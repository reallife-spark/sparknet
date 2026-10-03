#!/usr/bin/env bash
# Identity capture (non-secret only)
set -euo pipefail
OUT="/etc/sparknet/user-env-manifest.json"
mkdir -p /etc/sparknet
cat > "$OUT.tmp" <<JSON
{
  "schema_version": "1.0",
  "generated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "host": {
    "hostname": "$(hostname -f 2>/dev/null || hostname)",
    "os": "$(grep -E '^PRETTY_NAME' /etc/os-release 2>/dev/null | cut -d= -f2 | tr -d '"')",
    "kernel": "$(uname -r)",
    "arch": "$(uname -m)"
  },
  "user": {
    "uid": $(id -u),
    "gid": $(id -g),
    "username": "$(id -un)",
    "home": "$HOME",
    "shell": "$(getent passwd $(id -un) 2>/dev/null | cut -d: -f7)",
    "groups": $(id -Gn | jq -R 'split(" ")' 2>/dev/null || echo '[]')
  },
  "paths": {
    "knowledge_base": "/mnt/knowledge",
    "sparknet_home": "/mnt/knowledge/.sparknet"
  },
  "constraints": {
    "require_plan_permission_execute": true,
    "deny_root_escalation_attempts": true,
    "unattended_mutations_allowed": false
  }
}
JSON
mv "$OUT.tmp" "$OUT"
