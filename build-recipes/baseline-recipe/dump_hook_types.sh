#!/usr/bin/env bash
set -euo pipefail
workspace=/home/sad1/wifi-kernel-realme-note60x
export PATH="$workspace/clang-r450784e/bin:$workspace/build-tools/bin:$workspace/host-tools/usr/bin:$PATH"
export LD_LIBRARY_PATH="$workspace/build-tools/lib64:${LD_LIBRARY_PATH:-}"
for out in out-stock-abi out-wifi1; do
    python3 - "$workspace/$out" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
assert root.parent == Path('/home/sad1/wifi-kernel-realme-note60x')
object_path = root / 'drivers/android/vendor_hooks.o'
if object_path.exists():
    object_path.unlink()
PY
    make -C "$workspace/common" O="$workspace/$out" ARCH=arm64 LLVM=1 LLVM_IAS=1 \
        CROSS_COMPILE=aarch64-linux-gnu- KCFLAGS=-D__ANDROID_COMMON_KERNEL__ \
        KBUILD_SYMTYPES=1 -j2 drivers/android/vendor_hooks.o
    cp "$workspace/$out/drivers/android/vendor_hooks.symtypes" \
        "/mnt/f/wifi_work/build/realme-note60x/$out-vendor-hooks.symtypes"
done
