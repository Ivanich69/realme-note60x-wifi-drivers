"""Prepare three monitor callback type corrections from the pinned wifi2 bundle."""
import difflib
import hashlib
import json
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = ROOT / 'artifacts/realme-note60x/gki-wifi2-full-lto'

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def main():
    audit = json.loads((HERE.parent / 'wifi3-audit/callback-CFI-wifi2-full-lto.json').read_text())
    assert len(audit['mismatches']) == 3 and len(audit['emitted_mismatches']) == 2
    assert {r['function'] for r in audit['mismatches']} == {'rtw_cfg80211_monitor_if_xmit_entry'}
    archive_path = BASE / 'sources/driver-sources-and-config.tar.gz'
    manifest = json.loads((BASE / 'SHA256SUMS.json').read_text())
    pinned = {r['file']: r['sha256'] for r in manifest}
    assert sha(archive_path) == pinned['sources/driver-sources-and-config.tar.gz']
    rows, patches = [], []
    with tarfile.open(archive_path) as archive:
        for driver in ['rtl8812au', 'rtl8188eus', 'rtl8812bu']:
            name = f'drivers/{driver}/os_dep/linux/ioctl_cfg80211.c'
            original = archive.extractfile(name).read()
            old = b'static int rtw_cfg80211_monitor_if_xmit_entry('
            new = b'static netdev_tx_t rtw_cfg80211_monitor_if_xmit_entry('
            assert original.count(old) == 1
            changed = original.replace(old, new)
            path = HERE / 'sources' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(changed)
            rows.append({'file': name, 'before_sha256': hashlib.sha256(original).hexdigest(),
                         'after_sha256': hashlib.sha256(changed).hexdigest()})
            patches.extend(difflib.unified_diff(original.decode().splitlines(True),
                changed.decode().splitlines(True), fromfile='a/' + name, tofile='b/' + name))
    patch = HERE / 'monitor-callback-cfi.patch'
    patch.write_text(''.join(patches), encoding='utf-8', newline='\n')
    data = {'variant': 'wifi3-cfi-monitor', 'scope': 'Host-only module rebuild; wifi2 core retained',
            'source_bundle': archive_path.relative_to(ROOT).as_posix(), 'source_bundle_sha256': sha(archive_path),
            'base_Image_sha256': sha(BASE / 'Image'), 'config_sha256': sha(BASE / 'kernel.config'),
            'source_changes': rows, 'patch_sha256': sha(patch), 'device_operations': []}
    (HERE / 'inputs.json').write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'changed_files': len(rows), 'core_rebuild_needed': False}))

if __name__ == '__main__':
    main()
