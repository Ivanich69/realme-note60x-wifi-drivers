from pathlib import Path
import json

root = Path('/home/sad1/wifi-kernel-realme-note60x/drivers')
matches = []
for path in (root / 'rtl8812au').rglob('*'):
    if path.is_file() and path.suffix in {'.c', '.h'}:
        for number, line in enumerate(path.read_text(errors='replace').splitlines(), 1):
            if any(name in line for name in ('get_rxbuf_desc', 'pkt_to_recvframe', 'pkt_to_recvmem', 'pkt_to_recvdata')):
                matches.append({'file': str(path.relative_to(root)), 'line': number, 'text': line})
print(json.dumps(matches))
