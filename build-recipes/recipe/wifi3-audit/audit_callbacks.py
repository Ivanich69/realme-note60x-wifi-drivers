"""Read-only audit of callback tables in the compiled wifi2 Realtek drivers.

Compiler probes and reports are written only under this audit directory. The
kernel, driver sources, existing objects and finished packages are not changed.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

HERE = Path(__file__).resolve().parent
WORKSPACE = Path('/home/sad1/wifi-kernel-realme-note60x')
VARIANT = WORKSPACE / 'wifi2-full-lto'
DRIVERS = ('rtl8812au', 'rtl8188eus', 'rtl8812bu')
TABLE_TYPES = ('net_device_ops', 'cfg80211_ops', 'ethtool_ops')
CLANG = WORKSPACE / 'clang-r450784e/bin/clang'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def compiler_flags(source):
    cmdfile = source.with_name('.' + source.stem + '.o.cmd')
    line = cmdfile.read_text().splitlines()[0]
    args = shlex.split(line.split(' := ', 1)[1])
    assert args[0] == 'clang'
    flags = []
    i = 1
    while i < len(args):
        value = args[i]
        if value == '-o':
            i += 2
            continue
        if value == '-c' or value == str(source) or value.startswith('-Wp,-MMD,'):
            i += 1
            continue
        flags.append(value)
        i += 1
    assert '-fsanitize=cfi' in flags and '-fsanitize-cfi-cross-dso' in flags
    return flags


def run(args, **kwargs):
    result = subprocess.run(list(map(str, args)), cwd=VARIANT / 'out',
                            capture_output=True, text=True, timeout=120, **kwargs)
    if result.returncode:
        raise RuntimeError(result.stderr[-10000:])
    return result


def ast_nodes(source, name):
    result = run([CLANG, *compiler_flags(source), '-fsyntax-only', '-Xclang', '-ast-dump=json',
                  '-Xclang', '-ast-dump-filter', '-Xclang', name, source])
    decoder = json.JSONDecoder()
    remaining = result.stdout.lstrip()
    nodes = []
    while remaining:
        node, end = decoder.raw_decode(remaining)
        nodes.append(node)
        remaining = remaining[end:].lstrip()
    return nodes


def walk(node):
    yield node
    for child in node.get('inner', []):
        yield from walk(child)


def cfi_metadata(text):
    strings = dict(re.findall(r'^!(\d+) = !\{i64 0, !"([^"]+)"\}', text, re.M))
    numbers = dict(re.findall(r'^!(\d+) = !\{i64 0, i64 (-?\d+)\}', text, re.M))
    functions = {}
    for line in text.splitlines():
        if not line.startswith('define '):
            continue
        name = re.search(r'@(?:"([^"]+)"|([^\s(]+))\(', line)
        if not name:
            continue
        refs = re.findall(r'!type !(\d+)', line)
        functions[name.group(1) or name.group(2)] = {
            'strings': sorted({strings[n] for n in refs if n in strings}),
            'ids': sorted({numbers[n] for n in refs if n in numbers})}
    return functions


def compare_cfi(report):
    comparisons = []
    for driver in DRIVERS:
        tables = [t for t in report['tables'] if t['driver'] == driver and t['compiled']]
        objects = {}
        emitted = set()
        paths = {VARIANT / t['source'] for t in tables}
        paths.update(VARIANT / 'drivers' / driver / 'os_dep/linux' / name
                     for name in ['xmit_linux.c', 'ioctl_linux.c'])
        for source in sorted(paths):
            obj = source.with_suffix('.o')
            assert obj.read_bytes()[:4] == b'BC\xc0\xde', str(obj)
            text = run([WORKSPACE / 'clang-r450784e/bin/llvm-dis', obj, '-o', '-']).stdout
            emitted.update(re.findall(r'^@(\w+) = ', text, re.M))
            object_sha = sha(obj)
            for name, types in cfi_metadata(text).items():
                if types['ids']:
                    objects.setdefault(name, []).append({'object': str(obj.relative_to(VARIANT)),
                                                        'object_sha256': object_sha, **types})
        external = VARIANT / 'out/net/ethtool/ioctl.o'
        assert external.is_file()
        metadata = cfi_metadata(run([WORKSPACE / 'clang-r450784e/bin/llvm-dis', external, '-o', '-']).stdout)
        assert 'ethtool_op_get_link' in metadata
        objects['ethtool_op_get_link'] = [{'object': str(external.relative_to(VARIANT)),
            'object_sha256': sha(external), **metadata['ethtool_op_get_link']}]
        for source_name in sorted({t['source'] for t in tables}):
            source = VARIANT / source_name
            selected = [(t, c) for t in tables if t['source'] == source_name for c in t['callbacks']]
            output = HERE / 'probes' / VARIANT.name / driver
            output.mkdir(parents=True, exist_ok=True)
            code = f'#line 1 "{source}"\n' + source.read_text() + '\n'
            for index, (table, callback) in enumerate(selected):
                match = re.fullmatch(r'(.*?)\(\*\)\((.*)\)', callback['expected_type'])
                assert match, callback
                declared = re.fullmatch(r'(.*?)\s*\((.*)\)', callback['declared_type'])
                assert declared, callback
                for label, parts in [('expected', match.groups()), ('declared', declared.groups())]:
                    code += ('__attribute__((__used__, __noinline__, __optnone__)) ' + parts[0] +
                             f' audit_{label}_{index}(' + parts[1] + ') { __builtin_trap(); }\n')
            probe = output / (source.stem + '.c')
            llvm = probe.with_suffix('.ll')
            probe.write_text(code)
            result = run([CLANG, *compiler_flags(source), '-iquote', source.parent, '-Wno-c2x-extensions',
                          '-S', '-emit-llvm', probe, '-o', llvm])
            (output / (source.stem + '.stderr')).write_text(result.stderr)
            reference = cfi_metadata(llvm.read_text())
            for index, (table, callback) in enumerate(selected):
                expected = reference[f'audit_expected_{index}']
                declared = reference[f'audit_declared_{index}']
                assert len(expected['ids']) == len(declared['ids']) == 1
                actual = objects.get(callback['function'], [])
                # A module-imported function is checked at declaration level only.
                matches = expected['ids'] == declared['ids'] and all(
                    expected['ids'][0] in row['ids'] for row in actual)
                table['emitted'] = table['table'] in emitted
                comparisons.append({'driver': driver, 'table': table['table'], 'kind': table['kind'],
                                    'table_emitted': table['emitted'],
                                    'source': source_name, **callback, 'expected_CFI': expected,
                                    'declaration_CFI': declared, 'compiled_definitions': actual,
                                    'compiled_definition_checked': bool(actual), 'matches': matches})
    report['comparisons'] = comparisons
    report['mismatches'] = [r for r in comparisons if not r['matches']]
    report['emitted_mismatches'] = [r for r in report['mismatches'] if r['table_emitted']]
    report['declaration_only'] = [r for r in comparisons if not r['compiled_definition_checked']]
    report['CFI_comparison_complete'] = True
    report['passed'] = not report['mismatches']
    print(json.dumps({'callbacks': len(comparisons), 'mismatches': len(report['mismatches']),
                      'declaration_only': len(report['declaration_only'])}), flush=True)


def main(inventory_only=False, reuse_inventory=False):
    os.nice(10)
    result = json.loads((VARIANT / 'compile-result.json').read_text())
    assert result['compiled']
    tables = []
    cache = HERE / ('callback-inventory-' + VARIANT.name + '.json')
    if reuse_inventory:
        saved = json.loads(cache.read_text())
        for table in saved['tables']:
            if table['compiled']:
                assert sha(VARIANT / table['source']) == table['source_sha256']
        tables = saved['tables']
    for driver in DRIVERS:
        if reuse_inventory:
            break
        base = VARIANT / 'drivers' / driver
        for source in sorted((base / 'os_dep/linux').glob('*.c')):
            text = source.read_text()
            pattern = r'\bstruct\s+(' + '|'.join(TABLE_TYPES) + r')\s+(?:const\s+)?(\w+)\s*=\s*\{'
            for match in re.finditer(pattern, text):
                kind, name = match.groups()
                nodes = [n for n in ast_nodes(source, name)
                         if n.get('kind') == 'VarDecl' and n.get('name') == name]
                if not nodes:
                    tables.append({'driver': driver, 'table': name, 'kind': kind,
                                   'source': str(source.relative_to(VARIANT)), 'compiled': False})
                    continue
                assert len(nodes) == 1
                fields = [n for n in ast_nodes(source, kind)
                          if n.get('kind') == 'RecordDecl' and n.get('name') == kind
                          and n.get('completeDefinition')]
                assert len(fields) == 1, (driver, name, len(fields))
                fields = [n for n in fields[0].get('inner', []) if n.get('kind') == 'FieldDecl']
                initial = [n for n in nodes[0]['inner'] if n.get('kind') == 'InitListExpr']
                assert len(initial) == 1
                values = initial[0].get('inner', [])
                assert len(values) == len(fields), (name, len(values), len(fields))
                callbacks = []
                for field, value in zip(fields, values):
                    refs = [n['referencedDecl'] for n in walk(value)
                            if n.get('kind') == 'DeclRefExpr'
                            and n.get('referencedDecl', {}).get('kind') == 'FunctionDecl']
                    if not refs:
                        continue
                    assert len(refs) == 1, (name, field['name'])
                    callbacks.append({'field': field['name'], 'expected_type': field['type']['qualType'],
                                      'function': refs[0]['name'], 'declared_type': refs[0]['type']['qualType']})
                tables.append({'driver': driver, 'table': name, 'kind': kind,
                               'source': str(source.relative_to(VARIANT)), 'source_sha256': sha(source),
                               'compiled': True, 'callbacks': callbacks})
                print(json.dumps({'driver': driver, 'table': name, 'callbacks': len(callbacks)}), flush=True)
    report = {'scope': 'Compiled net_device_ops, cfg80211_ops and ethtool_ops tables only',
              'tables': tables, 'device_accessed': False, 'sources_changed': False,
              'CFI_comparison_complete': False}
    cache.write_text(json.dumps(report, indent=2) + '\n')
    if not inventory_only:
        compare_cfi(report)
        (HERE / ('callback-CFI-' + VARIANT.name + '.json')).write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--variant', choices=('wifi2-full-lto', 'wifi3-cfi-monitor'), default='wifi2-full-lto')
    parser.add_argument('--inventory-only', action='store_true')
    parser.add_argument('--reuse-inventory', action='store_true')
    args = parser.parse_args()
    VARIANT = WORKSPACE / args.variant
    main(args.inventory_only, args.reuse_inventory)
