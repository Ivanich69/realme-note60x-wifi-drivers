"""Export typed runtime callback wrappers with the unchanged wifi3 core."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = Path('/home/sad1/wifi-kernel-realme-note60x')
VARIANT = WORK / 'wifi4-cfi-runtime'
BASE = ROOT / 'artifacts/realme-note60x/gki-wifi3-cfi-monitor'
ART = ROOT / 'artifacts/realme-note60x/gki-wifi4-cfi-runtime'

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def read(path):
    return json.loads(path.read_text())

def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')

def main():
    result = read(VARIANT / 'compile-result.json')
    inputs = read(HERE / 'inputs.json')
    assert result['compiled'] and result['inputs'] == inputs and result['core_Image_unchanged']
    audit = read(HERE.parent / 'wifi4-audit/callback-CFI-wifi4-cfi-runtime.json')
    assert audit['passed'] and len(audit['comparisons']) == 156 and not audit['mismatches']
    assert sum(r['table_emitted'] for r in audit['comparisons']) == 152
    assert all(r['compiled_definition_checked'] for r in audit['comparisons'] if r['table_emitted'])
    runtime = read(HERE.parent / 'wifi4-runtime-audit/runtime-CFI-review.json')
    assert runtime['passed'] and not runtime['mismatches'] and not runtime['limited_run'] and not runtime['marker_only']
    assert not runtime['device_contacted'] and runtime['source_count'] >= 400
    shutil.copytree(BASE, ART, dirs_exist_ok=True)
    # Changed module bytes require fresh proofs; never inherit a successful
    # signature/ABI status for the old modules merely by copying the directory.
    for name in ['signature-validation.json', 'validation-summary.json', 'module-validation.json',
                 'vendor-abi-validation.json', 'full-module-compatibility.json',
                 'boot-image-validation.json', 'SHA256SUMS.json', 'BUILD_REPORT.md']:
        path = ART / name
        if path.exists():
            path.unlink()
    assert sha(ART / 'Image') == inputs['base_Image_sha256']
    assert sha(VARIANT / 'out/arch/arm64/boot/Image') == inputs['base_Image_sha256']
    modules = list((VARIANT / 'stage').rglob('*.ko'))
    assert len(modules) == 17
    for p in modules:
        shutil.copyfile(p, ART / 'modules' / p.name)
    for driver in ['rtl8812au', 'rtl8188eus', 'rtl8812bu']:
        shutil.copyfile(VARIANT / 'drivers' / driver / 'Module.symvers', ART / f'{driver}.symvers')
    shutil.copyfile(ROOT / 'logs/realme-note60x-wifi4-module-build.log', ART / 'build.log')
    shutil.copyfile(BASE / 'core-build-wifi2.log', ART / 'core-build-wifi2.log')
    shutil.copyfile(HERE / 'inputs.json', ART / 'wifi4-inputs.json')
    write(ART / 'callback-CFI-validation.json', audit)
    write(ART / 'runtime-CFI-validation.json', runtime)
    write(ART / 'runtime-CFI-before.json', read(HERE.parent / 'wifi3-runtime-audit/runtime-CFI-review.json'))
    write(ART / 'callback-CFI-before.json', read(BASE / 'callback-CFI-validation.json'))
    main_tx = [r for r in audit['comparisons'] if r['table'] == 'rtw_netdev_ops' and r['field'] == 'ndo_start_xmit']
    assert len(main_tx) == 3
    old_proof = read(BASE / 'compiled-xmit-cfi-validation.json')
    proof = {k: v for k, v in old_proof.items() if k != 'objects'}
    proof['objects'] = []
    for row in main_tx:
        assert len(row['compiled_definitions']) == 1
        obj = row['compiled_definitions'][0]
        assert old_proof['expected_cross_DSO_type_id'] in obj['ids']
        source = VARIANT / 'drivers' / row['driver'] / 'os_dep/linux/xmit_linux.c'
        proof['objects'].append({'driver': row['driver'], 'source_sha256': sha(source),
            'compiled_object_sha256': obj['object_sha256'], 'CFI_types': obj['strings'],
            'cross_DSO_type_ids': obj['ids']})
    write(ART / 'compiled-xmit-cfi-validation.json', proof)
    changed = {r['file']: r for r in inputs['source_changes']}
    changes = read(BASE / 'source-changes.json')
    known = {r['file']: r for r in changes}
    for name, row in changed.items():
        if name in known:
            assert known[name]['after_sha256'] == row['before_sha256']
            known[name]['after_sha256'] = row['after_sha256']
        else:
            changes.append(row)
    write(ART / 'source-changes.json', changes)
    capabilities = read(BASE / 'driver-capabilities.json')
    for driver in capabilities['drivers']:
        for row in driver['sources']:
            if row['file'] in changed:
                row['sha256'] = changed[row['file']]['after_sha256']
            path = (VARIANT if row['file'].startswith('drivers/') else WORK) / row['file']
            assert sha(path) == row['sha256']
            assert all(marker in path.read_text() for marker in row['implementation_markers'])
    write(ART / 'driver-capabilities.json', capabilities)
    patch = (BASE / 'sources/realtek-compat.patch').read_bytes() + (HERE / 'runtime-callback-cfi.patch').read_bytes()
    (ART / 'sources/realtek-compat.patch').write_bytes(patch)
    with tarfile.open(BASE / 'sources/driver-sources-and-config.tar.gz') as source, \
            tarfile.open(ART / 'sources/driver-sources-and-config.tar.gz', 'w:gz') as target:
        for member in source:
            assert member.isfile()
            data = source.extractfile(member).read()
            if member.name in changed:
                data = (VARIANT / member.name).read_bytes()
            elif member.name == 'realtek-compat.patch':
                data = patch
            member.size = len(data)
            target.addfile(member, io.BytesIO(data))
        for path in sorted(HERE.iterdir()):
            if (path.is_file() and path.suffix in {'.py', '.json', '.md', '.patch'}
                    and path.name not in {'SHA256SUMS.json', 'STATUS.json'}):
                target.add(path, arcname='recipe/wifi4/' + path.name)
        target.add(HERE.parent / 'wifi4-audit/audit_callbacks.py', arcname='recipe/wifi4-audit/audit_callbacks.py')
        for name in ['callback-CFI-wifi4-cfi-runtime.json']:
            target.add(HERE.parent / 'wifi4-audit' / name, arcname='recipe/wifi4-audit/' + name)
        for name in ['audit_runtime.py', 'clang_roots.py', 'runtime-CFI-review.json']:
            target.add(HERE.parent / 'wifi4-runtime-audit' / name, arcname='recipe/wifi4-runtime-audit/' + name)
        for name in ['audit_runtime.py', 'clang_roots.py', 'runtime-CFI-review.json']:
            target.add(HERE.parent / 'wifi3-runtime-audit' / name, arcname='recipe/wifi3-runtime-audit/' + name)
        for name in ['package_realme_wifi_magisk.py', 'package_realme_wifi2.py']:
            target.add(ROOT / 'diagnostics' / name, arcname='recipe/wifi4/shared/' + name)
        target.add(HERE.parent / 'verify_signatures.py', arcname='recipe/wifi4/shared/verify_signatures.py')
    manifest = read(ART / 'build-manifest.json')
    manifest.update({'scope': 'Host-only typed runtime callback wrappers; wifi3 core reused unchanged',
        'variant': 'wifi4-cfi-runtime', 'base_variant': 'wifi3-cfi-monitor',
        'core_Image_sha256': inputs['base_Image_sha256'], 'core_Image_unchanged': True,
        'wifi4_source_changes': inputs['source_changes'], 'expanded_callback_CFI_verified': True,
        'module_rebuild_WSL_configuration_changed': False,
        'validation_pending': True, 'physical_device_accessed': False, 'hardware_tested': False})
    write(ART / 'build-manifest.json', manifest)
    print(json.dumps({'artifacts': str(ART), 'modules': 17, 'core_Image_unchanged': True}))

if __name__ == '__main__':
    main()
