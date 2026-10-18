# Security policy

**English** | [Русский](SECURITY_RU.md)

This project contains dual-use wireless driver functionality intended for
driver development, personal equipment diagnostics and authorized security
testing.

## Reporting a project security issue

Open a GitHub issue for:

- a release checksum or build-integrity mismatch;
- unsafe module-loader behavior;
- unexpected device or partition access by a build/repack tool;
- accidentally published private data;
- a licensing or corresponding-source problem.

Do not include device serial numbers, IMEI values, MAC addresses, credentials,
private captures, keys or partition dumps in a public report. Describe the
class of sensitive information first and wait for an appropriate private
channel before sharing the data itself.

## Scope

The project accepts reports about its source, artifacts, packaging and guarded
module-loading behavior. It does not accept requests to target third-party
networks, bypass the owner's authorization or hide unauthorized activity.

## Integrity model

The release uses published SHA-256 values, a strict stock-boot input hash,
payload checksums and a matched kernel/module certificate. A mismatch should
be treated as a failed validation rather than bypassed.
