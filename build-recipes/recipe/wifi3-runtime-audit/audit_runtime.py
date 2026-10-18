"""Host-only audit of additional CFI callback registrations in compiled Realtek TUs.

Uses the pinned compiler, real Kbuild command flags and real bitcode objects.
Only files below this new audit folder are written. No phone/device commands,
source/object edits, build configuration changes or installation.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE.parent / 'wifi3-audit'))
import audit_callbacks as base
from clang_roots import Clang

base.VARIANT = base.WORKSPACE / 'wifi3-cfi-monitor'
DRIVERS = base.DRIVERS
TRIGGERS = re.compile(r'\b(rtw_init_timer|_init_timer|_init_workitem|INIT_WORK|INIT_DELAYED_WORK|tasklet_init|tasklet_setup|usb_fill_bulk_urb|usb_fill_int_urb|usb_driver|kthread_run|proc_ops|file_operations|seq_operations)\b')
KNOWN_VOID_CALLBACKS = {
    'rtw_init_timer': (2, 'void (*)(void *)'),
    '_init_timer': (2, 'void (*)(void *)'),
    '_init_workitem': (1, 'void (*)(struct work_struct *)'),
}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def walk(node):
    yield node
    for child in node.get('inner', []):
        yield from walk(child)


def typ(node):
    value = node.get('type', {})
    return value.get('desugaredQualType', value.get('qualType', ''))


def refs(node):
    values = {}
    for child in walk(node):
        target = child.get('referencedDecl', {})
        if child.get('kind') == 'DeclRefExpr' and target.get('kind') == 'FunctionDecl':
            values[target['id']] = target
    return list(values.values())


def registrations(tree, api_declarations=None):
    top = tree.get('inner', [])
    declarations = {node['id']: node for node in top
                    if node.get('kind') in ('FunctionDecl', 'RecordDecl') and node.get('id')}
    declarations.update(api_declarations or {})
    records, forwarded = [], []

    def add(value, expected, context, node):
        functions = refs(value)
        if len(functions) != 1:
            if not functions:
                forwarded.append({'context': context, 'expected_type': expected, 'expression_kind': value.get('kind')})
            return
        target = functions[0]
        if not re.fullmatch(r'(.*?)\(\*\)\((.*)\)', expected):
            return
        records.append({'context': context, 'expected_type': expected, 'function': target['name'],
                        'declared_type': typ(target), 'location': node.get('range', {}).get('begin', {})})

    # These roots were selected from main-file and driver-header definitions
    # with libclang; the executable dumps their actual JSON AST afterwards.
    roots = [node for node in top if node.get('kind') in ('FunctionDecl', 'VarDecl')]
    for root in roots:
      for node in walk(root):
        kind = node.get('kind')
        inner = node.get('inner', [])
        if kind == 'CallExpr' and inner:
            targets = refs(inner[0])
            if len(targets) != 1:
                continue
            target = targets[0]
            name = target['name']
            declaration = declarations.get(target['id'], declarations.get('function:' + name, {}))
            params = [child for child in declaration.get('inner', []) if child.get('kind') == 'ParmVarDecl']
            for index, value in enumerate(inner[1:]):
                expected = typ(params[index]) if index < len(params) else ''
                if name in KNOWN_VOID_CALLBACKS and index == KNOWN_VOID_CALLBACKS[name][0]:
                    expected = KNOWN_VOID_CALLBACKS[name][1]
                if '(*)(' in expected:
                    add(value, expected, f'call:{name}:arg{index}', node)
        elif kind == 'BinaryOperator' and node.get('opcode') == '=' and len(inner) == 2:
            expected = typ(inner[0])
            if '(*)(' in expected:
                field = next((child.get('name') for child in walk(inner[0]) if child.get('kind') == 'MemberExpr'), '')
                add(inner[1], expected, 'assignment:' + field, node)
        elif kind == 'InitListExpr' and typ(node).startswith('struct '):
            name = typ(node)[7:]
            candidates = [decl for decl in declarations.values() if decl.get('kind') == 'RecordDecl'
                          and decl.get('name') == name and decl.get('completeDefinition')]
            if 'record:' + name in declarations:
                candidates = [declarations['record:' + name]]
            if len(candidates) != 1:
                continue
            fields = [field for field in candidates[0].get('inner', []) if field.get('kind') == 'FieldDecl']
            if len(fields) != len(inner):
                continue
            for field, value in zip(fields, inner):
                expected = typ(field)
                if '(*)(' in expected and refs(value):
                    add(value, expected, f'initializer:{name}.{field["name"]}', node)
    unique = {}
    for record in records:
        key = (record['expected_type'], record['declared_type'], record['function'])
        if key not in unique:
            unique[key] = {**record, 'contexts': []}
        unique[key]['contexts'].append(record['context'])
    return list(unique.values()), forwarded


def main(limit=None, marker_only=False):
    started = time.time()
    assert sha(ROOT / 'artifacts/realme-note60x/gki-wifi3-cfi-monitor/kernel.config') == '513cad42f78dee45b7892917cc7c080971734d990b866243fabeece1c22bcb8b'
    assert sha(base.VARIANT / 'out/.config') == '513cad42f78dee45b7892917cc7c080971734d990b866243fabeece1c22bcb8b'
    records, source_rows, excluded = [], [], []
    api = Clang(base.WORKSPACE / 'clang-r450784e/lib64/libclang.so.13')
    for driver in DRIVERS:
        shared_wrappers_checked = False
        for source in sorted((base.VARIANT / 'drivers' / driver).rglob('*.c')):
            if source.name.endswith('.mod.c'):
                continue  # Kbuild-generated CRC metadata, not driver callbacks.
            if marker_only and not TRIGGERS.search(source.read_text(errors='replace')):
                continue
            obj = source.with_suffix('.o')
            cmd = source.with_name('.' + source.stem + '.o.cmd')
            if not obj.is_file() or not cmd.is_file():
                excluded.append(str(source.relative_to(base.VARIANT)))
                continue
            if limit is not None and len(source_rows) >= limit:
                break
            destination = HERE / 'probes' / driver / source.relative_to(base.VARIANT / 'drivers' / driver).with_suffix('')
            destination.mkdir(parents=True, exist_ok=True)
            before = {'source': sha(source), 'object': sha(obj), 'command': sha(cmd), 'auditor': sha(Path(__file__)),
                      'root_selector': sha(HERE / 'clang_roots.py')}
            cache = destination / 'registration-checks.json'
            if cache.exists():
                cached = json.loads(cache.read_text())
                if cached['source_row']['sha256'] == before:
                    records.extend(cached['comparisons'])
                    source_rows.append(cached['source_row'])
                    print(json.dumps({'cached': str(source.relative_to(base.VARIANT)), 'callbacks': len(cached['comparisons'])}), flush=True)
                    continue
            print(json.dumps({'checking': str(source.relative_to(base.VARIANT))}), flush=True)
            # libclang selects roots; the pinned clang executable supplies JSON
            # AST and final CFI metadata. Large unrelated kernel-header bodies
            # are not serialized for every source file.
            names, declarations, api_records = api.roots(source, base.compiler_flags(source), base.VARIANT / 'out')
            shared = {'_init_timer', '_init_workitem', 'timer_hdl'}
            shared_roots = [name for name in names if name in shared]
            names = [name for name in names if name not in shared]
            reused_wrappers = shared_wrappers_checked
            if not shared_wrappers_checked:
                names.extend(name for name in shared_roots if name != 'timer_hdl')
            if shared_wrappers_checked:
                api_records = [row for row in api_records if row['owner'] not in shared]
            if shared_roots or any(row['owner'] in shared for row in api_records):
                shared_wrappers_checked = True
            nodes, decoder = [], json.JSONDecoder()
            for name in names:
                ast = base.run([base.CLANG, *base.compiler_flags(source), '-fsyntax-only', '-Xclang', '-ast-dump=json',
                                '-Xclang', '-ast-dump-filter', '-Xclang', name, source])
                remaining = ast.stdout.lstrip()
                while remaining:
                    node, end = decoder.raw_decode(remaining)
                    nodes.append(node)
                    remaining = remaining[end:].lstrip()
            selected, forwarded = registrations({'inner': nodes}, declarations)
            selected.extend(api_records)
            unique = {}
            for row in selected:
                key = (row['expected_type'], row['declared_type'], row['function'])
                if key not in unique:
                    unique[key] = row
                else:
                    unique[key]['contexts'].extend(row['contexts'])
            selected = list(unique.values())
            code = ''
            for index, row in enumerate(selected):
                expected = re.fullmatch(r'(.*?)\(\*\)\((.*)\)', row['expected_type'])
                declared = re.fullmatch(r'(.*?)\s*\((.*)\)', row['declared_type'])
                assert expected and declared, row
                for label, parts in [('expected', expected.groups()), ('declared', declared.groups())]:
                    code += ('__attribute__((__used__, __noinline__, __optnone__)) ' + parts[0] +
                             f' runtime_audit_{label}_{index}(' + parts[1] + ') { __builtin_trap(); }\n')
            probe, llvm = destination / 'probe.c', destination / 'probe.ll'
            headers = '#include <drv_types.h>\n#include <linux/usb.h>\n#include <linux/proc_fs.h>\n#include <linux/seq_file.h>\n#include <linux/ethtool.h>\n'
            probe.write_text(headers + code, encoding='latin-1')
            command = [base.CLANG, *base.compiler_flags(source), '-iquote', source.parent,
                       '-Wno-c2x-extensions', '-S', '-emit-llvm', probe, '-o', llvm]
            full_source_probe = False
            try:
                if selected:
                    result = base.run(command)
                else:
                    llvm.write_text('; No direct callback registrations in the selected AST roots.\n')
                    result = type('EmptyResult', (), {'stderr': ''})()
            except RuntimeError as error:
                # Some source-local typedefs require the complete source scope.
                # This fallback retains the same type test and compiler flags.
                (destination / 'header-probe-retry-reason.txt').write_text(str(error))
                probe.write_text(f'#line 1 "{source}"\n' + source.read_text(encoding='latin-1') + '\n' + code, encoding='latin-1')
                full_source_probe = True
                result = base.run(command)
            (destination / 'compiler.stderr').write_text(result.stderr)
            metadata = base.cfi_metadata(llvm.read_text())
            comparisons = []
            for index, row in enumerate(selected):
                expected = metadata[f'runtime_audit_expected_{index}']
                declared = metadata[f'runtime_audit_declared_{index}']
                assert len(expected['ids']) == len(declared['ids']) == 1
                comparisons.append({**row, 'driver': driver, 'source': str(source.relative_to(base.VARIANT)),
                                'expected_CFI': expected, 'declared_CFI': declared,
                                'declaration_matches': expected['ids'] == declared['ids']})
            require_unchanged = {'source': sha(source), 'object': sha(obj), 'command': sha(cmd), 'auditor': sha(Path(__file__)),
                                 'root_selector': sha(HERE / 'clang_roots.py')}
            assert before == require_unchanged, 'Original source/object/command changed during audit'
            row = {'driver': driver, 'source': str(source.relative_to(base.VARIANT)), 'sha256': before, 'AST_roots': names,
                   'probe_requires_original_source_scope': full_source_probe,
                   'probe_compiled': bool(selected), 'shared_timer_work_wrappers_checked_once_per_driver': True,
                   'shared_wrapper_roots_reused': reused_wrappers,
                   'callbacks': len(selected), 'forwarded_or_indirect_expressions': forwarded,
                   'probe_sha256': sha(probe), 'probe_LLVM_sha256': sha(llvm)}
            source_rows.append(row)
            records.extend(comparisons)
            write(cache, {'source_row': row, 'comparisons': comparisons})
            print(json.dumps({'source': row['source'], 'callbacks': len(selected), 'elapsed_seconds': round(time.time() - started)}), flush=True)
        if limit is not None and len(source_rows) >= limit:
            break
    objects = {}
    checked_objects = []
    for driver in DRIVERS:
        needed = {row['function'] for row in records if row['driver'] == driver}
        if not needed:
            continue
        for obj in sorted((base.VARIANT / 'drivers' / driver).rglob('*.o')):
            if obj.read_bytes()[:4] != b'BC\xc0\xde':
                continue
            digest = sha(obj)
            metadata = base.cfi_metadata(base.run([base.WORKSPACE / 'clang-r450784e/bin/llvm-dis', obj, '-o', '-']).stdout)
            for name in needed & metadata.keys():
                objects.setdefault((driver, name), []).append({'object': str(obj.relative_to(base.VARIANT)),
                                                              'sha256': digest, **metadata[name]})
            checked_objects.append({'object': str(obj.relative_to(base.VARIANT)), 'sha256': digest})
    for row in records:
        actual = objects.get((row['driver'], row['function']), [])
        row['compiled_definitions'] = actual
        row['compiled_definition_checked'] = bool(actual)
        row['matches'] = row['declaration_matches'] and all(row['expected_CFI']['ids'][0] in value['ids'] for value in actual)
    mismatches = [row for row in records if not row['matches']]
    report = {'scope': 'Callback-valued calls, assignments and struct initializers in compiled Realtek translation units',
              'host_only': True, 'device_contacted': False, 'original_sources_and_objects_modified': False,
              'limited_run': limit is not None, 'marker_only': marker_only, 'source_count': len(source_rows), 'callbacks': len(records),
              'compiled_definition_checks': sum(row['compiled_definition_checked'] for row in records),
              'mismatches': mismatches, 'passed': not mismatches, 'sources': source_rows, 'comparisons': records,
              'objects': checked_objects, 'uncompiled_trigger_sources': excluded,
              'limits': ['Main-file AST registrations and driver timer/work wrappers are analyzed; this is not proof about every dynamic indirect call.',
                         'Forwarded/dynamic callback expressions are recorded, not solved by an interprocedural analysis.',
                         'Declarations without compiled definitions do not prove runtime CFI type identity.',
                         'Timer/workqueue/USB lifecycle, races, memory safety and on-air behavior require hardware testing.']}
    target = HERE / ('smoke-test.json' if limit is not None else 'runtime-CFI-review.json')
    write(target, report)
    print(json.dumps({'report': str(target), 'sources': len(source_rows), 'callbacks': len(records),
                      'mismatches': len(mismatches), 'elapsed_seconds': round(time.time() - started)}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int)
    parser.add_argument('--marker-only', action='store_true')
    args = parser.parse_args()
    main(args.limit, args.marker_only)
