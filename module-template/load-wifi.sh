#!/system/bin/sh
MODDIR=$(dirname "$0")
exec 9>"$MODDIR/load.lock"
flock -n 9 || exit 0
[ "$(getprop ro.product.model)" = RMX3938 ] || { echo "Wrong phone"; exit 1; }
[ "$(getprop ro.build.display.id)" = RMX3938export_15_C.13 ] || { echo "Wrong ROM"; exit 1; }
grep -qF 'wifi_work@host-build' /proc/version || { echo "wifi4 kernel is not running"; exit 1; }
actual_config=$(zcat /proc/config.gz | sha256sum | cut -d ' ' -f 1)
[ "$actual_config" = '513cad42f78dee45b7892917cc7c080971734d990b866243fabeece1c22bcb8b' ] || { echo "Kernel config differs"; exit 1; }
[ -d /sys/module/cfg80211 ] || { echo "Stock cfg80211 is not loaded; stopping"; exit 1; }
cd "$MODDIR" || exit 1
sha256sum -c payload.sha256 || exit 1
while IFS= read -r file; do
    [ -n "$file" ] || continue
    name=$(basename "$file" .ko | tr '-' '_')
    [ -d "/sys/module/$name" ] && continue
    echo "Loading $file"
    insmod "$MODDIR/drivers/$file" || { echo "Failed $file; remaining modules skipped"; exit 1; }
done < "$MODDIR/load-order.txt"
echo "All USB Wi-Fi drivers registered; radio operation still requires adapter testing"
