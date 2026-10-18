#!/system/bin/sh
MODDIR=$(dirname "$0")
[ -f "$MODDIR/auto-load.enabled" ] || exit 0
count=0
while [ "$(getprop sys.boot_completed)" != 1 ]; do
    count=$((count + 1))
    [ "$count" -lt 120 ] || exit 1
    sleep 1
done
/data/adb/magisk/busybox sh -o standalone "$MODDIR/load-wifi.sh" >> "$MODDIR/load.log" 2>&1
