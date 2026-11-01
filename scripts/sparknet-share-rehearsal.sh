#!/usr/bin/env bash
# Three-node share rehearsal: loopback wire, payload inbox, 4203 queue and a
# human-signed lift. This is not a live-overlay or systemd claim.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${SPARKNET_PYTHON:-$ROOT/.venv/bin/python}"
exec "$PY" "$ROOT/scripts/sparknet-share-rehearsal.py" "$@"
