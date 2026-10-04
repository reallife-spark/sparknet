#!/usr/bin/env bash
# Vault/path/venv-agnostic environment setup.
# Roots are derived from this file's own location, so the vault is relocatable.
# Any value can still be overridden from the environment.
set -euo pipefail

SPARKNET_ENV_SELF="${BASH_SOURCE[0]}"
SPARKNET_SCRIPTS_DIR="$(cd "$(dirname "$SPARKNET_ENV_SELF")" && pwd)"
SPARKNET_VAULT_ROOT="${SPARKNET_VAULT_ROOT:-$(dirname "$SPARKNET_SCRIPTS_DIR")}"
SPARKNET_KNOWLEDGE_ROOT="${SPARKNET_KNOWLEDGE_ROOT:-$(dirname "$SPARKNET_VAULT_ROOT")}"
VAULT_PATH="${VAULT_PATH:-$SPARKNET_VAULT_ROOT}"

# Runtime state stays inside the vault unless overridden.
SPARKNET_STATE_DIR="${SPARKNET_STATE_DIR:-$SPARKNET_VAULT_ROOT/.state}"
SPARKNET_CACHE_DIR="${SPARKNET_CACHE_DIR:-$SPARKNET_VAULT_ROOT/.cache}"

# Default XDG dirs inside the vault so nothing leaks onto the host. A pre-existing
# XDG_* in the environment still wins — that is a deliberate host-level setting.
XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$SPARKNET_VAULT_ROOT/.state/config}"
XDG_DATA_HOME="${XDG_DATA_HOME:-$SPARKNET_VAULT_ROOT/.state/share}"
XDG_STATE_HOME="${XDG_STATE_HOME:-$SPARKNET_VAULT_ROOT/.state}"

export SPARKNET_VAULT_ROOT SPARKNET_KNOWLEDGE_ROOT VAULT_PATH
export SPARKNET_STATE_DIR SPARKNET_CACHE_DIR
export XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME
