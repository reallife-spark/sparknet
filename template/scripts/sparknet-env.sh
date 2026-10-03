#!/usr/bin/env bash
# Vault/path/venv-agnostic environment setup
set -euo pipefail

SPARKNET_KNOWLEDGE_ROOT=${SPARKNET_KNOWLEDGE_ROOT:-/mnt/knowledge}
SPARKNET_VAULT_ROOT=${SPARKNET_VAULT_ROOT:-/mnt/knowledge/sparknet}
VAULT_PATH=${VAULT_PATH:-$SPARKNET_VAULT_ROOT}
XDG_CONFIG_HOME=${XDG_CONFIG_HOME:-/mnt/knowledge/.config}
XDG_DATA_HOME=${XDG_DATA_HOME:-/mnt/knowledge/.local/share}
XDG_STATE_HOME=${XDG_STATE_HOME:-/mnt/knowledge/.local/state}

export SPARKNET_KNOWLEDGE_ROOT SPARKNET_VAULT_ROOT VAULT_PATH
export XDG_CONFIG_HOME XDG_DATA_HOME XDG_STATE_HOME
