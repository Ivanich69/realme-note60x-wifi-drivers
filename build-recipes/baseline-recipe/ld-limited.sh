#!/usr/bin/env bash
set -euo pipefail
workspace=${REALME_WORKSPACE:-/home/sad1/wifi-kernel-realme-note60x}
exec "$workspace/clang-r450784e/bin/ld.lld" --threads=2 --thinlto-jobs=2 "$@"
