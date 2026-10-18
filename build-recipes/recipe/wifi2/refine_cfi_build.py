"""Rebuild only the two isolated external drivers after TX callback type fixes.

The compiled core, shared common sources, wifi1 and WSL settings stay unchanged.
"""

import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
HOST = HERE.parents[2]
WORKSPACE = Path('/home/sad1/wifi-kernel-realme-note60x')
VARIANT = WORKSPACE / 'wifi2-full-lto'


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main():
    with (VARIANT / 'build.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result_path = VARIANT / 'compile-result.json'
        previous = json.loads(result_path.read_text())
        current = json.loads((HERE / 'inputs.json').read_text())
        if previous.get('TX_callback_CFI_verified') and previous['inputs'] == current:
            print('Current source revision already compiled with verified TX callback CFI')
            return
        assert previous['compiled'] and previous['inputs']['config_seed_sha256'] == current['config_seed_sha256']
        old = {r['file']: r for r in previous['inputs']['source_changes']}
        new = {r['file']: r for r in current['source_changes']}
        assert len(new) == 6 and all(new[name] == row for name, row in old.items())
        expected_new = {f'drivers/{driver}/{suffix}' for driver in ['rtl8188eus', 'rtl8812bu']
                        for suffix in ['os_dep/linux/xmit_linux.c', 'include/xmit_osdep.h']}
        assert set(new) - set(old) <= expected_new
        out = VARIANT / 'out'
        image_hash = sha(out / 'arch/arm64/boot/Image')
        for name in expected_new:
            target = (VARIANT / name).resolve()
            assert target.is_relative_to(VARIANT / 'drivers')
            assert sha(target) in {new[name]['before_sha256'], new[name]['after_sha256']}
            source = HERE / 'sources' / name
            assert sha(source) == new[name]['after_sha256']
            target.write_bytes(source.read_bytes())
        env = os.environ.copy()
        env['REALME_WORKSPACE'] = str(WORKSPACE)
        env['PATH'] = ':'.join(str(WORKSPACE / p) for p in
            ['clang-r450784e/bin', 'build-tools/bin', 'host-tools/usr/bin']) + ':' + env['PATH']
        env['LD_LIBRARY_PATH'] = str(WORKSPACE / 'build-tools/lib64') + ':' + env.get('LD_LIBRARY_PATH', '')
        os.nice(10)
        log_path = HOST / 'logs/realme-note60x-wifi2-full-lto-build.log'
        with log_path.open('a', buffering=1) as log:
            def run(command):
                log.write('\nCOMMAND ' + json.dumps(list(map(str, command))) + '\n')
                log.flush()
                subprocess.run(list(map(str, command)), cwd=HOST, env=env,
                               stdout=log, stderr=subprocess.STDOUT, check=True)
            run([sys.executable, HERE / 'test_xmit_cfi.py'])
            make = ['make', '-C', WORKSPACE / 'common', f'O={out}', 'ARCH=arm64', 'LLVM=1', 'LLVM_IAS=1',
                    f'LD={HERE / "ld-full.sh"}', 'CROSS_COMPILE=aarch64-linux-gnu-',
                    'KCFLAGS=-D__ANDROID_COMMON_KERNEL__', 'KBUILD_BUILD_USER=wifi_work',
                    'KBUILD_BUILD_HOST=host-build']
            for driver in ['rtl8188eus', 'rtl8812bu']:
                module = [f'M={VARIANT / "drivers" / driver}', 'CONFIG_88XXAU=m',
                          'CONFIG_RTL8188EU=m', 'CONFIG_RTL8822BU=m']
                run(make + ['-j1', *module, 'modules'])
                run(make + [*module, f'INSTALL_MOD_PATH={VARIANT / "stage"}',
                            'INSTALL_MOD_STRIP=1', 'modules_install'])
            run([sys.executable, HERE / 'audit_compiled_xmit_cfi.py'])
        assert sha(out / 'arch/arm64/boot/Image') == image_hash, 'External rebuild changed the core Image'
        cfi = json.loads((HERE / 'xmit-cfi-validation.json').read_text())
        assert cfi['passed'] and len(cfi['callbacks']) == 3
        for row in cfi['callbacks']:
            assert sha(VARIANT / 'drivers' / row['driver'] / 'os_dep/linux/xmit_linux.c') == row['source_sha256']
        previous.update({'inputs': current, 'TX_callback_CFI_verified': True,
                         'compiled_TX_callback_CFI_verified': True,
                         'core_Image_unchanged_during_external_rebuild': True,
                         'module_count': len(list((VARIANT / 'stage').rglob('*.ko')))})
        result_path.write_text(json.dumps(previous, indent=2) + '\n')
        (VARIANT / 'profile.txt').write_text(current['config_seed_sha256'] + ':' + current['patch_sha256'] + '\n')
        print(json.dumps({'CFI_verified': True, 'external_drivers_rebuilt': ['rtl8188eus', 'rtl8812bu'],
                          'core_Image_unchanged': True, 'modules': previous['module_count']}))


if __name__ == '__main__':
    main()
