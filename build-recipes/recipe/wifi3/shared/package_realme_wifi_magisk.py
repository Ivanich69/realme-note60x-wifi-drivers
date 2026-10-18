"""Build a separate, reviewable Magisk companion package; never deploy it."""

import hashlib
import argparse
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / 'artifacts/realme-note60x/gki-wifi1'
OUT = ROOT / 'artifacts/realme-note60x/wifi1-install'


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8', newline='\n')


def main(variant='wifi1', version_code=1, compatibility_path=None):
    latest = Path((ROOT / 'diagnostics/realme-wifi-install-latest.txt').read_text().strip())
    compatibility_path = compatibility_path or latest / 'full-module-compatibility.json'
    compatibility = json.loads(compatibility_path.read_text())
    assert not compatibility['core_incompatible_modules']
    assert not compatibility['stock_vs_new_cfg80211_differences']
    assert not compatibility['stock_drivers_with_new_cfg80211_errors']
    assert not any(row['cfg80211_errors'] for row in compatibility['new_drivers_with_stock_cfg80211'])
    module = OUT / 'module'
    module.mkdir(parents=True, exist_ok=True)
    config_hash = hashlib.sha256((ART / 'kernel.config').read_bytes()).hexdigest()
    # Keep one companion identity across variants; config guards distinguish builds.
    put(module / 'module.prop', f'id=realme_wifi_gki1\nname=Realme Note 60x USB Wi-Fi {variant}\n'
        f'version={variant}\nversionCode={version_code}\nauthor=wifi_work\n'
        f'description=USB Wi-Fi drivers and firmware for RMX3938 C.13 {variant}; hardware untested\n')
    put(module / 'customize.sh', '''[ "$BOOTMODE" = true ] || abort "Install from the running Magisk app/CLI only"
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
''')
    put(module / 'service.sh', '''#!/system/bin/sh
MODDIR=$(dirname "$0")
[ -f "$MODDIR/auto-load.enabled" ] || exit 0
count=0
while [ "$(getprop sys.boot_completed)" != 1 ]; do
    count=$((count + 1))
    [ "$count" -lt 120 ] || exit 1
    sleep 1
done
/data/adb/magisk/busybox sh -o standalone "$MODDIR/load-wifi.sh" >> "$MODDIR/load.log" 2>&1
''')
    put(module / 'action.sh', '''#!/system/bin/sh
set -o pipefail
MODDIR=$(dirname "$0")
/data/adb/magisk/busybox sh -o standalone "$MODDIR/load-wifi.sh" 2>&1 | tee -a "$MODDIR/load.log"
''')
    loader = '''#!/system/bin/sh
MODDIR=$(dirname "$0")
exec 9>"$MODDIR/load.lock"
flock -n 9 || exit 0
[ "$(getprop ro.product.model)" = RMX3938 ] || { echo "Wrong phone"; exit 1; }
[ "$(getprop ro.build.display.id)" = RMX3938export_15_C.13 ] || { echo "Wrong ROM"; exit 1; }
grep -qF 'wifi_work@host-build' /proc/version || { echo "@VARIANT@ kernel is not running"; exit 1; }
actual_config=$(zcat /proc/config.gz | sha256sum | cut -d ' ' -f 1)
[ "$actual_config" = '@CONFIG_HASH@' ] || { echo "Kernel config differs"; exit 1; }
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
'''.replace('@CONFIG_HASH@', config_hash).replace('@VARIANT@', variant)
    put(module / 'load-wifi.sh', loader)
    order = [name for name in (ART / 'wifi-module-load-order.txt').read_text().splitlines()
             if name != 'cfg80211.ko']
    put(module / 'load-order.txt', '\n'.join(order) + '\n')
    drivers = module / 'drivers'
    drivers.mkdir(exist_ok=True)
    for name in order:
        shutil.copyfile(ART / 'modules' / name, drivers / name)
    # Keep the existing ODM regulatory database; add only adapter firmware.
    for name in ('mediatek/mt7662u.bin', 'mediatek/mt7662u_rom_patch.bin',
                 'ath9k_htc/htc_9271-1.4.0.fw'):
        target = module / 'system/vendor/firmware' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ART / 'firmware' / name, target)
    shutil.copytree(ART / 'firmware/LICENSES', module / 'licenses', dirs_exist_ok=True)
    shutil.copyfile(ART / 'firmware/WHENCE', module / 'licenses/WHENCE')
    for name in ('ar9271-firmware-manifest.json', 'mt76-firmware-manifest.json'):
        shutil.copyfile(ART / name, module / name)
    sums = []
    for path in sorted(module.rglob('*')):
        if path.is_file() and (path.suffix == '.ko' or 'firmware' in path.parts):
            sums.append(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(module).as_posix())
    put(module / 'payload.sha256', '\n'.join(sums) + '\n')
    archive_path = OUT / f'realme-note60x-{variant}-magisk.zip'
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(module.rglob('*')):
            if path.is_file():
                archive.write(path, path.relative_to(module).as_posix())
    shutil.copyfile(compatibility_path, OUT / 'full-module-compatibility.json')
    put(OUT / 'README.md', f'''# Realme Note 60x {variant} companion preparation

This companion ZIP adds 14 USB Wi-Fi modules and three firmware binaries via
Magisk. The existing stock cfg80211 remains loaded and is not replaced.
Its exported CRCs match the compiled drivers. Kernel config and build marker
are checked before loading. Driver loading is manual until runtime validation.
The module contains no kernel flashing, partition writes, reboot commands,
SELinux disabling or stock module unloading.

The matching kernel build is ../{ART.name}/. This companion ZIP contains no
kernel image. Host checks do not establish bootability or radio behavior.
Backups are in the diagnostic directory recorded by
diagnostics/realme-wifi-install-latest.txt.
''')
    record = {'zip': archive_path.name, 'sha256': hashlib.sha256(archive_path.read_bytes()).hexdigest(),
              'bytes': archive_path.stat().st_size, 'driver_modules': len(order),
              'uses_stock_cfg80211': True, 'kernel_config_sha256': config_hash,
              'auto_load_initially_enabled': False, 'contains_partition_writes': False,
              'preflight_dir': str(latest), 'device_install_performed': False}
    put(OUT / 'package-validation.json', json.dumps(record, indent=2) + '\n')
    with zipfile.ZipFile(archive_path) as archive:
        assert archive.testzip() is None
        assert 'module.prop' in archive.namelist()
        assert not any(name.endswith('.img') for name in archive.namelist())
    print(json.dumps(record))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts', type=Path, default=ART)
    parser.add_argument('--output', type=Path, default=OUT)
    parser.add_argument('--variant', choices=('wifi1', 'wifi2', 'wifi3'), default='wifi1')
    parser.add_argument('--version-code', type=int, default=1)
    parser.add_argument('--compatibility', type=Path)
    args = parser.parse_args()
    ART, OUT = args.artifacts.resolve(), args.output.resolve()
    assert ART.is_relative_to((ROOT / 'artifacts/realme-note60x').resolve())
    assert OUT.is_relative_to((ROOT / 'artifacts/realme-note60x').resolve())
    main(args.variant, args.version_code, args.compatibility)
