"""Prepare GKI configuration and external modules on the host only."""

import hashlib
import json
import os
from pathlib import Path
import re

HOST = Path("/mnt/f/wifi_work")
ROOT = Path(os.environ.get("REALME_WORKSPACE", "/home/sad1/wifi-kernel-realme-note60x"))
COMMON = ROOT / "common"
OUT = ROOT / "out-wifi1"
RELEASE = "5.15.178-android13-8-00006-g0c6055fd2d8b-ab13363910"


def main():
    assert (COMMON / "build.config.constants").read_text().strip().endswith("CLANG_VERSION=r450784e")
    makefile = (COMMON / "Makefile").read_text()
    assert re.search(r"^SUBLEVEL = 178$", makefile, re.M)
    # Retain the stock release string for the vendor module set. Artifact
    # hashes and manifests identify the custom build, never a copied signature.
    (COMMON / ".scmversion").write_text(RELEASE.removeprefix("5.15.178") + "\n")
    (COMMON / "certs/stock_gki_modules.pem").write_bytes(
        (HOST / "build/realme-note60x/stock-module-cert.pem").read_bytes())
    OUT.mkdir(exist_ok=True)
    (OUT / ".config").write_bytes((HOST / "build/realme-note60x/stock-gki.config").read_bytes())
    # genksyms-only hook includes are not all tracked by normal CPP deps.
    # Recreate this small object when regenerating the build configuration.
    hook_object = OUT / "drivers/android/vendor_hooks.o"
    if hook_object.exists():
        hook_object.unlink()
    whitelist = set()
    for path in (COMMON / "android").glob("abi_gki_aarch64*"):
        if path.suffix == ".xml" or not path.is_file():
            continue
        for line in path.read_text().splitlines():
            symbol = line.strip()
            if re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", symbol):
                whitelist.add(symbol)
    whitelist.update((HOST / "build/realme-note60x/vendor-required-symbols.txt").read_text().splitlines())
    # File helpers imported by the external GPL Realtek drivers.
    whitelist.update({'kernel_read', 'kernel_write', 'filp_open'})
    (ROOT / "abi_symbollist.raw").write_text("\n".join(sorted(whitelist)) + "\n")

    changes_path = HOST / "build/realme-note60x/source-changes.json"
    changes = json.loads(changes_path.read_text()) if changes_path.exists() else []

    def record_change(path, before, after):
        if before == after:
            return
        relative = str(path.relative_to(ROOT))
        prior = next((item for item in changes if item["file"] == relative), None)
        if prior:
            prior["after_sha256"] = hashlib.sha256(after.encode()).hexdigest()
        else:
            changes.append({"file": relative,
                            "before_sha256": hashlib.sha256(before.encode()).hexdigest(),
                            "after_sha256": hashlib.sha256(after.encode()).hexdigest()})
    for name in ("rtl8812au", "rtl8188eus", "rtl8812bu"):
        driver = ROOT / "drivers" / name
        path = driver / "Makefile"
        before = path.read_text()
        text = before
        text = re.sub(r"(?m)^(CONFIG_PLATFORM_[A-Za-z_0-9]+\s*=\s*)y\b", r"\1n", text)
        text = text.replace("CONFIG_RTW_WIFI_HAL = y", "CONFIG_RTW_WIFI_HAL = n")
        text = re.sub(r"(?m)^((?:ccflags-y|EXTRA_CFLAGS)\s*\+=\s*)-Wno-([\w-]+)([^\n]*)$",
                      r"\1$(call cc-disable-warning,\2)\3", text)
        marker = "# Realme GKI ARM64 external-module build\n"
        if marker not in text:
            text = (marker + "ccflags-y += -DCONFIG_LITTLE_ENDIAN -DCONFIG_IOCTL_CFG80211\n"
                    "ccflags-y += -DRTW_USE_CFG80211_STA_EVENT\n\n" + text)
        assert re.search(r"^CONFIG_WIFI_MONITOR\s*=\s*y$", text, re.M), name
        path.write_text(text)
        record_change(path, before, text)
        if name == "rtl8188eus":
            fixes = [("os_dep/linux/rtw_cfgvendor.c", "u16 kflags;", "gfp_t kflags;"),
                     ("hal/rtl8188e/usb/usb_halinit.c", "(IS_FULL_SPEED_USB(Adapter))", "IS_FULL_SPEED_USB(Adapter)")]
            for relative, old, new in fixes:
                path = driver / relative
                before = path.read_text()
                after = before.replace(old, new)
                path.write_text(after)
                record_change(path, before, after)
        if name == "rtl8812bu":
            path = driver / "core/rtw_xmit.c"
            before = path.read_text()
            text = before
            if "\tu8 dummybuf[32];\n" in text:
                text = text.replace("\tu8 dummybuf[32];\n", "")
                old_guard = "if (unlikely(skb->len < rtap_len))"
                assert text.count(old_guard) == 1
                text = text.replace(old_guard,
                    "if (unlikely(rtap_len < sizeof(rtap_hdr) || rtap_len > skb->len ||\n"
                    "\t\tskb->len - rtap_len < WLAN_HDR_A3_LEN ||\n"
                    "\t\tskb->len - rtap_len > MAX_XMIT_EXTBUF_SZ - TXDESC_OFFSET))")
                old_copy = "_rtw_pktfile_read(&pktfile, dummybuf, rtap_len-sizeof(struct ieee80211_radiotap_header));"
                assert text.count(old_copy) == 1
                text = text.replace(old_copy,
                    "_rtw_pktfile_read(&pktfile, NULL, rtap_len-sizeof(struct ieee80211_radiotap_header));")
                path.write_text(text)
                record_change(path, before, text)
            assert "rtap_len < sizeof(rtap_hdr)" in text
    changes_path.write_text(json.dumps(changes, indent=2) + "\n")
    print(json.dumps({"workspace": str(ROOT), "release": RELEASE,
                      "whitelisted_symbols": len(whitelist), "source_changes": changes}), flush=True)


if __name__ == "__main__":
    main()
