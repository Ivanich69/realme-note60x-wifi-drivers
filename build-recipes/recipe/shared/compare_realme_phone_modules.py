"""Compare collected stock modules with the built kernel and Wi-Fi stack."""

import json
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILT = ROOT / 'artifacts/realme-note60x/gki-wifi1'


def main(output=None):
    out = Path((ROOT / 'diagnostics/realme-wifi-install-latest.txt').read_text().strip())
    phone = json.loads((out / 'stock-module-abi.json').read_text())
    ramdisk = json.loads((ROOT / 'build/realme-note60x/vendor-module-abi.json').read_text())['modules']
    rows = phone + ramdisk
    stock_exports = {}
    for row in rows:
        for name, crc in row['export_crcs'].items():
            assert name not in stock_exports or stock_exports[name]['crc'] == crc, name
            stock_exports[name] = {'crc': crc, 'module': row['file']}
    available = {}
    for line in (BUILT / 'Module.symvers').read_text().splitlines():
        crc, name, owner, *_ = line.split()
        available[name] = {'crc': crc, 'module': owner}
    stock_core_checks = []
    for row in rows:
        missing, mismatches = [], []
        checked = 0
        for name, expected in row['import_crcs'].items():
            if name in stock_exports:
                continue
            actual = available.get(name)
            checked += 1
            if actual is None:
                missing.append(name)
            elif actual['crc'] != expected:
                mismatches.append({'symbol': name, 'stock': expected, 'built': actual['crc']})
        stock_core_checks.append({'module': row['file'], 'checked': checked,
                                  'missing': missing, 'mismatches': mismatches})
    cfg = next(row for row in phone if Path(row['file']).name == 'cfg80211.ko')
    cfg_exports = cfg['export_crcs']
    cfg_comparison = [{'symbol': name, 'stock': crc, 'new': available.get(name)}
                      for name, crc in cfg_exports.items()
                      if name not in available or available[name]['crc'] != crc]
    built = json.loads((BUILT / 'module-validation.json').read_text())['modules']
    new_on_stock = []
    replacement_checks = []
    for row in built:
        if row['file'] in ('zram.ko', 'zsmalloc.ko', 'cfg80211.ko'):
            continue
        errors = []
        for name, expected in row['import_crcs'].items():
            if name in cfg_exports and cfg_exports[name] != expected:
                errors.append({'symbol': name, 'new_driver': expected, 'stock_cfg80211': cfg_exports[name]})
        new_on_stock.append({'module': row['file'], 'cfg80211_errors': errors})
    for row in rows:
        errors = []
        for name, expected in row['import_crcs'].items():
            if name in cfg_exports and (name not in available or available[name]['crc'] != expected):
                errors.append({'symbol': name, 'stock_driver': expected, 'new_cfg80211': available.get(name)})
        if errors:
            replacement_checks.append({'module': row['file'], 'errors': errors})
    bad_core = [row for row in stock_core_checks if row['missing'] or row['mismatches']]
    record = {'copied_modules': len(phone), 'vendor_boot_modules': len(ramdisk),
              'stock_core_checks': stock_core_checks, 'core_incompatible_modules': bad_core,
              'stock_cfg80211_exports': len(cfg_exports),
              'stock_vs_new_cfg80211_differences': cfg_comparison,
              'new_drivers_with_stock_cfg80211': new_on_stock,
              'stock_drivers_with_new_cfg80211_errors': replacement_checks,
              'hardware_load_tested': False}
    destination = output or out / 'full-module-compatibility.json'
    destination.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({'copied_modules': len(phone), 'vendor_boot_modules': len(ramdisk),
                      'core_incompatible_modules': bad_core,
                      'cfg80211_export_differences': len(cfg_comparison),
                      'new_on_stock_errors': [r for r in new_on_stock if r['cfg80211_errors']],
                      'stock_on_new_errors': replacement_checks}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts', type=Path, default=BUILT)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    BUILT = args.artifacts.resolve()
    assert BUILT.is_relative_to((ROOT / 'artifacts/realme-note60x').resolve())
    if args.output:
        assert args.output.resolve().is_relative_to((ROOT / 'artifacts/realme-note60x').resolve())
    main(args.output)
