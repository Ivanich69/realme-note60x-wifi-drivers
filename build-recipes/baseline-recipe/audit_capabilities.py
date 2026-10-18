"""Record monitor/TX implementation evidence from the pinned source trees."""

import hashlib
import json
import os
from pathlib import Path

HOST = Path("/mnt/f/wifi_work")
ROOT = Path(os.environ.get("REALME_WORKSPACE", "/home/sad1/wifi-kernel-realme-note60x"))
ARTIFACTS = HOST / "artifacts/realme-note60x/gki-wifi1"


def record(path, needles):
    raw = path.read_bytes()
    text = raw.decode(errors="replace")
    result = {needle: needle in text for needle in needles}
    assert all(result.values()), (str(path), result)
    return {"file": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(raw).hexdigest(),
            "implementation_markers": result}


def main():
    ARTIFACTS.mkdir(exist_ok=True)
    rows = []
    for name, chip in [("rtl8812au", "RTL8812AU"), ("rtl8188eus", "RTL8188EUS"),
                       ("rtl8812bu", "RTL8812BU / RTL8822BU")]:
        driver = ROOT / "drivers" / name
        evidence = [record(driver / "Makefile", ["CONFIG_WIFI_MONITOR = y"]),
                    record(driver / "os_dep/linux/ioctl_cfg80211.c", ["NL80211_IFTYPE_MONITOR"])]
        tx_candidates = [driver / "core/rtw_xmit.c", driver / "os_dep/linux/xmit_linux.c",
                         driver / "os_dep/linux/ioctl_cfg80211.c"]
        tx = next(path for path in tx_candidates if "rtw_monitor_xmit_entry" in path.read_text())
        evidence.append(record(tx, ["rtw_monitor_xmit_entry"]))
        rows.append({"chipset": chip, "driver": name, "monitor_enabled": True,
                     "monitor_TX_implementation_present": True, "sources": evidence})
    common = ROOT / "common"
    mac = record(common / "net/mac80211/tx.c", ["ieee80211_monitor_start_xmit", "ieee80211_parse_tx_radiotap"])
    rows.append({"chipset": "AR9271", "driver": "ath9k_htc", "monitor_enabled": True,
                 "monitor_TX_implementation_present": True,
                 "sources": [mac, record(common / "drivers/net/wireless/ath/ath9k/htc_drv_main.c",
                     ["NL80211_IFTYPE_MONITOR", "ath9k_htc_tx"])]})
    rows.append({"chipset": "MT7612U", "driver": "mt76x2u", "monitor_enabled": True,
                 "monitor_TX_implementation_present": True,
                 "sources": [mac, record(common / "drivers/net/wireless/mediatek/mt76/mt76x2/usb_main.c",
                     ["mt76x02_tx", "mt76x02_configure_filter"])]})
    report = {"drivers": rows, "on_air_reception_injection_or_channel_switching_tested": False,
              "scope": "Implementation and build evidence only; no device or radio tests"}
    (ARTIFACTS / "driver-capabilities.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"source_capabilities_checked": len(rows), "hardware_tested": False}))


if __name__ == "__main__":
    main()
