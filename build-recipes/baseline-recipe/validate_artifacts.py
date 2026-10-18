"""Validate staged GKI artifacts without access to a physical device."""

import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import struct
import tarfile

from elftools.elf.elffile import ELFFile
from cryptography import x509
from cryptography.hazmat.primitives import serialization

HOST = Path(__file__).resolve().parents[2]
INPUTS = Path(__file__).resolve().parent
OUT = HOST / "artifacts/realme-note60x/gki-wifi1"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def main():
    config = (OUT / "kernel.config").read_bytes()
    image = (OUT / "Image").read_bytes()
    assert image[56:60] == b"ARM\x64"
    assert 4096 < len(image) < 64 * 1024 * 1024 - 4096
    assert gzip.decompress((OUT / "Image.gz").read_bytes()) == image
    begin = image.index(b"IKCFG_ST") + 8
    end = image.index(b"IKCFG_ED", begin)
    assert gzip.decompress(image[begin:end]) == config
    stock_cert = x509.load_pem_x509_certificate((OUT / "stock-module-cert.pem").read_bytes())
    assert stock_cert.public_bytes(serialization.Encoding.DER) in image
    assert (OUT / "module-signing-cert.x509").read_bytes() in image
    for expected in ("CONFIG_CFG80211=m", "CONFIG_MAC80211=m", "CONFIG_MT76x2U=m",
                     "CONFIG_ATH9K_HTC=m", "CONFIG_MODVERSIONS=y", "CONFIG_CFI_CLANG=y",
                     "CONFIG_LTO_CLANG_THIN=y", "CONFIG_DEBUG_INFO_BTF=y",
                     "CONFIG_DEBUG_INFO_BTF_MODULES=y", "CONFIG_MODULE_SIG_PROTECT=y"):
        assert expected.encode() in config.splitlines(), expected
    assert b'CONFIG_CFG80211_REQUIRE_SIGNED_REGDB=y' in config.splitlines()
    assert b'CONFIG_CFG80211_USE_KERNEL_REGDB_KEYS=y' in config.splitlines()
    system_map = (OUT / "System.map").read_text()
    assert "__cfi_check" in system_map
    with (OUT / "vmlinux").open("rb") as stream:
        elf = ELFFile(stream)
        assert elf.header["e_machine"] == "EM_AARCH64" and elf.elfclass == 64
        assert elf.get_section_by_name(".BTF") is not None

    # Reuse the host-only ELF metadata reader, not any historical device tool.
    spec = importlib.util.spec_from_file_location("stock_inspector", INPUTS / "inspect_stock.py")
    inspector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inspector)
    available = {}
    for path in (OUT / "Module.symvers", *OUT.glob("rtl*.symvers")):
        for line in path.read_text().splitlines():
            fields = line.split()
            assert len(fields) >= 4
            crc, symbol, owner = fields[:3]
            row = {"crc": crc.lower(), "owner": owner}
            assert symbol not in available or available[symbol]["crc"] == row["crc"]
            available[symbol] = row
    stock = json.loads((INPUTS / "vendor-module-abi.json").read_text())
    matches, missing, mismatches = [], [], []
    for name, expected in stock["non_vendor_module_import_crcs"].items():
        actual = available.get(name)
        if actual is None:
            missing.append(name)
        elif actual["crc"] != expected:
            mismatches.append({"symbol": name, "stock": expected, "built": actual["crc"]})
        else:
            matches.append(name)
    abi = {"saved_vendor_modules": len(stock["modules"]), "matched_symbols": len(matches),
           "missing_symbols": missing, "CRC_mismatches": mismatches,
           "saved_vendor_boot_imports_compatible": not missing and not mismatches,
           "scope_limit": stock["limits"], "hardware_tested": False}
    write_json("vendor-abi-validation.json", abi)

    modules = []
    module_errors = []
    release = json.loads((OUT / 'build-manifest.json').read_text())['kernelrelease_retained_from_stock']
    for path in sorted((OUT / "modules").glob("*.ko")):
        raw = path.read_bytes()
        metadata = inspector.module_metadata(path.name, raw)
        assert metadata['modinfo']['vermagic'][0].split()[0] == release, path.name
        assert metadata["cfi_check_defined"], path.name
        assert raw.endswith(b"~Module signature appended~\n"), path.name
        for name, expected in metadata["import_crcs"].items():
            actual = available.get(name)
            if not actual or actual["crc"] != expected:
                module_errors.append({"module": path.name, "symbol": name,
                                      "expected": expected, "available": actual})
        metadata["signature_footer_present"] = True
        elf = ELFFile(io.BytesIO(raw))
        symbols = elf.get_section_by_name(".symtab")
        metadata["monitor_tx_symbols"] = sorted({symbol.name for symbol in symbols.iter_symbols()
            if "monitor" in symbol.name.lower() and any(word in symbol.name.lower() for word in ("xmit", "tx"))})
        metadata["BTF_present"] = elf.get_section_by_name(".BTF") is not None
        assert metadata['BTF_present'], path.name
        modules.append(metadata)
    write_json("module-validation.json", {"modules": modules, "import_errors": module_errors})
    by_name = {row["file"]: row for row in modules}
    for name, usb_id in [("88XXau.ko", "v0BDAp8812"), ("8188eu.ko", "v2357p010C"),
                         ("88x2bu.ko", "v0BDApB812"), ("ath9k_htc.ko", "v0CF3p9271"),
                         ("mt76x2u.ko", "v0E8Dp7612")]:
        assert name in by_name, name
        aliases = by_name[name]["modinfo"].get("alias", [])
        assert any(usb_id in alias for alias in aliases), (name, usb_id)
        if name in ("88XXau.ko", "8188eu.ko", "88x2bu.ko"):
            assert by_name[name]["monitor_tx_symbols"], name
    assert by_name["mac80211.ko"]["monitor_tx_symbols"]
    assert not module_errors, module_errors[:10]
    assert not missing and not mismatches, abi
    # Record the dependencies as data, without any automatic load script.
    names = {row["file"].removesuffix(".ko").replace("-", "_"): row for row in modules}
    ordered, visiting, visited = [], set(), set()

    def visit(name):
        if name in visited or name not in names:
            return
        assert name not in visiting, "Module dependency cycle"
        visiting.add(name)
        dependencies = names[name]["modinfo"].get("depends", [""])[0].split(",")
        for dependency in dependencies:
            if dependency:
                visit(dependency.replace("-", "_"))
        visiting.remove(name)
        visited.add(name)
        ordered.append(names[name]["file"])

    for name in ("88XXau", "8188eu", "88x2bu", "ath9k_htc", "mt76x2u"):
        visit(name)
    (OUT / "wifi-module-load-order.txt").write_text("\n".join(ordered) + "\n")
    write_json("module-dependencies.json", {
        row["file"]: row["modinfo"].get("depends", [""])[0].split(",") for row in modules
    })

    firmware = OUT / "firmware"
    firmware.mkdir(exist_ok=True)
    for name, reference in [("mt76-firmware-manifest.json", "mt7612u-firmware"),
                            ("ar9271-firmware-manifest.json", "ar9271-firmware")]:
        manifest = json.loads((HOST / "build" / name).read_text())
        for row in manifest["files"]:
            source = HOST / ".reference" / reference / row["file"]
            assert source.stat().st_size == row["size"] and sha(source) == row["sha256"]
            target = firmware / row["file"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        shutil.copyfile(HOST / "build" / name, OUT / name)
    regdb = HOST / ".reference/realme-note60x/regulatory-db"
    manifest = json.loads((regdb / "source-manifest.json").read_text())
    for row in manifest["files"]:
        source = regdb / row["file"]
        assert sha(source) == row["sha256"]
        target = firmware / ("LICENSES/wireless-regdb-LICENSE" if row["file"] == "LICENSE" else row["file"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    shutil.copyfile(regdb / "source-manifest.json", OUT / "regulatory-db-manifest.json")
    with tarfile.open(OUT / "wifi-modules-and-firmware.tar.gz", "w:gz") as archive:
        for path in sorted((OUT / "modules").glob("*.ko")):
            archive.add(path, arcname="modules/" + path.name)
        archive.add(firmware, arcname="firmware")
        archive.add(OUT / "wifi-module-load-order.txt", arcname="wifi-module-load-order.txt")
        archive.add(OUT / "module-dependencies.json", arcname="module-dependencies.json")

    # Build an unsigned boot v4 image as data. Keep the stock header fields,
    # replace the kernel and remove the obsolete optional boot signature.
    stock_boot = HOST / "backups/realme-note60x-critical-20261011T180537Z/boot_b.bin"
    assert sha(stock_boot) == "4432fa1827b9f4cb12816d646d6b4be08b10d65537bda9f5d2c10b554a53bf4f"
    original = stock_boot.read_bytes()
    header = bytearray(original[:4096])
    assert header[:8] == b"ANDROID!" and struct.unpack_from("<I", header, 40)[0] == 4
    assert struct.unpack_from("<I", header, 12)[0] == 0
    struct.pack_into("<I", header, 8, len(image))
    struct.pack_into("<I", header, 1580, 0)
    boot = header + image
    boot.extend(b"\0" * (len(original) - len(boot)))
    (OUT / "boot-unsigned.img").write_bytes(boot)
    assert boot[4096:4096 + len(image)] == image
    assert len(boot) == 64 * 1024 * 1024
    assert not any(boot[4096 + len(image):])
    write_json("boot-image-validation.json", {
        "file": "boot-unsigned.img", "bytes": len(boot), "boot_header_version": 4,
        "kernel_bytes": len(image), "ramdisk_bytes": 0, "optional_boot_signature_bytes": 0,
        "stock_header_fields_preserved_except_kernel_size_and_signature_size": True,
        "OEM_AVB_footer_and_signature_present": False, "Magisk_init_boot_modified": False,
        "loaded_or_flashed": False, "hardware_acceptance_verified": False
    })
    record = json.loads((OUT / "build-manifest.json").read_text())
    record["validation_pending"] = False
    record["saved_vendor_boot_ABI_verified"] = True
    record["boot_image"] = "boot-unsigned.img"
    write_json("build-manifest.json", record)
    write_json("validation-summary.json", {
        "Image_AArch64": True, "gzip_matches_Image": True, "embedded_config_matches": True,
        "CFI_BTF_preserved": True, "LTO_mode": "Thin LTO (stock used Full LTO)", "module_import_CRCS_verified": True,
        "USB_IDs_verified": True, "monitor_TX_symbols_verified": True,
        "saved_vendor_boot_ABI_verified": True, "vendor_imports_checked": len(matches),
        "module_count": len(modules), "firmware_sources_verified": True,
        "hardware_boot_monitor_mode_injection_tested": False, "physical_device_accessed": False
    })
    print(json.dumps({"validation_passed": True, "modules": len(modules),
                      "vendor_imports_matched": len(matches), "Image_bytes": len(image)}))


if __name__ == "__main__":
    main()
