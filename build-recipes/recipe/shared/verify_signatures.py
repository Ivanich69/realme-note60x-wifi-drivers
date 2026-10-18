"""Verify module and regulatory database signatures using host OpenSSL."""

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HOST = Path("/mnt/f/wifi_work")
ROOT = Path(os.environ.get("REALME_WORKSPACE", "/home/sad1/wifi-kernel-realme-note60x"))
ARTIFACTS = Path(os.environ.get("REALME_ARTIFACTS", str(HOST / "artifacts/realme-note60x/gki-wifi1")))


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise ValueError(result.stderr)
    return result


def main():
    temp = Path(os.environ.get("REALME_SIGNATURE_TEMP", str(ROOT / "signature-validation")))
    temp.mkdir(exist_ok=True)
    regdb_only = sys.argv[1:] == ["--regdb-only"]
    assert not sys.argv[1:] or regdb_only
    module_cert = temp / "module-cert.pem"
    if not regdb_only:
        run("/usr/bin/openssl", "x509", "-inform", "DER", "-in",
            str(ARTIFACTS / "module-signing-cert.x509"), "-out", str(module_cert))
    magic = b"~Module signature appended~\n"
    records = []
    signature_path = temp / "signature.der"
    content_path = temp / "content.bin"
    for path in ([] if regdb_only else sorted((ARTIFACTS / "modules").glob("*.ko"))):
        raw = path.read_bytes()
        assert raw.endswith(magic), path.name
        footer_offset = len(raw) - len(magic) - 12
        footer = raw[footer_offset:footer_offset + 12]
        assert footer[2] == 2 and footer[3:8] == b"\0" * 5, path.name
        length = int.from_bytes(footer[-4:], "big")
        assert 256 < length < footer_offset
        signature_path.write_bytes(raw[footer_offset - length:footer_offset])
        content_path.write_bytes(raw[:footer_offset - length])
        run("/usr/bin/openssl", "cms", "-verify", "-binary", "-inform", "DER",
            "-in", str(signature_path), "-content", str(content_path),
            "-certfile", str(module_cert), "-noverify", "-out", "/dev/null")
        records.append({"module": path.name, "PKCS7_signature_verified": True,
                        "sha256": hashlib.sha256(raw).hexdigest()})

    regdb_certs = temp / "regdb-certs.pem"
    cert_text = ""
    for path in sorted((ROOT / "common/net/wireless/certs").glob("*.hex")):
        der = bytes.fromhex("".join(re.findall(r"0x([0-9a-fA-F]{2})", path.read_text())))
        der_path = temp / (path.stem + ".der")
        der_path.write_bytes(der)
        cert_text += run("/usr/bin/openssl", "x509", "-inform", "DER", "-in", str(der_path)).stdout
    assert cert_text
    regdb_certs.write_text(cert_text)
    firmware = HOST / ".reference/realme-note60x/regulatory-db" if regdb_only else ARTIFACTS / "firmware"
    run("/usr/bin/openssl", "cms", "-verify", "-binary", "-inform", "DER",
        "-in", str(firmware / "regulatory.db.p7s"), "-content", str(firmware / "regulatory.db"),
        "-certfile", str(regdb_certs), "-noverify", "-out", "/dev/null")
    report = {"modules": records, "regulatory_db_signature_verified_with_kernel_certificates": True,
              "private_key_exported": False, "phone_accessed": False}
    result_path = (HOST / "build/realme-note60x/regdb-signature-validation.json" if regdb_only
                   else ARTIFACTS / "signature-validation.json")
    result_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"module_signatures_verified": len(records), "regulatory_db_signature_verified": True}))


if __name__ == "__main__":
    main()
