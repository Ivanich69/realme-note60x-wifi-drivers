"""Package/check reviewed Full LTO boot and its versioned companion, on PC only."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import zipfile

from realme_avb_integrity import inspect_avb, require

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "artifacts/realme-note60x/gki-wifi2-full-lto"
OUT = ROOT / "artifacts/realme-note60x/wifi2-reviewed"
STOCK = ROOT / "artifacts/realme-note60x/stock-boot-b-restore-review/boot_b-original-C13.img"
TOOL = ROOT / "tools/avb-reviewed/avbtool.py"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def command(*args, expected=0):
    result = subprocess.run([sys.executable, str(TOOL), *map(str, args)], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    require(result.returncode == expected, f"AVB command failed: {result.stderr}")
    return {"args": list(map(str, args)), "exit_code": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}


def main(variant='wifi2'):
    require(file_sha(TOOL) == "e5a664a38db623da00f080219bc0ee60a640a9dc4a872803616fae4938ac749b",
            "AOSP avbtool pin changed")
    summary = read_json(ART / "validation-summary.json")
    require(summary["LTO_mode"] == "Full LTO (same mode as stock)", "Wrong LTO variant")
    require(summary["saved_vendor_boot_ABI_verified"] and summary["module_count"] == 17,
            "Kernel/module checks not complete")
    signatures = read_json(ART / "signature-validation.json")
    require(len(signatures["modules"]) == 17 and all(r["PKCS7_signature_verified"] for r in signatures["modules"]),
            "Module signature checks incomplete")
    require(signatures["regulatory_db_signature_verified_with_kernel_certificates"], "Regdb check incomplete")
    compatibility = read_json(ART / "full-module-compatibility.json")
    require(not compatibility["core_incompatible_modules"] and
            not compatibility["stock_vs_new_cfg80211_differences"] and
            not compatibility["stock_drivers_with_new_cfg80211_errors"], "ABI mismatch")
    require(all(not r["cfg80211_errors"] for r in compatibility["new_drivers_with_stock_cfg80211"]),
            "Stock cfg80211 mismatch")
    bounds = read_json(ART / "monitor-bounds-validation.json")
    require(bounds["passed"] and bounds["boundary_cases"] == 128, "Bounds tests not complete")
    cfi = read_json(ART / "xmit-cfi-validation.json")
    require(cfi["passed"] and len(cfi["callbacks"]) == 3 and cfi["legacy_type_rejected"],
            "TX callback CFI check incomplete")
    compiled_cfi = read_json(ART / "compiled-xmit-cfi-validation.json")
    require(compiled_cfi["passed"] and len(compiled_cfi["objects"]) == 3, "Compiled TX CFI check incomplete")
    stock = STOCK.read_bytes()
    require(sha(stock) == "4432fa1827b9f4cb12816d646d6b4be08b10d65537bda9f5d2c10b554a53bf4f", "Wrong original B")
    stock_avb = inspect_avb(stock)
    require(stock_avb["integrity_checks_pass"], "Saved stock integrity failed")
    image = (ART / "Image").read_bytes()
    require(image[56:60] == b"ARM\x64", "Not an ARM64 Image")
    header = bytearray(stock[:4096])
    require(struct.unpack_from("<I", header, 12)[0] == 0, "Unexpected ramdisk")
    require(struct.unpack_from("<I", header, 1580)[0] == 0, "Unexpected GKI boot signature")
    struct.pack_into("<I", header, 8, len(image))
    raw = header + image
    raw.extend(bytes((-len(raw)) % 4096))
    require(len(raw) < len(stock) - 69632, "Insufficient room for metadata")
    OUT.mkdir(exist_ok=True)
    boot = OUT / "boot.img"
    boot.write_bytes(raw)
    args = ["add_hash_footer", "--image", boot, "--partition_size", len(stock),
            "--partition_name", "boot", "--hash_algorithm", "sha256", "--algorithm", "NONE",
            "--salt", stock_avb["hash_descriptors"][0]["salt"], "--flags", 0,
            "--rollback_index", stock_avb["rollback_index"],
            "--rollback_index_location", stock_avb["rollback_index_location"]]
    for key, value in stock_avb["properties"].items():
        args += ["--prop", f"{key}:{value}"]
    packed = command(*args)
    final = boot.read_bytes()
    avb = inspect_avb(final)
    require(len(final) == len(stock) == 67108864, "Wrong output boot size")
    require(final[:len(raw)] == raw and final[4096:4096 + len(image)] == image, "Payload changed")
    require(avb["integrity_checks_pass"] and avb["algorithm_type"] == 0 and avb["vbmeta_flags"] == 0,
            "Unsigned image integrity failed")
    verified = command("verify_image", "--image", boot)
    negative_dir = OUT / ".corruption-check"
    negative_dir.mkdir(exist_ok=True)
    negative = negative_dir / "boot.img"
    altered = bytearray(final)
    altered[8192] ^= 1
    require(not inspect_avb(altered)["integrity_checks_pass"], "Independent checker missed corruption")
    negative.write_bytes(altered)
    rejected = command("verify_image", "--image", negative, expected=1)
    require("digest" in (rejected["stdout"] + rejected["stderr"]).lower(), "Unexpected negative-check result")
    negative.unlink()
    negative_dir.rmdir()
    config_hash = file_sha(ART / "kernel.config")
    zip_path = OUT / f"realme-note60x-{variant}-magisk.zip"
    order = []
    with zipfile.ZipFile(zip_path) as archive:
        require(archive.testzip() is None, "Corrupt companion ZIP")
        names = archive.namelist()
        require(len(names) == len(set(names)), "Duplicate ZIP entries")
        require(not any(n.endswith(".img") for n in names), "Image inside companion ZIP")
        require("auto-load.enabled" not in names, "Unexpected autoload flag")
        require(config_hash in archive.read("load-wifi.sh").decode(), "Companion config guard differs")
        require(f"version={variant}\n" in archive.read("module.prop").decode(), "Wrong companion version")
        order = archive.read("load-order.txt").decode().splitlines()
        require(len(order) == len(set(order)) == 14, "Wrong companion module count")
        dependencies = read_json(ART / "module-dependencies.json")
        available = {"cfg80211"}
        for module in order:
            require(archive.read("drivers/" + module) == (ART / "modules" / module).read_bytes(), "Wrong module payload")
            needs = {n.replace("-", "_") for n in dependencies[module] if n}
            require(needs <= available, f"Unresolved dependencies for {module}")
            available.add(module[:-3].replace("-", "_"))
        sums = archive.read("payload.sha256").decode().splitlines()
        require(len(sums) == 17, "Incomplete payload manifest")
        covered = []
        for line in sums:
            expected, name = line.split("  ", 1)
            require(sha(archive.read(name)) == expected, "ZIP payload checksum mismatch")
            covered.append(name)
            if name.startswith("system/vendor/firmware/"):
                require(archive.read(name) == (ART / "firmware" / name.removeprefix("system/vendor/firmware/")).read_bytes(),
                        "Firmware differs from validated build")
        require(set(covered) == {n for n in names if n.endswith((".ko", ".fw", ".bin"))}, "Missing ZIP checksum coverage")
    expanded = None
    if variant == 'wifi3':
        expanded = read_json(ART / 'callback-CFI-validation.json')
        require(expanded['passed'] and not expanded['mismatches'], 'Expanded CFI audit failed')
        require(len(expanded['comparisons']) == 156, 'Incomplete expanded audit')
    report = {"scope": f"Host-only {variant} boot/companion packaging; no device interaction",
              "target": "Realme Note 60x RMX3938 RMX3938export_15_C.13",
              "variant": ('wifi2-full-lto' if variant == 'wifi2' else 'wifi3-cfi-monitor'),
              "image": {"file": boot.name, "bytes": len(final), "sha256": sha(final),
                        "kernel_sha256": sha(image), "config_sha256": config_hash,
                        "header_version": 4, "ramdisk_bytes": 0, "OEM_signed": False},
              "AVB": avb, "companion": {"file": zip_path.name, "bytes": zip_path.stat().st_size,
                        "sha256": file_sha(zip_path), "modules": order, "uses_stock_cfg80211": True,
                        "config_guard_matches": True, "load_order_valid": True,
                        "payload_checksums_verified": 17, "autoload_enabled": False},
              "cached_core_module_checks": len(compatibility["stock_core_checks"]),
              "cached_ABI_incompatibilities": 0, "bounds_tests": bounds, "TX_callback_CFI": cfi,
              "compiled_TX_callback_CFI": compiled_cfi,
              "source_changes": read_json(ART / f"{variant}-inputs.json")["source_changes"],
              "expanded_callback_CFI": expanded,
              "official_AVB_checks": {"packaging": packed, "verification": verified,
                                      "corruption_rejected": rejected},
              "all_host_checks_complete": True, "hardware_boot_verified": False,
              "monitor_injection_radio_tested": False, "boot_chain_authentication_satisfied": False,
              "unlocked_Realme_acceptance_proven": False, "independent_recovery_route_proven": False,
              "device_operations": [], "packaging_script_sha256": file_sha(Path(__file__))}
    (OUT / "review.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "image_sha256": sha(final), "zip_sha256": file_sha(zip_path),
                      "all_host_checks_complete": True, "hardware_tested": False}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts', type=Path, default=ART)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--variant', choices=('wifi2', 'wifi3'), default='wifi2')
    args = parser.parse_args()
    ART, OUT = args.artifacts.resolve(), args.output.resolve()
    require(ART.is_relative_to(ROOT / 'artifacts/realme-note60x'), 'Unexpected artifact path')
    require(OUT.is_relative_to(ROOT / 'artifacts/realme-note60x'), 'Unexpected package path')
    main(args.variant)
