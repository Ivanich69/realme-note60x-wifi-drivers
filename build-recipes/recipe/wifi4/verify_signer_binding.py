"""Host-only positive/negative check for explicit module signer selection."""

import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ART = ROOT / 'artifacts/realme-note60x/gki-wifi4-cfi-runtime'


def main():
    temp = HERE / 'signature-binding-test'
    temp.mkdir(exist_ok=False)
    module = ART / 'modules/8188eu.ko'
    raw = module.read_bytes()
    magic = b'~Module signature appended~\n'
    assert raw.endswith(magic)
    footer = len(raw) - len(magic) - 12
    size = int.from_bytes(raw[footer + 8:footer + 12], 'big')
    assert 256 < size < footer
    content, signature = temp / 'content.bin', temp / 'signature.der'
    content.write_bytes(raw[:footer - size])
    signature.write_bytes(raw[footer - size:footer])
    good, wrong = HERE / 'signature-check/module-cert.pem', ART / 'stock-module-cert.pem'
    commands = []
    for name, cert, accepted in (('matching-explicit-cert', good, True), ('different-explicit-cert', wrong, False)):
        args = ['/usr/bin/openssl', 'cms', '-verify', '-binary', '-inform', 'DER', '-in', str(signature),
                '-content', str(content), '-certfile', str(cert), '-nointern', '-noverify', '-out', '/dev/null']
        result = subprocess.run(args, capture_output=True, timeout=30)
        assert (result.returncode == 0) == accepted
        if not accepted:
            assert b'signer certificate not found' in result.stderr.lower()
        commands.append({'case': name, 'passed': True, 'exit_code': result.returncode,
                         'stderr': result.stderr.decode(errors='replace'),
                         'explicit_certificate_sha256': hashlib.sha256(cert.read_bytes()).hexdigest()})
    report = {'host_only': True, 'phone_contacted': False, 'module': module.name,
              'module_sha256': hashlib.sha256(raw).hexdigest(), 'cases_passed': 2,
              'embedded_certificates_not_used_to_override_explicit_cert': True, 'cases': commands}
    (ART / 'signature-binding-negative.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'host_only': True, 'signature_binding_checks_passed': 2, 'phone_contacted': False}))


if __name__ == '__main__':
    main()
