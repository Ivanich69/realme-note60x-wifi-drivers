"""Export only the separately compiled wifi2 files to the PC workspace."""

import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
HOST = HERE.parents[2]
WORKSPACE = Path("/home/sad1/wifi-kernel-realme-note60x")
VARIANT = WORKSPACE / "wifi2-full-lto"
OUT = VARIANT / "out"
ART = HOST / "artifacts/realme-note60x/gki-wifi2-full-lto"
BASE = HOST / "artifacts/realme-note60x/gki-wifi1"


def sha(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    result = json.loads((VARIANT / "compile-result.json").read_text())
    assert result["compiled"] and result["module_count"] == 17
    assert result["TX_callback_CFI_verified"]
    assert result["compiled_TX_callback_CFI_verified"]
    inputs = json.loads((HERE / "inputs.json").read_text())
    assert result["inputs"] == inputs
    config = (OUT / ".config").read_bytes()
    assert b"CONFIG_LTO_CLANG_FULL=y\n" in config and b"CONFIG_CFI_CLANG=y\n" in config
    assert b"CONFIG_LTO_CLANG_THIN=y\n" not in config
    def config_values(data):
        return dict(line.split("=", 1) for line in data.decode().splitlines()
                    if line.startswith("CONFIG_") and "=" in line)
    before, after = config_values((BASE / "kernel.config").read_bytes()), config_values(config)
    config_changes = {key: [before.get(key, "n"), after.get(key, "n")]
                      for key in sorted(before.keys() | after.keys())
                      if before.get(key, "n") != after.get(key, "n")}
    assert config_changes == {"CONFIG_LTO_CLANG_FULL": ["n", "y"],
                              "CONFIG_LTO_CLANG_THIN": ["y", "n"]}, config_changes
    ART.mkdir(exist_ok=True)
    (ART / "config-delta-validation.json").write_text(json.dumps({
        "passed": True, "only_semantic_config_changes": config_changes,
        "previous_config_sha256": sha(BASE / "kernel.config"),
        "new_config_sha256": sha(OUT / ".config")}, indent=2) + "\n")
    for name in ["modules", "sources"]:
        (ART / name).mkdir(exist_ok=True)
    for relative, name in [
        ("arch/arm64/boot/Image", "Image"), ("arch/arm64/boot/Image.gz", "Image.gz"),
        ("vmlinux", "vmlinux"), ("System.map", "System.map"),
        ("Module.symvers", "Module.symvers"), (".config", "kernel.config"),
        ("modules.order", "modules.order"), ("modules.builtin", "modules.builtin"),
        ("certs/signing_key.x509", "module-signing-cert.x509")
    ]:
        shutil.copyfile(OUT / relative, ART / name)
    staged = list((VARIANT / "stage").rglob("*.ko"))
    assert len(staged) == len({p.name for p in staged}) == 17
    for path in staged:
        shutil.copyfile(path, ART / "modules" / path.name)
    for name in ("rtl8812au", "rtl8188eus", "rtl8812bu"):
        shutil.copyfile(VARIANT / "drivers" / name / "Module.symvers", ART / f"{name}.symvers")
    for name in ("stock-module-cert.pem", "stock-module-certificate.json", "stock-kernel-inspection.json",
                 "clang-source-pin.json", "build-tools-pin.json"):
        shutil.copyfile(BASE / name, ART / name)
    shutil.copyfile(HOST / "logs/realme-note60x-wifi2-full-lto-build.log", ART / "build.log")
    shutil.copyfile(HERE / "inputs.json", ART / "wifi2-inputs.json")
    shutil.copyfile(HERE / "bounds-test/results.json", ART / "monitor-bounds-validation.json")
    shutil.copyfile(HERE / "xmit-cfi-validation.json", ART / "xmit-cfi-validation.json")
    shutil.copyfile(HERE / "compiled-xmit-cfi-validation.json", ART / "compiled-xmit-cfi-validation.json")
    shutil.copyfile(HERE / "prior-artifacts-integrity.json", ART / "prior-artifacts-integrity.json")
    changes = json.loads((BASE / "source-changes.json").read_text())
    assert not {x["file"] for x in changes} & {x["file"] for x in inputs["source_changes"]}
    changes.extend(inputs["source_changes"])
    (ART / "source-changes.json").write_text(json.dumps(changes, indent=2) + "\n")
    capabilities = json.loads((BASE / "driver-capabilities.json").read_text())
    changed = {x["file"]: x for x in inputs["source_changes"]}
    for driver in capabilities["drivers"]:
        for source in driver["sources"]:
            if source["file"] in changed:
                source["sha256"] = changed[source["file"]]["after_sha256"]
            path = (VARIANT if source["file"].startswith("drivers/") else WORKSPACE) / source["file"]
            assert sha(path) == source["sha256"], source["file"]
            text = path.read_text()
            assert all(marker in text for marker in source["implementation_markers"]), source["file"]
    (ART / "driver-capabilities.json").write_text(json.dumps(capabilities, indent=2) + "\n")
    patch = (BASE / "sources/realtek-compat.patch").read_bytes() + (HERE / "monitor-tx-bounds.patch").read_bytes()
    (ART / "sources/realtek-compat.patch").write_bytes(patch)
    original_bundle = HOST / inputs["source_bundle"]
    assert sha(original_bundle) == inputs["source_bundle_sha256"]
    with tarfile.open(original_bundle) as source, tarfile.open(ART / "sources/driver-sources-and-config.tar.gz", "w:gz") as target:
        for member in source.getmembers():
            assert member.isfile(), member.name
            data = source.extractfile(member).read()
            if member.name.startswith("recipe/"):
                member.name = "baseline-" + member.name
            if member.name in changed:
                data = (VARIANT / member.name).read_bytes()
            elif member.name == "kernel.config":
                data = config
            elif member.name == "realtek-compat.patch":
                data = patch
            member.size = len(data)
            target.addfile(member, io.BytesIO(data))
        for path in sorted(HERE.iterdir()):
            if (path.is_file() and path.name not in {"STATUS.json", "SHA256SUMS.json"}
                    and path.suffix in {".py", ".sh", ".config", ".json", ".md", ".patch"}):
                target.add(path, arcname="recipe/wifi2/" + path.name)
        for path in [HOST / "build/realme-note60x/validate_artifacts.py",
                     HOST / "build/realme-note60x/verify_signatures.py",
                     HOST / "diagnostics/compare_realme_phone_modules.py",
                     HOST / "diagnostics/package_realme_wifi_magisk.py",
                     HOST / "diagnostics/package_realme_wifi2.py",
                     HOST / "diagnostics/realme_avb_integrity.py"]:
            target.add(path, arcname="recipe/shared/" + path.name)
        target.add(HOST / "tools/avb-reviewed/avbtool.py", arcname="recipe/tools/avbtool.py")
        target.add(HOST / "tools/avb-reviewed/source.json", arcname="recipe/tools/avbtool-source.json")
    manifest = json.loads((BASE / "build-manifest.json").read_text())
    manifest.update({"scope": "Host-only wifi2 Full LTO kernel and companion modules",
                     "variant": "wifi2-full-lto", "LTO": "full",
                     "compiler": subprocess.check_output([str(WORKSPACE / "clang-r450784e/bin/clang"), "--version"], text=True).strip(),
                     "kernelrelease_retained_from_stock": (OUT / "include/config/kernel.release").read_text().strip(),
                     "validation_pending": True, "saved_vendor_boot_ABI_verified": False,
                     "physical_device_accessed": False, "hardware_tested": False,
                     "build_resources_at_start": result["resources_at_start"],
                     "WSL_configuration_changed": result["WSL_configuration_changed"],
                     "TX_callback_CFI_verified": result["TX_callback_CFI_verified"],
                     "compiled_TX_callback_CFI_verified": result["compiled_TX_callback_CFI_verified"],
                     "wifi2_source_changes": inputs["source_changes"]})
    manifest.pop("boot_image", None)
    (ART / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"artifacts": str(ART), "modules": len(staged), "validation_pending": True}))


if __name__ == "__main__":
    main()
