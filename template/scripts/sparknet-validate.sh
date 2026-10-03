#!/usr/bin/env bash
# Validate sparknet node template environment
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/sparknet-env.sh"

echo "=== Sparknet Node Template Validation ==="
echo "Vault root: $SPARKNET_VAULT_ROOT"
echo "Knowledge root: $SPARKNET_KNOWLEDGE_ROOT"
[ -f "$SPARKNET_VAULT_ROOT/manifests/user-env-manifest.json" ] && echo "✓ user-env-manifest.json exists" || echo "✗ missing"
[ -x "$SCRIPT_DIR/sparknet-identity-capture.sh" ] && echo "✓ identity capture executable" || echo "✗"
echo "=== Done ==="
