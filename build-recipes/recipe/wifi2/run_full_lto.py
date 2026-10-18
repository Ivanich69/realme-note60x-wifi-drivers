"""Compile/stage wifi2 on the host only, in an isolated output directory.

Run inside an explicitly authorized Linux build environment. This script never
starts, stops or configures WSL. Existing common sources and wifi1 outputs are
read-only inputs; only wifi2's output/driver/staging directories are written.
Final image packaging, signatures and ABI validation follow compilation.
"""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
HOST = HERE.parents[2]
VARIANT = "wifi2-full-lto"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def config_values(text):
    return dict(line.split("=", 1) for line in text.splitlines()
                if line.startswith("CONFIG_") and "=" in line)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path("/home/sad1/wifi-kernel-realme-note60x"))
    parser.add_argument("--build", action="store_true", help="Explicitly compile; otherwise only check inputs/resources")
    parser.add_argument("--resume-bounds-profile", action="store_true",
                        help="Resume interrupted bounds-only wifi2 compilation with the four prepared CFI fixes")
    args = parser.parse_args()
    require(sys.platform == "linux", "This recipe requires a separately authorized Linux session")
    workspace = args.workspace.resolve(strict=True)
    common = workspace / "common"
    variant = (workspace / VARIANT).resolve()
    require(variant.is_relative_to(workspace) and variant != workspace, "Invalid isolated output path")
    inputs = json.loads((HERE / "inputs.json").read_text())
    bundle = HOST / inputs["source_bundle"]
    require(digest(bundle) == inputs["source_bundle_sha256"], "Source archive pin mismatch")
    require(digest(HERE / "full-lto.config") == inputs["config_seed_sha256"], "Config seed pin mismatch")
    for row in inputs["source_changes"]:
        require(digest(HERE / "sources" / row["file"]) == row["after_sha256"], "Patched source pin mismatch")
    compiler = workspace / "clang-r450784e/bin/clang"
    require(compiler.is_file() and (workspace / "build-tools/bin/pahole").is_file(), "Missing pinned toolchain")
    require(Path("/usr/bin/cc").is_file(), "Native C compiler needed for bounds regressions")
    require((common / ".scmversion").read_text().strip() == "-android13-8-00006-g0c6055fd2d8b-ab13363910",
            "Source kernel release changed")
    require("CLANG_VERSION=r450784e" in (common / "build.config.constants").read_text(), "Wrong kernel toolchain pin")
    mem = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        if value.strip().endswith("kB"):
            mem[key] = int(value.split()[0]) * 1024
    free_disk = shutil.disk_usage(workspace).free
    resource_review = HERE / "wsl-resource-change/change.json"
    resource_changes = (json.loads(resource_review.read_text()).get("applied", False)
                        if resource_review.exists() else False)
    resources = {"memory_available": mem["MemAvailable"], "swap_free": mem["SwapFree"],
                 "memory_total": mem["MemTotal"], "disk_free": free_disk,
                 "WSL_configuration_changes": resource_changes,
                 "output": str(variant), "jobs": 1, "linker_threads": 1}
    print(json.dumps(resources), flush=True)
    if not args.build:
        return
    # Capacity checks are advisory thresholds, not a promise Full LTO fits.
    require(mem["MemAvailable"] + mem["SwapFree"] >= 18 * 1024**3,
            "Less than 18 GiB available RAM+swap; stop without altering WSL")
    require(free_disk >= 15 * 1024**3, "Less than 15 GiB free for isolated compilation")
    variant.mkdir(exist_ok=True)
    with (variant / "build.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        expected = inputs["config_seed_sha256"] + ":" + inputs["patch_sha256"]
        marker = variant / "profile.txt"
        resume_transition = args.resume_bounds_profile and marker.exists() and marker.read_text().strip() != expected
        if resume_transition:
            old_patch = "ef82e92516b431c927b660d5f90963a82793b92571b5e210545c9232ce46588f"
            require(marker.read_text().strip() == inputs["config_seed_sha256"] + ":" + old_patch,
                    "Resume is restricted to the pinned bounds-only wifi2 profile")
            require(not (variant / "compile-result.json").exists(), "Completed builds require the refinement recipe")
            require(len(inputs["source_changes"]) == 6, "Resume requires all six corrected sources")
            prior_config = config_values((variant / "out/.config").read_text())
            require(prior_config.get("CONFIG_LTO_CLANG_FULL") == "y"
                    and prior_config.get("CONFIG_LTO_CLANG_THIN") != "y", "Prior output is not Full LTO")
            for row in inputs["source_changes"]:
                existing = variant / row["file"]
                require(digest(existing) in {row["before_sha256"], row["after_sha256"]},
                        f"Unexpected prior source during resume: {row['file']}")
        else:
            require(not marker.exists() or marker.read_text().strip() == expected, "Different profile already occupies output")
        marker.write_text(expected + "\n")
        env = os.environ.copy()
        env["REALME_WORKSPACE"] = str(workspace)
        env["PATH"] = ":".join(map(str, [workspace / "clang-r450784e/bin", workspace / "build-tools/bin",
                                              workspace / "host-tools/usr/bin"])) + ":" + env["PATH"]
        env["LD_LIBRARY_PATH"] = str(workspace / "build-tools/lib64") + ":" + env.get("LD_LIBRARY_PATH", "")
        out, stage = variant / "out", variant / "stage"
        out.mkdir(exist_ok=True)
        (variant / "drivers").mkdir(exist_ok=True)
        overlays = {row["file"]: row for row in inputs["source_changes"]}
        with tarfile.open(bundle) as archive:
            # Verify shared source inputs; do not regenerate or edit them.
            for name, path in [("common/.scmversion", common / ".scmversion"),
                               ("common/certs/stock_gki_modules.pem", common / "certs/stock_gki_modules.pem"),
                               ("abi_symbollist.raw", workspace / "abi_symbollist.raw")]:
                require(path.read_bytes() == archive.extractfile(name).read(), f"Shared input changed: {name}")
            for member in archive.getmembers():
                parts = PurePosixPath(member.name).parts
                if not parts or parts[0] != "drivers":
                    continue
                require(member.isfile() and len(parts) >= 3 and
                        parts[1] in {"rtl8812au", "rtl8188eus", "rtl8812bu"}, "Unexpected source archive entry")
                target = (variant / member.name).resolve()
                require(target.is_relative_to(variant / "drivers"), "Archive path escaped source directory")
                original = archive.extractfile(member).read()
                data = (HERE / "sources" / member.name).read_bytes() if member.name in overlays else original
                if member.name in overlays:
                    require(hashlib.sha256(original).hexdigest() == overlays[member.name]["before_sha256"],
                            "Overlay baseline mismatch")
                allowed_prior_overlay = (resume_transition and member.name in overlays and target.exists()
                                         and target.read_bytes() == original)
                require(not target.exists() or target.read_bytes() == data or allowed_prior_overlay,
                        f"Changed isolated source: {target}")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                target.chmod(member.mode & 0o777)
        config = out / ".config"
        if not config.exists():
            config.write_bytes((HERE / "full-lto.config").read_bytes())
        log_path = HOST / "logs/realme-note60x-wifi2-full-lto-build.log"
        log_path.parent.mkdir(exist_ok=True)
        os.nice(10)  # Lower only this process and its children.
        with log_path.open("a", buffering=1) as log:
            def run(command):
                log.write("\nCOMMAND " + json.dumps(list(map(str, command))) + "\n")
                log.flush()
                subprocess.run(list(map(str, command)), cwd=HOST, env=env,
                               stdout=log, stderr=subprocess.STDOUT, check=True)
            run([sys.executable, HERE / "test_monitor_bounds.py", "--compiler", "/usr/bin/cc"])
            if len(inputs["source_changes"]) == 6:
                run([sys.executable, HERE / "test_xmit_cfi.py", "--workspace", workspace])
            make = ["make", "-C", common, f"O={out}", "ARCH=arm64", "LLVM=1", "LLVM_IAS=1",
                    f"LD={HERE / 'ld-full.sh'}", "CROSS_COMPILE=aarch64-linux-gnu-",
                    "KCFLAGS=-D__ANDROID_COMMON_KERNEL__", "KBUILD_BUILD_USER=wifi_work",
                    "KBUILD_BUILD_HOST=host-build"]
            run(make + ["olddefconfig"])
            values = config_values(config.read_text())
            for key, value in {"CONFIG_LTO_CLANG_FULL": "y", "CONFIG_CFI_CLANG": "y",
                               "CONFIG_MODULE_SIG_PROTECT": "y", "CONFIG_MODVERSIONS": "y",
                               "CONFIG_CFG80211": "m", "CONFIG_MAC80211": "m",
                               "CONFIG_ATH9K_HTC": "m", "CONFIG_MT76x2U": "m"}.items():
                require(values.get(key) == value, f"Resolved config lost {key}")
            require(values.get("CONFIG_LTO_CLANG_THIN") != "y", "Thin LTO unexpectedly enabled")
            for _ in range(2):
                run(make + ["-j1", "Image", "Image.gz", "modules"])
                exports = {line.split()[1] for line in (out / "Module.symvers").read_text().splitlines()}
                if {"kernel_read", "kernel_write", "filp_open"} <= exports:
                    break
            require({"kernel_read", "kernel_write", "filp_open"} <= exports, "Missing required core exports")
            drivers = [variant / "drivers" / n for n in ["rtl8812au", "rtl8188eus", "rtl8812bu"]]
            flags = ["CONFIG_88XXAU=m", "CONFIG_RTL8188EU=m", "CONFIG_RTL8822BU=m"]
            for driver in drivers:
                run(make + ["-j1", f"M={driver}", *flags, "modules"])
            install = [f"INSTALL_MOD_PATH={stage}", "INSTALL_MOD_STRIP=1"]
            run(make + install + ["modules_install"])
            for driver in drivers:
                run(make + install + [f"M={driver}", *flags, "modules_install"])
            if len(inputs["source_changes"]) == 6:
                run([sys.executable, HERE / "audit_compiled_xmit_cfi.py"])
        record = {"variant": VARIANT, "compiled": True, "validation_pending": True,
                  "kernel_output": str(out), "staged_modules": str(stage),
                  "module_count": len(list(stage.rglob("*.ko"))), "build_log": str(log_path),
                  "TX_callback_CFI_verified": len(inputs["source_changes"]) == 6,
                  "compiled_TX_callback_CFI_verified": len(inputs["source_changes"]) == 6,
                  "inputs": inputs, "resources_at_start": resources,
                  "physical_device_accessed": False, "WSL_configuration_changed": resource_changes}
        (variant / "compile-result.json").write_text(json.dumps(record, indent=2) + "\n")
        print(json.dumps({k: v for k, v in record.items() if k != "inputs"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
