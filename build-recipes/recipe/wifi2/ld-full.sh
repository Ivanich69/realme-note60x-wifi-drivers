#!/usr/bin/env bash
set -euo pipefail
workspace=${REALME_WORKSPACE:-/home/sad1/wifi-kernel-realme-note60x}
# Restrict this linker invocation only. No WSL settings or other jobs change.
exec "$workspace/clang-r450784e/bin/ld.lld" --threads=1 --lto-partitions=1 "$@"
