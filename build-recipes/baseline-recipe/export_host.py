"""Stage compiled kernel/module files and source changes on the host."""

import hashlib
import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile

HOST = Path("/mnt/f/wifi_work")
ROOT = Path(os.environ.get("REALME_WORKSPACE", "/home/sad1/wifi-kernel-realme-note60x"))
OUT = ROOT / "out-wifi1"
ARTIFACTS = HOST / "artifacts/realme-note60x/gki-wifi1"


def main():
    ARTIFACTS.mkdir(exist_ok=True)
    original_pins = json.loads((HOST / "build/source-manifest.json").read_text())
    bu_pin = json.loads((HOST / "build/rtl8812bu-source-manifest.json").read_text())["rtl8812bu"]
    pins = {"rtl8812au": original_pins["rtl8812au"],
            "rtl8188eus": original_pins["rtl8188eus"], "rtl8812bu": bu_pin}
    for relative, name in [
        ("arch/arm64/boot/Image", "Image"), ("arch/arm64/boot/Image.gz", "Image.gz"),
        ("vmlinux", "vmlinux"), ("System.map", "System.map"),
        ("Module.symvers", "Module.symvers"), (".config", "kernel.config"),
        ("modules.order", "modules.order"), ("modules.builtin", "modules.builtin"),
        ("certs/signing_key.x509", "module-signing-cert.x509")
    ]:
        shutil.copyfile(OUT / relative, ARTIFACTS / name)
    modules_out = ARTIFACTS / "modules"
    modules_out.mkdir(exist_ok=True)
    for module in sorted((ROOT / "stage-wifi1").rglob("*.ko")):
        target = modules_out / module.name
        assert not target.exists() or target.read_bytes() == module.read_bytes(), module.name
        shutil.copyfile(module, target)
    for name in ("rtl8812au", "rtl8188eus", "rtl8812bu"):
        shutil.copyfile(ROOT / "drivers" / name / "Module.symvers", ARTIFACTS / f"{name}.symvers")
    shutil.copyfile(HOST / "logs/realme-note60x-wifi1-build.log", ARTIFACTS / "build.log")
    for name in ("stock-module-cert.pem", "stock-module-certificate.json", "stock-kernel-inspection.json",
                 "source-changes.json", "clang-source-pin.json", "build-tools-pin.json"):
        shutil.copyfile(HOST / "build/realme-note60x" / name, ARTIFACTS / name)

    # The source bundle contains the three complete GPL drivers (patched),
    # plus the small changes to pinned AOSP. No generated private keys.
    source_bundle = ARTIFACTS / "sources/driver-sources-and-config.tar.gz"
    patches = []
    changes = json.loads((HOST / "build/realme-note60x/source-changes.json").read_text())
    assert len({row['file'] for row in changes}) == len(changes)
    for row in changes:
        relative = Path(row['file'])
        assert relative.parts[0] == 'drivers' and relative.parts[1] in pins
        name = relative.parts[1]
        original = Path('/home/sad1/wifi-kernel-sweet/drivers') / name
        old = subprocess.check_output(['git', '-C', str(original), 'show',
                                      pins[name]['commit'] + ':' + '/'.join(relative.parts[2:])])
        new = (ROOT / relative).read_bytes()
        assert hashlib.sha256(old).hexdigest() == row['before_sha256'], row['file']
        assert hashlib.sha256(new).hexdigest() == row['after_sha256'], row['file']
        patches.extend(difflib.unified_diff(old.decode().splitlines(keepends=True),
                       new.decode().splitlines(keepends=True),
                       fromfile='a/' + row['file'], tofile='b/' + row['file']))
    patch_path = ARTIFACTS / 'sources/realtek-compat.patch'
    patch_path.write_text(''.join(patches))
    with tarfile.open(source_bundle, "w:gz") as archive:
        archive.add(patch_path, arcname='realtek-compat.patch')
        for name in ("rtl8812au", "rtl8188eus", "rtl8812bu"):
            driver = ROOT / "drivers" / name
            # The pinned tree supplies the complete file list, including assembly,
            # licenses and build helpers, without generated objects or private keys.
            original = Path("/home/sad1/wifi-kernel-sweet/drivers") / name
            tracked = subprocess.check_output(
                ["git", "-C", str(original), "ls-tree", "-rz", "--name-only", pins[name]["commit"]])
            for relative in tracked.decode().split("\0"):
                if not relative:
                    continue
                path = driver / relative
                assert path.is_file() and path.resolve().is_relative_to(driver.resolve()), relative
                assert path.name != "signing_key.pem"
                archive.add(path, arcname=str(path.relative_to(ROOT)))
        archive.add(OUT / ".config", arcname="kernel.config")
        archive.add(ROOT / "abi_symbollist.raw", arcname="abi_symbollist.raw")
        archive.add(ROOT / "common/.scmversion", arcname="common/.scmversion")
        archive.add(ROOT / "common/certs/stock_gki_modules.pem", arcname="common/certs/stock_gki_modules.pem")
        for path in sorted((HOST / "build/realme-note60x").iterdir()):
            if path.is_file() and (path.suffix in {".py", ".sh"} or path.name in {
                "README.md", "stock-gki.config", "source-changes.json", "clang-source-pin.json",
                "build-tools-pin.json", "stock-module-certificate.json", "stock-module-cert.pem",
                "vendor-module-abi.json", "vendor-required-symbols.txt"}):
                archive.add(path, arcname="recipe/" + path.name)
    version = subprocess.check_output([str(ROOT / "clang-r450784e/bin/clang"), "--version"], text=True)
    record = {"scope": "Host-only GKI and companion module build for Realme RMX3938 C.13",
              "kernel_repository": "https://android.googlesource.com/kernel/common",
              "kernel_commit": "0c6055fd2d8b95ec88db7bfd79bfd1e471592215",
              "kernel_tag": "android13-5.15-2025-03_r2",
              "kernelrelease_retained_from_stock": (OUT / "include/config/kernel.release").read_text().strip(),
              "compiler": version.strip(), "driver_form": "modules",
              "physical_device_accessed": False, "hardware_tested": False,
              "native_driver_modules": ["ath9k_htc.ko", "mt76x2u.ko"],
              "external_driver_modules": ["88XXau.ko", "8188eu.ko", "88x2bu.ko"],
              "validation_pending": True}
    record["external_driver_sources"] = {
        name: {key: item[key] for key in ("repository", "commit")}
        for name, item in pins.items()
    }
    (ARTIFACTS / "build-manifest.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"artifacts": str(ARTIFACTS), "modules": len(list(modules_out.glob('*.ko')))}))


if __name__ == "__main__":
    main()
