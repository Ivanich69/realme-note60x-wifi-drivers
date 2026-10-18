"""Isolated module rebuild only. No physical device operations."""
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = Path('/home/sad1/wifi-kernel-realme-note60x')
BASE = WORK / 'wifi3-cfi-monitor'
VARIANT = WORK / 'wifi4-cfi-runtime'

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def main():
    inputs = json.loads((HERE / 'inputs.json').read_text())
    bundle = ROOT / inputs['source_bundle']
    assert sha(bundle) == inputs['source_bundle_sha256']
    assert sha(BASE / 'out/arch/arm64/boot/Image') == inputs['base_Image_sha256']
    assert sha(BASE / 'out/.config') == inputs['config_sha256']
    VARIANT.mkdir(exist_ok=True)
    with (VARIANT / 'build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker = VARIANT / 'inputs.json'
        assert not marker.exists() or json.loads(marker.read_text()) == inputs
        marker.write_text(json.dumps(inputs, indent=2) + '\n')
        if not (VARIANT / 'core-copied.json').exists():
            assert shutil.disk_usage(WORK).free > 15 * 1024**3
            shutil.copytree(BASE / 'out', VARIANT / 'out', symlinks=True, dirs_exist_ok=True)
            shutil.copytree(BASE / 'stage', VARIANT / 'stage', symlinks=True, dirs_exist_ok=True)
            (VARIANT / 'core-copied.json').write_text(json.dumps({'Image': inputs['base_Image_sha256']}))
        changes = {r['file']: r for r in inputs['source_changes']}
        with tarfile.open(bundle) as archive:
            for member in archive:
                if not member.name.startswith('drivers/'):
                    continue
                assert member.isfile() and '..' not in PurePosixPath(member.name).parts
                target = (VARIANT / member.name).resolve()
                assert target.is_relative_to(VARIANT / 'drivers')
                data = archive.extractfile(member).read()
                if member.name in changes:
                    row = changes[member.name]
                    assert hashlib.sha256(data).hexdigest() == row['before_sha256']
                    data = (HERE / 'sources' / member.name).read_bytes()
                    assert hashlib.sha256(data).hexdigest() == row['after_sha256']
                assert not target.exists() or target.read_bytes() == data
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    target.write_bytes(data)
                    target.chmod(member.mode & 0o777)
        env = os.environ.copy()
        env['REALME_WORKSPACE'] = str(WORK)
        env['PATH'] = ':'.join(str(WORK / p) for p in
            ['clang-r450784e/bin', 'build-tools/bin', 'host-tools/usr/bin']) + ':' + env['PATH']
        env['LD_LIBRARY_PATH'] = str(WORK / 'build-tools/lib64') + ':' + env.get('LD_LIBRARY_PATH', '')
        os.nice(10)
        logfile = ROOT / 'logs/realme-note60x-wifi4-module-build.log'
        with logfile.open('a', buffering=1) as log:
            def run(args):
                log.write('\nCOMMAND ' + json.dumps(list(map(str, args))) + '\n')
                log.flush()
                subprocess.run(list(map(str, args)), cwd=ROOT, env=env,
                               stdout=log, stderr=subprocess.STDOUT, check=True)
            make = ['make', '-C', WORK / 'common', f'O={VARIANT / "out"}', 'ARCH=arm64',
                    'LLVM=1', 'LLVM_IAS=1', f'LD={HERE.parent / "wifi2/ld-full.sh"}',
                    'CROSS_COMPILE=aarch64-linux-gnu-', 'KCFLAGS=-D__ANDROID_COMMON_KERNEL__',
                    'KBUILD_BUILD_USER=wifi_work', 'KBUILD_BUILD_HOST=host-build']
            for name in ['rtl8812au', 'rtl8188eus', 'rtl8812bu']:
                module = [f'M={VARIANT / "drivers" / name}', 'CONFIG_88XXAU=m',
                          'CONFIG_RTL8188EU=m', 'CONFIG_RTL8822BU=m']
                run(make + ['-j1', *module, 'modules'])
                run(make + [*module, f'INSTALL_MOD_PATH={VARIANT / "stage"}',
                            'INSTALL_MOD_STRIP=1', 'modules_install'])
        assert sha(VARIANT / 'out/arch/arm64/boot/Image') == inputs['base_Image_sha256']
        assert sha(VARIANT / 'out/.config') == inputs['config_sha256']
        assert sha(BASE / 'out/arch/arm64/boot/Image') == inputs['base_Image_sha256']
        modules = list((VARIANT / 'stage').rglob('*.ko'))
        assert len(modules) == 17
        record = {'compiled': True, 'variant': 'wifi4-cfi-runtime', 'module_count': len(modules),
                  'core_Image_unchanged': True, 'inputs': inputs, 'device_operations': []}
        (VARIANT / 'compile-result.json').write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record), flush=True)

if __name__ == '__main__':
    main()
