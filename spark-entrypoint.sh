#!/usr/bin/env bash
# spark-entrypoint — thin exec wrapper. The implementation is spark-entrypoint.py
# beside this file; the image keeps this name as its ENTRYPOINT so compose and
# operators need no change. No logic lives here.
set -euo pipefail

HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec "${SPARKNET_PYTHON:-python3}" "$HERE/spark-entrypoint.py" "$@"
