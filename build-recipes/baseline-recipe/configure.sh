#!/usr/bin/env bash
set -euo pipefail
workspace=${REALME_WORKSPACE:-/home/sad1/wifi-kernel-realme-note60x}
host_root=/mnt/f/wifi_work
clang="$workspace/clang-r450784e/bin"
export PATH="$clang:$workspace/build-tools/bin:$workspace/host-tools/usr/bin:$PATH"
export LD_LIBRARY_PATH="$workspace/build-tools/lib64:${LD_LIBRARY_PATH:-}"
python3 "$host_root/build/realme-note60x/prepare_build.py"
out="$workspace/out-wifi1"
config="$workspace/common/scripts/config"
"$config" --file "$out/.config" --keep-case \
    --module CFG80211 --disable CFG80211_WEXT \
    --module MAC80211 --enable WLAN --enable WLAN_VENDOR_ATH \
    --module ATH9K_HTC --enable WLAN_VENDOR_MEDIATEK --module MT76x2U \
    --enable WIRELESS_EXT --enable WEXT_CORE --enable WEXT_PROC --enable WEXT_PRIV \
    --set-str SYSTEM_TRUSTED_KEYS certs/stock_gki_modules.pem \
    --disable LTO_CLANG_FULL --enable LTO_CLANG_THIN \
    --set-str UNUSED_KSYMS_WHITELIST "$workspace/abi_symbollist.raw"
make -C "$workspace/common" O="$out" ARCH=arm64 LLVM=1 LLVM_IAS=1 \
    CROSS_COMPILE=aarch64-linux-gnu- LD="$host_root/build/realme-note60x/ld-limited.sh" \
    KCFLAGS=-D__ANDROID_COMMON_KERNEL__ olddefconfig
cp "$out/.config" "$host_root/build/realme-note60x/resolved.config"
"$clang/clang" --version
make -s -C "$workspace/common" O="$out" ARCH=arm64 LLVM=1 LLVM_IAS=1 kernelrelease
