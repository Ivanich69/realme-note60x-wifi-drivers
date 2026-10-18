#!/usr/bin/env bash
set -euo pipefail

# Host-side source preparation only. No device or deployment commands.
workspace=${REALME_WORKSPACE:-/home/sad1/wifi-kernel-realme-note60x}
kernel_commit=0c6055fd2d8b95ec88db7bfd79bfd1e471592215
kernel_tag=android13-5.15-2025-03_r2
mkdir -p "$workspace"
host_root=/mnt/f/wifi_work
python3 "$host_root/build/realme-note60x/prepare_archive.py" \
    "$host_root/.reference/realme-note60x/kernel-build-inputs/common-0c6055fd2d8b.tar.gz" \
    "$workspace/common"
printf 'Kernel source: %s\n' "$kernel_commit"

mkdir -p "$workspace/drivers"
while read -r name commit; do
    source_dir="/home/sad1/wifi-kernel-sweet/drivers/$name"
    dest_dir="$workspace/drivers/$name"
    test "$(git -C "$source_dir" rev-parse HEAD)" = "$commit"
    if [[ ! -d "$dest_dir" ]]; then
        mkdir "$dest_dir"
        git -C "$source_dir" archive "$commit" | tar -x -C "$dest_dir"
    fi
    printf 'Driver source: %s %s\n' "$name" "$commit"
done <<'PINS'
rtl8812au 734485506a30d6237c2deaad666a19f8ca5379f2
rtl8188eus af3bf004458f76b7aec33e9ba552cd382ed1f5c3
rtl8812bu d31ffa827bb95b8a436c2a469b5163b634ac4333
PINS

printf 'Source workspace: %s\n' "$workspace"
