#!/usr/bin/env bash
# sparknet-node-setup — thin exec wrapper. The implementation is
# sparknet-node-setup.py beside this file; the name stays stable for the
# runbook, bootstrap-agx.sh and operators.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${SPARKNET_PYTHON:-python3}" "$HERE/sparknet-node-setup.py" "$@"
