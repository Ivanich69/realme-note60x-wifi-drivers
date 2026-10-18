[ "$BOOTMODE" = true ] || abort "Install from the running Magisk app/CLI only"
[ "$ARCH" = arm64 ] || abort "ARM64 required"
[ "$(getprop ro.product.model)" = RMX3938 ] || abort "RMX3938 required"
[ "$(getprop ro.build.display.id)" = RMX3938export_15_C.13 ] || abort "C.13 required"
ui_print "Firmware and drivers only; this package does not flash a kernel"
ui_print "Automatic driver loading stays disabled until runtime checks pass"
set_perm_recursive "$MODPATH" 0 0 0755 0644
set_perm_recursive "$MODPATH/system/vendor/firmware" 0 0 0755 0644 u:object_r:vendor_file:s0
set_perm "$MODPATH/service.sh" 0 0 0755
set_perm "$MODPATH/action.sh" 0 0 0755
set_perm "$MODPATH/load-wifi.sh" 0 0 0755
