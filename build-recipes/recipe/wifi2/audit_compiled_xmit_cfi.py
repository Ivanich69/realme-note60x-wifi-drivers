"""Check emitted CFI identities in the three actual compiled Realtek objects."""

import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent
WORKSPACE = Path('/home/sad1/wifi-kernel-realme-note60x')


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main():
    reference = json.loads((HERE / 'xmit-cfi-validation.json').read_text())
    assert reference['passed'] and reference['legacy_type_rejected']
    records = []
    for row in reference['callbacks']:
        driver = WORKSPACE / 'wifi2-full-lto/drivers' / row['driver']
        source = driver / 'os_dep/linux/xmit_linux.c'
        obj = driver / 'os_dep/linux/xmit_linux.o'
        assert sha(source) == row['source_sha256']
        with obj.open('rb') as handle:
            assert handle.read(4) == b'BC\xc0\xde', 'Expected the real pre-link LLVM object'
        result = subprocess.run([str(WORKSPACE / 'clang-r450784e/bin/llvm-dis'), str(obj), '-o', '-'],
                                capture_output=True, text=True, check=True, timeout=60)
        text = result.stdout
        declaration = next(line for line in text.splitlines() if line.startswith('define ') and '@rtw_xmit_entry(' in line)
        refs = re.findall(r'!type !(\d+)', declaration)
        strings = dict(re.findall(r'^!(\d+) = !\{i64 0, !"([^"]+)"\}', text, re.M))
        numbers = dict(re.findall(r'^!(\d+) = !\{i64 0, i64 (-?\d+)\}', text, re.M))
        actual_strings = [strings[n] for n in refs if n in strings]
        actual_numbers = [numbers[n] for n in refs if n in numbers]
        assert reference['expected_type'] in actual_strings, (row['driver'], actual_strings)
        assert reference['expected_cross_DSO_type_id'] in actual_numbers, (row['driver'], actual_numbers)
        assert reference['legacy_type'] not in actual_strings, (row['driver'], actual_strings)
        records.append({'driver': row['driver'], 'source_sha256': sha(source),
                        'compiled_object_sha256': sha(obj), 'CFI_types': actual_strings,
                        'cross_DSO_type_ids': actual_numbers})
    report = {'passed': True, 'scope': 'Actual pre-link objects for three ndo_start_xmit callbacks; no runtime test',
              'expected_type': reference['expected_type'],
              'expected_cross_DSO_type_id': reference['expected_cross_DSO_type_id'], 'objects': records}
    (HERE / 'compiled-xmit-cfi-validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': True, 'compiled_TX_callbacks': len(records)}))


if __name__ == '__main__':
    main()
