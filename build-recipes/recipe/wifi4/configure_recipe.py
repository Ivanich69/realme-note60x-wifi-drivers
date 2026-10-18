"""Create new host-only recipes; do not execute builds, payloads or devices."""

import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def main():
    net = HERE.parent / 'wifi4-audit'
    runtime = HERE.parent / 'wifi4-runtime-audit'
    assert not net.exists() and not runtime.exists()
    net.mkdir()
    runtime.mkdir()
    text = (HERE.parent / 'wifi3-audit/audit_callbacks.py').read_text(encoding='utf-8')
    text = text.replace("choices=('wifi2-full-lto', 'wifi3-cfi-monitor'), default='wifi2-full-lto'",
                        "choices=('wifi4-cfi-runtime',), default='wifi4-cfi-runtime'")
    (net / 'audit_callbacks.py').write_text(text, encoding='utf-8', newline='\n')
    for name in ('audit_runtime.py', 'clang_roots.py'):
        text = (HERE.parent / 'wifi3-runtime-audit' / name).read_text(encoding='utf-8')
        if name == 'audit_runtime.py':
            text = text.replace("base.VARIANT = base.WORKSPACE / 'wifi3-cfi-monitor'", "base.VARIANT = base.WORKSPACE / 'wifi4-cfi-runtime'")
        (runtime / name).write_text(text, encoding='utf-8', newline='\n')
    text = (HERE.parent / 'wifi3/export_artifacts.py').read_text(encoding='utf-8')
    text = text.replace('gki-wifi2-full-lto', 'gki-wifi3-cfi-monitor')
    text = text.replace('wifi3-cfi-monitor', 'wifi4-cfi-runtime')
    text = text.replace("BASE = ROOT / 'artifacts/realme-note60x/gki-wifi4-cfi-runtime'",
                        "BASE = ROOT / 'artifacts/realme-note60x/gki-wifi3-cfi-monitor'")
    text = text.replace('wifi3-audit', 'wifi4-audit')
    text = text.replace('realme-note60x-wifi3-module-build.log', 'realme-note60x-wifi4-module-build.log')
    text = text.replace("shutil.copyfile(BASE / 'build.log', ART / 'core-build-wifi2.log')",
                        "shutil.copyfile(BASE / 'core-build-wifi2.log', ART / 'core-build-wifi2.log')")
    text = text.replace("HERE / 'inputs.json', ART / 'wifi3-inputs.json'", "HERE / 'inputs.json', ART / 'wifi4-inputs.json'")
    text = text.replace("read(HERE.parent / 'wifi4-audit/callback-CFI-wifi2-full-lto.json')",
                        "read(BASE / 'callback-CFI-validation.json')")
    text = text.replace("(HERE / 'monitor-callback-cfi.patch')", "(HERE / 'runtime-callback-cfi.patch')")
    text = text.replace("'recipe/wifi3/'", "'recipe/wifi4/'")
    text = text.replace("'recipe/wifi3/shared/'", "'recipe/wifi4/shared/'")
    text = text.replace("for name in ['callback-CFI-wifi2-full-lto.json', 'callback-CFI-wifi4-cfi-runtime.json']:",
                        "for name in ['callback-CFI-wifi4-cfi-runtime.json']:")
    text = text.replace("'base_variant': 'wifi2-full-lto'", "'base_variant': 'wifi3-cfi-monitor'")
    text = text.replace("'wifi3_source_changes': inputs['source_changes']", "'wifi4_source_changes': inputs['source_changes']")
    text = text.replace('Host-only monitor CFI module refinement; wifi2 core reused unchanged',
                        'Host-only typed runtime callback wrappers; wifi3 core reused unchanged')
    # Never export modules merely on the strength of the old network-table audit.
    needle = "    shutil.copytree(BASE, ART, dirs_exist_ok=True)"
    replacement = """    runtime = read(HERE.parent / 'wifi4-runtime-audit/runtime-CFI-review.json')
    assert runtime['passed'] and not runtime['mismatches'] and not runtime['limited_run'] and not runtime['marker_only']
    assert not runtime['device_contacted'] and runtime['source_count'] >= 400
    shutil.copytree(BASE, ART, dirs_exist_ok=True)"""
    assert text.count(needle) == 1
    text = text.replace(needle, replacement)
    needle = "    write(ART / 'callback-CFI-validation.json', audit)"
    text = text.replace(needle, needle + "\n    write(ART / 'runtime-CFI-validation.json', runtime)\n"
                        "    write(ART / 'runtime-CFI-before.json', read(HERE.parent / 'wifi3-runtime-audit/runtime-CFI-review.json'))")
    (HERE / 'export_artifacts.py').write_text(text, encoding='utf-8', newline='\n')
    files = [net / 'audit_callbacks.py', runtime / 'audit_runtime.py', runtime / 'clang_roots.py', HERE / 'export_artifacts.py']
    pin = {'host_only': True, 'executes_generated_scripts': False, 'phone_contacted': False,
           'files': {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}}
    (HERE / 'configured-recipes.json').write_text(json.dumps(pin, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'host_only': True, 'prepared_recipes': len(files), 'phone_contacted': False}))


if __name__ == '__main__':
    main()
