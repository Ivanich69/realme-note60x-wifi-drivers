"""Prepare isolated typed CFI wrappers from the sealed wifi3 source bundle.

No device commands. Existing sources/artifacts remain unchanged. The complete
baseline audit must be available before this recipe can be executed.
"""

import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'diagnostics'))
from analyze_realme_b_preserving_exit import verify_manifest

BASE = ROOT / 'artifacts/realme-note60x/gki-wifi3-cfi-monitor'
AUDIT = HERE.parent / 'wifi3-runtime-audit/runtime-CFI-review.json'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def replace_once(text, before, after):
    assert text.count(before) == 1, before
    return text.replace(before, after)


def main():
    assert verify_manifest(BASE) == 74
    audit = json.loads(AUDIT.read_text(encoding='utf-8'))
    assert not audit['limited_run'] and not audit['marker_only'] and not audit['device_contacted']
    known = {'rtl8812au_xmit_tasklet', 'rtl8814au_xmit_tasklet', 'rtl8188eu_xmit_tasklet',
             'rtl8822bu_xmit_tasklet', 'phy_reload_default_tx_power_ext_info',
             'phy_reload_tx_power_ext_info', 'rtw_hal_update_tx_aclt', 'usb_recv_tasklet',
             'rtw_hal_update_txpwr_level'}
    assert {row['function'] for row in audit['mismatches']} <= known, 'Additional mismatches need explicit source review'
    assert audit['mismatches'], 'Expected baseline CFI findings are absent'
    bundle = BASE / 'sources/driver-sources-and-config.tar.gz'
    rows, patches = [], []
    edits = {}
    tasklets = (
        ('rtl8812au', 'hal/rtl8812a/usb/rtl8812au_xmit.c', 'rtl8812au'),
        ('rtl8812au', 'hal/rtl8814a/usb/rtl8814au_xmit.c', 'rtl8814au'),
        ('rtl8188eus', 'hal/rtl8188e/usb/rtl8188eu_xmit.c', 'rtl8188eu'),
        ('rtl8812bu', 'hal/rtl8822b/usb/rtl8822bu_xmit.c', 'rtl8822bu'),
    )
    with tarfile.open(bundle) as archive:
        for driver, filename, stem in tasklets:
            name = f'drivers/{driver}/{filename}'
            original = archive.extractfile(name).read()
            text = original.decode('latin-1')
            wrapper = f'''#ifdef PLATFORM_LINUX
/* Match tasklet_init's actual unsigned-long callback type under Clang CFI. */
static void {stem}_xmit_tasklet_cfi(unsigned long data)
{{
\t{stem}_xmit_tasklet((void *)data);
}}
#endif

'''
            match = re.search(r'(?m)^s32\s+' + stem + r'_init_xmit_priv\(', text)
            assert match
            text = text[:match.start()] + wrapper + text[match.start():]
            text = replace_once(text, '(void(*)(unsigned long))' + stem + '_xmit_tasklet', stem + '_xmit_tasklet_cfi')
            if driver == 'rtl8812bu':
                # The version branches both still call tasklet_init with the
                # same unsigned-long callback contract in this kernel profile.
                text = replace_once(text, '(void *)rtl8822bu_xmit_tasklet,', 'rtl8822bu_xmit_tasklet_cfi,')
            edits[name] = (original, text.encode('latin-1'))
        name = 'drivers/rtl8812bu/os_dep/linux/ioctl_cfg80211.c'
        original = archive.extractfile(name).read()
        text = original.decode('latin-1')
        marker = 'static int cfg80211_rtw_set_txpower('
        wrapper = '''static void rtw_hal_update_txpwr_level_cfi(void *context)
{
\trtw_hal_update_txpwr_level((_adapter *)context);
}

'''
        text = replace_once(text, marker, wrapper + marker)
        text = replace_once(text, '((void *)(rtw_hal_update_txpwr_level))', 'rtw_hal_update_txpwr_level_cfi')
        edits[name] = (original, text.encode('latin-1'))
        for driver in ('rtl8188eus', 'rtl8812bu'):
            name = f'drivers/{driver}/hal/hal_hci/hal_usb.c'
            original = archive.extractfile(name).read()
            text = original.decode('latin-1')
            wrapper = '''#ifdef PLATFORM_LINUX
static void usb_recv_tasklet_cfi(unsigned long data)
{
\tusb_recv_tasklet((void *)data);
}
#endif

'''
            match = re.search(r'(?m)^int\s+usb_init_recv_priv\(', text)
            assert match
            text = text[:match.start()] + wrapper + text[match.start():]
            text = replace_once(text, '(void(*)(unsigned long))usb_recv_tasklet', 'usb_recv_tasklet_cfi')
            if driver == 'rtl8812bu':
                text = replace_once(text, '(void *)usb_recv_tasklet,', 'usb_recv_tasklet_cfi,')
            edits[name] = (original, text.encode('latin-1'))
        for driver in ('rtl8812au', 'rtl8188eus', 'rtl8812bu'):
            name = f'drivers/{driver}/os_dep/linux/rtw_proc.c'
            original = archive.extractfile(name).read()
            text = original.decode('latin-1')
            wrappers = '''/* Queue callbacks take void *, while PHY helpers take _adapter *. */
static void phy_reload_default_tx_power_ext_info_cfi(void *context)
{
\tphy_reload_default_tx_power_ext_info((_adapter *)context);
}

static void phy_reload_tx_power_ext_info_cfi(void *context)
{
\tphy_reload_tx_power_ext_info((_adapter *)context);
}

'''
            marker = 'static ssize_t proc_set_tx_power_ext_info('
            text = replace_once(text, marker, wrappers + marker)
            for function in ('phy_reload_default_tx_power_ext_info', 'phy_reload_tx_power_ext_info'):
                text = replace_once(text, '((void *)(' + function + '))', function + '_cfi')
            # More callbacks are changed only if found in the active baseline.
            if driver == 'rtl8812bu' and any(row['driver'] == driver and row['function'] == 'rtw_hal_update_tx_aclt' for row in audit['mismatches']):
                # Keep the wrapper inside the same existing build guard as
                # all three proc consumers of this optional helper.
                marker = '#if CONFIG_TX_AC_LIFETIME\nstatic int proc_get_tx_aclt_force_val('
                wrapper = '''#if CONFIG_TX_AC_LIFETIME
static void rtw_hal_update_tx_aclt_cfi(void *context)
{
\trtw_hal_update_tx_aclt((_adapter *)context);
}

static int proc_get_tx_aclt_force_val('''
                text = replace_once(text, marker, wrapper)
                original_callback = '((void *)(rtw_hal_update_tx_aclt))'
                assert text.count(original_callback) == 3
                text = text.replace(original_callback, 'rtw_hal_update_tx_aclt_cfi')
            edits[name] = (original, text.encode('latin-1'))
    for name, (original, changed) in edits.items():
        path = HERE / 'sources' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        assert not path.exists(), 'Do not overwrite a prepared source'
        path.write_bytes(changed)
        rows.append({'file': name, 'before_sha256': hashlib.sha256(original).hexdigest(),
                     'after_sha256': hashlib.sha256(changed).hexdigest()})
        patches.extend(difflib.unified_diff(original.decode('latin-1').splitlines(True), changed.decode('latin-1').splitlines(True),
                                           fromfile='a/' + name, tofile='b/' + name))
    patch = HERE / 'runtime-callback-cfi.patch'
    patch.write_text(''.join(patches), encoding='utf-8', newline='\n')
    inputs = {'variant': 'wifi4-cfi-runtime', 'scope': 'Host-only typed callback wrappers; wifi3 core retained',
              'source_bundle': bundle.relative_to(ROOT).as_posix(), 'source_bundle_sha256': sha(bundle),
              'base_Image_sha256': sha(BASE / 'Image'), 'config_sha256': sha(BASE / 'kernel.config'),
              'source_changes': rows, 'patch_sha256': sha(patch), 'baseline_runtime_audit_sha256': sha(AUDIT),
              'device_operations': []}
    (HERE / 'inputs.json').write_text(json.dumps(inputs, indent=2) + '\n', encoding='utf-8')
    build_script = (HERE.parent / 'wifi3/build_modules.py').read_text(encoding='utf-8')
    build_script = build_script.replace("BASE = WORK / 'wifi2-full-lto'", "BASE = WORK / 'wifi3-cfi-monitor'")
    build_script = build_script.replace('wifi3-cfi-monitor', 'wifi4-cfi-runtime')
    build_script = build_script.replace("BASE = WORK / 'wifi4-cfi-runtime'", "BASE = WORK / 'wifi3-cfi-monitor'")
    build_script = build_script.replace('realme-note60x-wifi3-module-build.log', 'realme-note60x-wifi4-module-build.log')
    (HERE / 'build_modules.py').write_text(build_script, encoding='utf-8', newline='\n')
    print(json.dumps({'host_only': True, 'changed_files': len(rows), 'core_rebuild_needed': False,
                      'device_operations': []}))


if __name__ == '__main__':
    main()
