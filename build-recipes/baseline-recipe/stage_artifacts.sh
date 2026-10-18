#!/usr/bin/env bash
set -euo pipefail

workspace=${REALME_WORKSPACE:-/home/sad1/wifi-kernel-realme-note60x}
host_root=/mnt/f/wifi_work
out="$workspace/out-wifi1"
stage="$workspace/stage-wifi1"
artifacts="$host_root/artifacts/realme-note60x/gki-wifi1"
export PATH="$workspace/clang-r450784e/bin:$workspace/build-tools/bin:$workspace/host-tools/usr/bin:$PATH"
export LD_LIBRARY_PATH="$workspace/build-tools/lib64:${LD_LIBRARY_PATH:-}"
mkdir -p "$stage" "$artifacts/modules" "$artifacts/sources"

# modules_install below targets this explicit directory on the PC, never
# the running OS or a physical device. Strip debug, retain BTF, and sign.
make_args=(-C "$workspace/common" O="$out" ARCH=arm64 LLVM=1 LLVM_IAS=1
           LD="$host_root/build/realme-note60x/ld-limited.sh"
           CROSS_COMPILE=aarch64-linux-gnu- KCFLAGS=-D__ANDROID_COMMON_KERNEL__
           INSTALL_MOD_PATH="$stage" INSTALL_MOD_STRIP=1)
make "${make_args[@]}" modules_install
for name in rtl8812au rtl8188eus rtl8812bu; do
    make "${make_args[@]}" M="$workspace/drivers/$name" \
        CONFIG_88XXAU=m CONFIG_RTL8188EU=m CONFIG_RTL8822BU=m modules_install
done
python3 "$host_root/build/realme-note60x/export_host.py"
