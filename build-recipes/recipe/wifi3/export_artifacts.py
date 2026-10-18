"""Export the isolated monitor-CFI module refinement with unchanged wifi2 core."""
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
WORK = Path('/home/sad1/wifi-kernel-realme-note60x')
VARIANT = WORK / 'wifi3-cfi-monitor'
BASE = ROOT / 'artifacts/realme-note60x/gki-wifi2-full-lto'
ART = ROOT / 'artifacts/realme-note60x/gki-wifi3-cfi-monitor'

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
    audit = read(HERE.parent / 'wifi3-audit/callback-CFI-wifi3-cfi-monitor.json')
    assert audit['passed'] and len(audit['comparisons']) == 156 and not audit['mismatches']
    assert sum(r['table_emitted'] for r in audit['comparisons']) == 152
    assert all(r['compiled_definition_checked'] for r in audit['comparisons'] if r['table_emitted'])
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
    shutil.copyfile(ROOT / 'logs/realme-note60x-wifi3-module-build.log', ART / 'build.log')
    shutil.copyfile(BASE / 'build.log', ART / 'core-build-wifi2.log')
    shutil.copyfile(HERE / 'inputs.json', ART / 'wifi3-inputs.json')
    write(ART / 'callback-CFI-validation.json', audit)
    write(ART / 'callback-CFI-before.json', read(HERE.parent / 'wifi3-audit/callback-CFI-wifi2-full-lto.json'))
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
    patch = (BASE / 'sources/realtek-compat.patch').read_bytes() + (HERE / 'monitor-callback-cfi.patch').read_bytes()
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
                target.add(path, arcname='recipe/wifi3/' + path.name)
        target.add(HERE.parent / 'wifi3-audit/audit_callbacks.py', arcname='recipe/wifi3-audit/audit_callbacks.py')
        for name in ['callback-CFI-wifi2-full-lto.json', 'callback-CFI-wifi3-cfi-monitor.json']:
            target.add(HERE.parent / 'wifi3-audit' / name, arcname='recipe/wifi3-audit/' + name)
        for name in ['package_realme_wifi_magisk.py', 'package_realme_wifi2.py']:
            target.add(ROOT / 'diagnostics' / name, arcname='recipe/wifi3/shared/' + name)
    manifest = read(ART / 'build-manifest.json')
    manifest.update({'scope': 'Host-only monitor CFI module refinement; wifi2 core reused unchanged',
        'variant': 'wifi3-cfi-monitor', 'base_variant': 'wifi2-full-lto',
        'core_Image_sha256': inputs['base_Image_sha256'], 'core_Image_unchanged': True,
        'wifi3_source_changes': inputs['source_changes'], 'expanded_callback_CFI_verified': True,
        'module_rebuild_WSL_configuration_changed': False,
        'validation_pending': True, 'physical_device_accessed': False, 'hardware_tested': False})
    write(ART / 'build-manifest.json', manifest)
    print(json.dumps({'artifacts': str(ART), 'modules': 17, 'core_Image_unchanged': True}))

if __name__ == '__main__':
    main()
