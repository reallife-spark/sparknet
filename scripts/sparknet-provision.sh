#!/usr/bin/env bash
# Provision (dry-run aware via --dry-run)
set -euo pipefail
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1
mkdir -p /etc/sparknet
cp /mnt/knowledge/sparknet/manifests/critical-manifest.json /etc/sparknet/ 2>/dev/null || true
cp /mnt/knowledge/sparknet/manifests/security-policies.json /etc/sparknet/ 2>/dev/null || true
cp /mnt/knowledge/sparknet/manifests/node-template-manifest.json /etc/sparknet/ 2>/dev/null || true
if [ $DRY -eq 0 ]; then
  /mnt/knowledge/sparknet/scripts/sparknet-identity-capture.sh
  /mnt/knowledge/sparknet/scripts/sparknet-lockdown.sh
fi
