"""Inspect pinned local Realme backups for a host-only kernel build."""

import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct

from elftools.elf.elffile import ELFFile
from cryptography import x509
from cryptography.hazmat.primitives import serialization

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
BACKUP = ROOT / "backups/realme-note60x-critical-20261011T180537Z"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def module_metadata(name, data):
    elf = ELFFile(io.BytesIO(data))
    assert elf.elfclass == 64 and elf.little_endian
    assert elf.header["e_machine"] == "EM_AARCH64"
    info = {}
    section = elf.get_section_by_name(".modinfo")
    if section:
        for field in section.data().split(b"\0"):
            if b"=" in field:
                key, value = field.decode("utf-8", errors="replace").split("=", 1)
                info.setdefault(key, []).append(value)
    versions = {}
    section = elf.get_section_by_name("__versions")
    if section:
        raw = section.data()
        assert len(raw) % 64 == 0, name
        for pos in range(0, len(raw), 64):
            crc = struct.unpack_from("<Q", raw, pos)[0]
            symbol = raw[pos + 8:pos + 64].split(b"\0", 1)[0].decode("ascii")
            assert symbol and crc <= 0xFFFFFFFF
            assert symbol not in versions
            versions[symbol] = f"0x{crc:08x}"
    symbols = elf.get_section_by_name(".symtab")
    exports = {}
    has_cfi_check = False
    if symbols:
        for symbol in symbols.iter_symbols():
            if symbol.name == "__cfi_check" and symbol["st_shndx"] != "SHN_UNDEF":
                has_cfi_check = True
            if symbol.name.startswith("__crc_") and symbol["st_shndx"] == "SHN_ABS":
                exports[symbol.name[6:]] = f"0x{symbol['st_value'] & 0xFFFFFFFF:08x}"
    return {"file": name, "bytes": len(data), "sha256": sha(data),
            "modinfo": info, "import_crcs": versions, "export_crcs": exports,
            "cfi_check_defined": has_cfi_check}


def main():
    manifest = json.loads((BACKUP / "SHA256SUMS.json").read_text(encoding="utf-8-sig"))
    images = {}
    for name in ("boot_b.bin", "vendor_boot_b.bin"):
        expected = next(row for row in manifest if row["file"] == name)
        data = (BACKUP / name).read_bytes()
        assert len(data) == expected["bytes"] and sha(data) == expected["sha256"]
        images[name] = data

    boot = images["boot_b.bin"]
    assert boot[:8] == b"ANDROID!" and struct.unpack_from("<I", boot, 40)[0] == 4
    kernel_size, ramdisk_size = struct.unpack_from("<II", boot, 8)
    assert ramdisk_size == 0 and kernel_size < len(boot) - 4096
    kernel = boot[4096:4096 + kernel_size]
    assert kernel[56:60] == b"ARM\x64"
    start = kernel.index(b"IKCFG_ST") + 8
    end = kernel.index(b"IKCFG_ED", start)
    config = gzip.decompress(kernel[start:end])
    assert 0 < len(config) < 1024 * 1024
    (OUT / "stock-gki.config").write_bytes(config)
    (OUT / "stock-Image").write_bytes(kernel)

    # Retain the public trust anchor for already signed stock GKI modules.
    # No private signing key is available or extracted from the image.
    certificates = []
    pos = 0
    while True:
        begin = kernel.find(b"\x30\x82", pos)
        if begin < 0:
            break
        pos = begin + 2
        length = int.from_bytes(kernel[begin + 2:begin + 4], "big") + 4
        if not 256 < length < 8192 or begin + length > len(kernel):
            continue
        der = kernel[begin:begin + length]
        try:
            certificate = x509.load_der_x509_certificate(der)
        except ValueError:
            continue
        certificates.append((begin, der, certificate))
    assert len(certificates) == 1
    begin, der, certificate = certificates[0]
    assert "kernel key" in certificate.subject.rfc4514_string().lower()
    (OUT / "stock-module-cert.pem").write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    write_json("stock-module-certificate.json", {
        "offset": begin, "bytes": len(der), "sha256": sha(der),
        "subject": certificate.subject.rfc4514_string(),
        "issuer": certificate.issuer.rfc4514_string(), "private_key_present": False
    })

    spec = importlib.util.spec_from_file_location(
        "host_image_parser", ROOT / "diagnostics/inspect_realme_magisk_image.py")
    parser = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(parser)
    parser.MAX_OUTPUT = 256 * 1024 * 1024
    vendor = images["vendor_boot_b.bin"]
    assert vendor[:8] == b"VNDRBOOT"
    version, page = struct.unpack_from("<II", vendor, 8)
    assert version == 4 and page == 4096
    ramdisk_size = struct.unpack_from("<I", vendor, 24)[0]
    header_size = struct.unpack_from("<I", vendor, 2096)[0]
    ramdisk_start = parser.aligned(header_size, page)
    expanded = parser.legacy_lz4(vendor[ramdisk_start:ramdisk_start + ramdisk_size])
    entries = parser.cpio(expanded)
    modules = [module_metadata(name, entry["data"]) for name, entry in entries.items()
               if name.endswith(".ko")]
    exports = {}
    for module in modules:
        for symbol, crc in module["export_crcs"].items():
            if symbol in exports:
                assert exports[symbol] == crc
            exports[symbol] = crc
    imports = {}
    for module in modules:
        for symbol, crc in module["import_crcs"].items():
            if symbol not in exports:
                if symbol in imports:
                    assert imports[symbol] == crc, symbol
                imports[symbol] = crc
    write_json("vendor-module-abi.json", {
        "source": str(BACKUP / "vendor_boot_b.bin"),
        "source_sha256": sha(vendor), "modules": modules,
        "non_vendor_module_import_crcs": imports,
        "vendor_module_export_crcs": exports,
        "limits": "Only modules in the saved vendor_boot ramdisk; vendor/system_dlkm modules in super are not captured."
    })
    (OUT / "vendor-required-symbols.txt").write_text(
        "\n".join(sorted(imports)) + "\n", encoding="utf-8")
    write_json("stock-kernel-inspection.json", {
        "source": str(BACKUP / "boot_b.bin"), "boot_sha256": sha(boot),
        "kernel_sha256": sha(kernel), "kernel_bytes": kernel_size,
        "config_sha256": sha(config), "config_bytes": len(config),
        "vendor_boot_modules": len(modules), "required_core_symbols": len(imports),
        "device_accessed": False
    })
    print(json.dumps({"config_bytes": len(config), "kernel_bytes": kernel_size,
                      "vendor_boot_modules": len(modules),
                      "required_core_symbols": len(imports)}))


if __name__ == "__main__":
    main()
