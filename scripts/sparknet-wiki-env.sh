#!/usr/bin/env bash
# Resolve the wiki vault for a sparknet role, and refuse to guess.
#
# The vendored wiki skills resolve their vault with the Config Resolution
# Protocol (llm-wiki/SKILL.md): walk up from $PWD for a .env containing
# VAULT_PATH, else fall back to ~/.wiki/config.
#
# That fallback is the danger. `.env` is gitignored, so a fresh clone has no role
# `.env`, resolution walks past the role directory, and the first `.env` it
# finds is the PARENT fabric vault. A peer session then silently distils peer
# knowledge into the fabric vault — no error, no warning, just knowledge filed
# in the wrong place. Worse on a node, where ~/.wiki/config may name a different
# vault entirely.
#
# So: source this, then check the exit status. It prints the resolved vault and
# the role on success, and fails loudly otherwise. Sourced rather than executed,
# so a Makefile target can `source` it and keep the exports.
#
# Usage:
#   source scripts/sparknet-wiki-env.sh          # from a role subvault
#   SPARKNET_ALLOW_ANY_VAULT=1 source ...         # override, for repo tooling
#
# Exported: SPARKNET_ROLE, SPARKNET_VAULT_ROOT, VAULT_PATH, VAULT_LINK_FORMAT,
#           WIKI_STAGED_WRITES, SPARKNET_WIKI_ENV_FILE

set -euo pipefail

# This script is sourced, not executed — the whole point is that its exports
# reach the caller. Guard the direct-execution path anyway, so `--help` is
# answered instead of the resolver running for a caller that would throw the
# result away, and so a bare execution says what to do rather than half-running.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  case "${1:-}" in
    -h|--help)
      cat <<'USAGE'
sparknet-wiki-env.sh — resolve the wiki vault for a sparknet role (source it)

Usage:
  source scripts/sparknet-wiki-env.sh           # from a role subvault
  scripts/sparknet-wiki-env.sh --help            # print this text (direct run)
  SPARKNET_ALLOW_ANY_VAULT=1 source ...          # override, for repo tooling

Exports: SPARKNET_ROLE, SPARKNET_VAULT_ROOT, VAULT_PATH, VAULT_LINK_FORMAT,
         WIKI_STAGED_WRITES, SPARKNET_WIKI_ENV_FILE

Fails loudly (exit 1) when the role .env is missing, because the skills'
fallback (~/.wiki/config) would file knowledge into the wrong vault.
USAGE
      exit 0 ;;
    *)
      printf 'sparknet-wiki-env: this script is sourced, not executed.\n' >&2
      printf 'Use:  source scripts/sparknet-wiki-env.sh\n' >&2
      printf 'Or:   scripts/sparknet-wiki-env.sh --help\n' >&2
      exit 2 ;;
  esac
fi

_wiki_env_die() {
  printf '\nsparknet wiki preflight FAILED: %s\n\n' "$1" >&2
  printf 'The vendored wiki skills pick their vault by walking up from $PWD for a\n' >&2
  printf '.env containing VAULT_PATH, then fall back to ~/.wiki/config. If the role\n' >&2
  printf '.env is missing, that fallback points at the wrong vault and a session\n' >&2
  printf 'would file knowledge into the wrong place without complaining.\n\n' >&2
  printf 'Fix:  make env-init        (writes this role'"'"'s .env from .env.example)\n' >&2
  printf 'Then: re-run your wiki command.\n' >&2
  exit 1
}

# --- 1. Find the role root ----------------------------------------------------
# Two shapes are legal: a session inside a role subvault, or a session at the
# fabric root working across both. Anything else is a misconfigured checkout.
_role_root=""
_fabric_root=""
_dir="$PWD"
while [ "$_dir" != "/" ] && [ -n "$_dir" ]; do
  case "$(basename "$_dir")" in
    peer-node|master-node)
      if [ -f "$_dir/AGENTS.md" ]; then
        _role_root="$_dir"
        break
      fi
      ;;
  esac
  if [ -f "$_dir/peer-node/AGENTS.md" ] || [ -f "$_dir/master-node/AGENTS.md" ]; then
    _fabric_root="$_dir"
  fi
  _dir="$(dirname "$_dir")"
done

if [ -z "$_role_root" ] && [ -n "$_fabric_root" ]; then
  # At the fabric root: there is no role subvault to scope to, so allow whatever
  # .env applies — that is the intended cross-cutting session.
  SPARKNET_ROLE="fabric"
  SPARKNET_VAULT_ROOT="$_fabric_root"
  _expected_env="$_fabric_root/.env"
else
  [ -n "$_role_root" ] || _wiki_env_die \
    "no sparknet role subvault found at or above $PWD.
    Expected to be inside peer-node/ or master-node/, or at the fabric root that
    contains them."

  case "$_role_root" in
    */peer-node)   SPARKNET_ROLE="peer" ;;
    */master-node) SPARKNET_ROLE="master" ;;
    *) _wiki_env_die "unexpected role subvault name: $_role_root" ;;
  esac
  SPARKNET_VAULT_ROOT="$_role_root"
  _expected_env="${_role_root}/.env"
fi

# --- 2. Locate the .env that claims to configure this role ---------------------
# Stop at $HOME, exactly like the Config Resolution Protocol does, so we
# diagnose the same resolution the skills will perform.
_env_file=""
_dir="$PWD"
while [ "$_dir" != "$HOME" ] && [ "$_dir" != "/" ]; do
  if [ -f "$_dir/.env" ] && grep -q '^[[:space:]]*VAULT_PATH' "$_dir/.env"; then
    _env_file="$_dir/.env"
    break
  fi
  _dir="$(dirname "$_dir")"
done

# --- 3. A vault must have its OWN .env, not an inherited one --------------------
# This is the check that closes the trap: if the winning .env belongs to some
# other directory, this session is not pointed at the vault it should be writing.
#
# NOTE: _expected_env was already set per-shape in step 1 (the role subvault's own
# .env, or the fabric root's). It must not be recomputed from _role_root here:
# at the fabric root _role_root is empty, and doing so compared the resolved .env
# against /.env, failing a session that was in fact configured correctly.

if [ -z "$_env_file" ]; then
  _wiki_env_die \
    "no .env with VAULT_PATH found from $PWD up to \$HOME.
    Expected: $_expected_env
    Nothing will resolve correctly until that file exists — and without it the
    skills would fall back to ~/.wiki/config, which is a different vault."
fi

if [ "$_env_file" != "$_expected_env" ]; then
  if [ -z "${SPARKNET_ALLOW_ANY_VAULT:-}" ]; then
    _wiki_env_die \
      "the nearest .env is $_env_file, but this session's vault is
    the $SPARKNET_ROLE vault at $SPARKNET_VAULT_ROOT.
    Skills would resolve VAULT_PATH to that other vault and file this session's
    knowledge there. Run 'make env-init' in $SPARKNET_VAULT_ROOT, or set
    SPARKNET_ALLOW_ANY_VAULT=1 if you really mean to target it."
  fi
fi

# --- 4. Read the config out of the .env ---------------------------------------
# The path is resolved at run time, so shellcheck cannot follow it (SC1090);
# note the directive has to sit on the sourcing line itself — above a
# `a; b; c` line it would only cover `a`.
set -a
# shellcheck disable=SC1090
. "$_env_file"
set +a

SPARKNET_WIKI_ENV_FILE="$_env_file"
: "${VAULT_PATH:=$SPARKNET_VAULT_ROOT}"
: "${VAULT_LINK_FORMAT:=wikilink}"
: "${WIKI_STAGED_WRITES:=false}"

# --- 5. The vault it names must be this role's own directory ------------------
if [ "${SPARKNET_ALLOW_ANY_VAULT:-}" = "" ]; then
  case "$(cd "$VAULT_PATH" 2>/dev/null && pwd || true)" in
    "$SPARKNET_VAULT_ROOT") : ;;
    *) _wiki_env_die \
         "VAULT_PATH in $_env_file resolves to '${VAULT_PATH}', not the
    $SPARKNET_ROLE vault ($SPARKNET_VAULT_ROOT).
    Every page written this session would land in the wrong vault." ;;
  esac
fi

[ -d "$VAULT_PATH" ] || _wiki_env_die "VAULT_PATH '$VAULT_PATH' is not a directory"

printf 'sparknet wiki preflight OK\n'
printf '  role         : %s\n' "$SPARKNET_ROLE"
printf '  role root    : %s\n' "$SPARKNET_VAULT_ROOT"
printf '  VAULT_PATH   : %s\n' "$VAULT_PATH"
printf '  config       : %s\n' "$SPARKNET_WIKI_ENV_FILE"
printf '  link format  : %s\n' "$VAULT_LINK_FORMAT"
printf '  staged writes: %s\n' "$WIKI_STAGED_WRITES"