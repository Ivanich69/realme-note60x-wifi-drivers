"""Check actual TX callback declarations against the kernel's Clang CFI type."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, default=Path('/home/sad1/wifi-kernel-realme-note60x'))
    args = parser.parse_args()
    common = args.workspace / 'common'
    drivers = args.workspace / 'wifi2-full-lto/drivers'
    header = (common / 'include/linux/netdevice.h').read_text()
    enum = re.search(r'enum netdev_tx\s*\{.*?\};', header, re.S).group(0)
    assert re.search(r'netdev_tx_t\s+\(\*ndo_start_xmit\)\s*\(struct sk_buff\s*\*\s*\w+,\s*struct net_device\s*\*\s*\w+\)', header), 'Kernel callback contract changed'
    source = ('#define INT_MIN (-2147483647-1)\n' + enum + '\n'
              'typedef enum netdev_tx netdev_tx_t; struct sk_buff; struct net_device;\n'
              'typedef struct sk_buff _pkt; typedef struct net_device *_nic_hdl;\n'
              'netdev_tx_t reference(struct sk_buff *a, struct net_device *b) {return NETDEV_TX_OK;}\n'
              'int legacy(struct sk_buff *a, struct net_device *b) {return 0;}\n')
    records = []
    for driver in ('rtl8812au', 'rtl8188eus', 'rtl8812bu'):
        path = drivers / driver / 'os_dep/linux/xmit_linux.c'
        text = path.read_text()
        signature = re.search(r'^(?:netdev_tx_t|int)\s+rtw_xmit_entry\([^)]*\)', text, re.M).group(0)
        name = 'callback_' + driver
        assert signature.startswith('netdev_tx_t '), driver
        prototype = (drivers / driver / 'include/xmit_osdep.h').read_text()
        linux = prototype[prototype.index('#ifdef PLATFORM_LINUX'):]
        assert re.search(r'extern netdev_tx_t\s+rtw_xmit_entry\(', linux), driver
        source += signature.replace('rtw_xmit_entry', name) + ' {return NETDEV_TX_OK;}\n'
        records.append({'driver': driver, 'signature': signature,
                        'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    command = [str(args.workspace / 'clang-r450784e/bin/clang'), '--target=aarch64-linux-gnu',
               '-flto', '-fsanitize=cfi', '-fsanitize-cfi-cross-dso',
               '-fno-sanitize-cfi-canonical-jump-tables', '-fvisibility=hidden',
               '-S', '-emit-llvm', '-x', 'c', '-', '-o', '-']
    result = subprocess.run(command, input=source, capture_output=True, text=True, check=True, timeout=30)
    metadata = dict(re.findall(r'^!(\d+) = !\{i64 0, !"([^"]+)"\}', result.stdout, re.M))
    numeric = dict(re.findall(r'^!(\d+) = !\{i64 0, i64 (-?\d+)\}', result.stdout, re.M))
    def type_references(name):
        declaration = next(line for line in result.stdout.splitlines() if re.search(r'@' + name + r'\(', line) and line.startswith('define '))
        return re.findall(r'!type !(\d+)', declaration)
    def cfi_type(name):
        types = [metadata[n] for n in type_references(name) if n in metadata]
        return next(value for value in types if not value.endswith('.generalized'))
    def type_id(name):
        values = [numeric[n] for n in type_references(name) if n in numeric]
        assert len(values) == 1, (name, values)
        return values[0]
    expected = cfi_type('reference')
    assert cfi_type('legacy') != expected, 'Negative control did not distinguish the old return type'
    assert type_id('legacy') != type_id('reference'), 'Cross-DSO IDs did not distinguish the old return type'
    for row in records:
        row['cfi_type'] = cfi_type('callback_' + row['driver'])
        assert row['cfi_type'] == expected, row
        row['cross_DSO_type_id'] = type_id('callback_' + row['driver'])
        assert row['cross_DSO_type_id'] == type_id('reference'), row
    report = {'passed': True, 'scope': 'Three Linux ndo_start_xmit declarations; not all callbacks or runtime CFI',
              'expected_type': expected, 'legacy_type': cfi_type('legacy'),
              'expected_cross_DSO_type_id': type_id('reference'), 'legacy_cross_DSO_type_id': type_id('legacy'),
              'legacy_type_rejected': True, 'callbacks': records,
              'kernel_header_sha256': hashlib.sha256((common / 'include/linux/netdevice.h').read_bytes()).hexdigest()}
    (HERE / 'xmit-cfi-validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
