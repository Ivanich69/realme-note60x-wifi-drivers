#!/usr/bin/env bash
set -euo pipefail

# Compile and stage files on the PC only. This recipe never deploys them.
workspace=${REALME_WORKSPACE:-/home/sad1/wifi-kernel-realme-note60x}
host_root=/mnt/f/wifi_work
jobs=${JOBS:-2}
export PATH="$workspace/clang-r450784e/bin:$workspace/build-tools/bin:$workspace/host-tools/usr/bin:$PATH"
export LD_LIBRARY_PATH="$workspace/build-tools/lib64:${LD_LIBRARY_PATH:-}"
out="$workspace/out-wifi1"
log="$host_root/logs/realme-note60x-wifi1-build.log"
mkdir -p "$host_root/logs"
python3 "$host_root/build/realme-note60x/apply_compat_fixes.py"
make_args=(-C "$workspace/common" O="$out" ARCH=arm64 LLVM=1 LLVM_IAS=1
           LD="$host_root/build/realme-note60x/ld-limited.sh"
           CROSS_COMPILE=aarch64-linux-gnu- KCFLAGS=-D__ANDROID_COMMON_KERNEL__
           KBUILD_BUILD_USER=wifi_work KBUILD_BUILD_HOST=host-build)
for pass in 1 2; do
    if [[ "$pass" == 1 ]]; then
        make "${make_args[@]}" -j"$jobs" Image Image.gz modules 2>&1 | tee "$log"
    else
        # TRIM_UNUSED_KSYMS can recompile providers late in the first pass.
        # Resolve the resulting link dependencies before external MODPOST.
        make "${make_args[@]}" -j"$jobs" Image Image.gz modules 2>&1 | tee -a "$log"
    fi
    core_exports_ready=true
    for symbol in kernel_read kernel_write filp_open; do
        if ! grep -qw "$symbol" "$out/Module.symvers"; then
            core_exports_ready=false
        fi
    done
    if [[ "$core_exports_ready" == true ]]; then
        break
    fi
done
test "$core_exports_ready" == true
for name in rtl8812au rtl8188eus rtl8812bu; do
    make "${make_args[@]}" -j"$jobs" M="$workspace/drivers/$name" \
        CONFIG_88XXAU=m CONFIG_RTL8188EU=m CONFIG_RTL8822BU=m modules \
        2>&1 | tee -a "$log"
    test -n "$(find "$workspace/drivers/$name" -maxdepth 1 -name '*.ko' -print -quit)"
done
printf 'Compilation completed in %s\n' "$out" | tee -a "$log"
