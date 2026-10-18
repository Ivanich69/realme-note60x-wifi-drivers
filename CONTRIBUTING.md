# Contributing

**English** | [Русский](CONTRIBUTING_RU.md)

Contributions are welcome, especially adapter compatibility reports, focused
driver fixes and reproducible build results.

## Adapter reports

Please include:

- exact adapter name and hardware revision;
- USB VID:PID;
- chipset family, if confirmed;
- supported 2.4/5 GHz bands;
- whether a new network interface appeared;
- separate results for ordinary scanning, monitor mode and frame injection;
- OTG adapter type and external power details;
- project release and SHA-256 of the files used.

Do not publish phone serial numbers, IMEI values, MAC addresses, passwords,
private network captures, credentials, private keys or partition dumps.

## Source changes

A pull request should:

1. describe the concrete problem and affected driver;
2. preserve upstream copyright and license headers;
3. exclude proprietary APKs, OEM boot images and user partition data;
4. list the host-side checks performed;
5. update manifests and documentation when artifacts change;
6. avoid automatic phone access, deployment or flashing in build scripts.

For callback changes under CFI, provide evidence that the actual function
definition matches the callback registration type after compilation.

## Adding a firmware target

Support for another Realme UI build must be a separate variant. Renaming the
C.13 package is insufficient. A new target requires a fresh review of the
kernel commit, configuration, vendor module ABI, signing certificate, boot
metadata, module set and complete build/validation cycle.

## Release integrity

When changing release binaries:

- regenerate `SHA256SUMS.txt`;
- update `SOURCE_MANIFEST.json` and provenance data;
- publish complete corresponding source;
- document which hardware behavior was actually tested;
- distinguish host validation from device validation.
