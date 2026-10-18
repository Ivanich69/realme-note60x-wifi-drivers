"""Prepare wifi2 source fixes/config on the PC. Never starts WSL or a device."""

import difflib
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
BASE = ROOT / "artifacts/realme-note60x/gki-wifi1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def replace_once(text, before, after):
    require(text.count(before) == 1, f"Source context changed: {before[:90]}")
    return text.replace(before, after, 1)


def main():
    bundle = BASE / "sources/driver-sources-and-config.tar.gz"
    manifest = json.loads((BASE / "SHA256SUMS.json").read_text())
    source_pin = next(row for row in manifest if row["file"] == "sources/driver-sources-and-config.tar.gz")
    require(sha(bundle.read_bytes()) == source_pin["sha256"], "Baseline sources changed")
    config = (BASE / "kernel.config").read_bytes()
    require(sha(config) == "964a06b43b5906aae9386657263b773472d17cb22b7b492f13eba1acc13eb9ca",
            "Baseline kernel config changed")
    full = replace_once(config.decode(), "# CONFIG_LTO_CLANG_FULL is not set\n", "CONFIG_LTO_CLANG_FULL=y\n")
    full = replace_once(full, "CONFIG_LTO_CLANG_THIN=y\n", "# CONFIG_LTO_CLANG_THIN is not set\n")
    require("CONFIG_CFI_CLANG=y\n" in full, "CFI must remain enabled")
    (HERE / "full-lto.config").write_bytes(full.encode())
    changes, patches = [], []
    with tarfile.open(bundle) as archive:
        for driver in ("rtl8812au", "rtl8188eus"):
            name = f"drivers/{driver}/core/rtw_xmit.c"
            before = archive.extractfile(name).read().decode()
            begin = before.index("s32 rtw_monitor_xmit_entry(")
            end = before.index("\n/*\n * The main transmit", begin)
            prefix, body, suffix = before[:begin], before[begin:end], before[end:]
            if driver == "rtl8812au":
                old = ("\tif (unlikely(skb->len < rtap_len))\n\t\tgoto fail;\n\n"
                       "\tif (unlikely(rtap_len < sizeof(struct ieee80211_radiotap_header)))\n\t\tgoto fail;")
                new = ("\t/* Bound both copy destinations before consuming packet bytes. */\n"
                       "\tif (unlikely(rtap_len < sizeof(*rtap_hdr) ||\n"
                       "\t\trtap_len > sizeof(rtap_buf) || rtap_len > skb->len ||\n"
                       "\t\tskb->len - rtap_len < WLAN_HDR_A3_LEN ||\n"
                       "\t\tskb->len - rtap_len > MAX_XMIT_EXTBUF_SZ - TXDESC_OFFSET))\n"
                       "\t\tgoto fail;")
                body = replace_once(body, old, new)
            else:
                body = replace_once(body, "\tstruct pkt_file pktfile;", "\tstruct pkt_file pktfile = {0};")
                body = replace_once(body, "\tu8 dummybuf[32];\n\tint len = skb->len, rtap_len, consume;",
                                    "\tint len = skb->len, rtap_len;")
                body = replace_once(body, "\tif (unlikely(skb->len < rtap_len))\n\t\tgoto fail;",
                    "\t/* Check lengths before subtracting or copying the frame. */\n"
                    "\tif (unlikely(rtap_len < sizeof(rtap_hdr) || rtap_len > skb->len ||\n"
                    "\t\tskb->len - rtap_len < WLAN_HDR_A3_LEN ||\n"
                    "\t\tskb->len - rtap_len > MAX_XMIT_EXTBUF_SZ - TXDESC_OFFSET))\n"
                    "\t\tgoto fail;")
                start = body.index("\tlen -= sizeof(struct ieee80211_radiotap_header);")
                stop = body.index("\n\tpmgntframe = alloc_mgtxmitframe", start)
                body = body[:start] + (
                    "\t/* Skip radiotap bytes without a temporary copy or signed loop. */\n"
                    "\t_rtw_pktfile_read(&pktfile, NULL, rtap_len - sizeof(rtap_hdr));\n"
                    "\tlen -= rtap_len;\n") + body[stop:]
            after = prefix + body + suffix
            path = HERE / "sources" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(after.encode())
            changes.append({"file": name, "before_sha256": sha(before.encode()),
                            "after_sha256": sha(after.encode())})
            patches.extend(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                              fromfile="a/" + name, tofile="b/" + name))
        # Linux ndo_start_xmit has an enum return type. An int return has a
        # different Clang CFI identity even though its machine representation fits.
        for driver in ("rtl8188eus", "rtl8812bu"):
            for suffix in ("os_dep/linux/xmit_linux.c", "include/xmit_osdep.h"):
                name = f"drivers/{driver}/{suffix}"
                before = archive.extractfile(name).read().decode()
                if suffix.endswith(".c"):
                    after = replace_once(before,
                        "int rtw_xmit_entry(_pkt *pkt, _nic_hdl pnetdev)",
                        "netdev_tx_t rtw_xmit_entry(_pkt *pkt, _nic_hdl pnetdev)")
                else:
                    split = before.index("#ifdef PLATFORM_LINUX")
                    after = before[:split] + replace_once(before[split:],
                        "extern int rtw_xmit_entry(_pkt *pkt, _nic_hdl pnetdev);",
                        "extern netdev_tx_t rtw_xmit_entry(_pkt *pkt, _nic_hdl pnetdev);")
                path = HERE / "sources" / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(after.encode())
                changes.append({"file": name, "before_sha256": sha(before.encode()),
                                "after_sha256": sha(after.encode())})
                patches.extend(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True),
                                                  fromfile="a/" + name, tofile="b/" + name))
    (HERE / "monitor-tx-bounds.patch").write_bytes("".join(patches).encode())
    record = {"variant": "wifi2-full-lto", "scope": "Host-only source preparation",
              "source_bundle": bundle.relative_to(ROOT).as_posix(), "source_bundle_sha256": source_pin["sha256"],
              "config_seed_sha256": sha(full.encode()), "baseline_config_sha256": sha(config),
              "kernel_config_changes": ["LTO_CLANG_FULL=n -> y", "LTO_CLANG_THIN=y -> n"],
              "source_changes": changes, "compiled": False, "hardware_tested": False,
              "additional_CFI_fix": "Linux RTL8188EUS/RTL8812BU ndo_start_xmit returns netdev_tx_t",
              "existing_artifacts_modified": False, "WSL_started": False,
              "patch_sha256": sha((HERE / "monitor-tx-bounds.patch").read_bytes())}
    (HERE / "inputs.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
