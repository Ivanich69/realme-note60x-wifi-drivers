#!/system/bin/sh
set -o pipefail
MODDIR=$(dirname "$0")
/data/adb/magisk/busybox sh -o standalone "$MODDIR/load-wifi.sh" 2>&1 | tee -a "$MODDIR/load.log"
