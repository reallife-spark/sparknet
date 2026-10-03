#!/usr/bin/env bash
# Apply chattr +i to critical paths
set -euo pipefail
MANIFEST="/etc/sparknet/critical-manifest.json"
command -v jq >/dev/null 2>&1 || { echo "jq required"; exit 1; }
jq -r '.protected_paths[]' "$MANIFEST" | while read -r f; do
  [ -e "$f" ] || continue
  chown root:root "$f" 2>/dev/null || true
  chmod 644 "$f" 2>/dev/null || true
  chattr +i "$f" 2>/dev/null || true
  echo "locked $f"
done
