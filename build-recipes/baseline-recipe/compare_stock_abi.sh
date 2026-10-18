#!/usr/bin/env bash
set -euo pipefail
workspace=/home/sad1/wifi-kernel-realme-note60x
host=/mnt/f/wifi_work/build/realme-note60x
out="$workspace/out-stock-abi"
export PATH="$workspace/clang-r450784e/bin:$workspace/build-tools/bin:$workspace/host-tools/usr/bin:$PATH"
export LD_LIBRARY_PATH="$workspace/build-tools/lib64:${LD_LIBRARY_PATH:-}"
mkdir -p "$out"
cp "$host/stock-gki.config" "$out/.config"
"$workspace/common/scripts/config" --file "$out/.config" \
    --set-str UNUSED_KSYMS_WHITELIST "$workspace/abi_symbollist.raw"
make_args=(-C "$workspace/common" O="$out" ARCH=arm64 LLVM=1 LLVM_IAS=1
           CROSS_COMPILE=aarch64-linux-gnu- KCFLAGS=-D__ANDROID_COMMON_KERNEL__)
make "${make_args[@]}" olddefconfig
make "${make_args[@]}" -j2 drivers/android/vendor_hooks.o
cp "$out/drivers/android/.vendor_hooks.o.cmd" "$host/stock-vendor-hooks.o.cmd"
cp "$workspace/out-wifi1/drivers/android/.vendor_hooks.o.cmd" "$host/wifi-vendor-hooks.o.cmd"
