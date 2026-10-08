#!/usr/bin/env bash
# Create a vault's .env and its wiki directory skeleton.
#
# Accepts a role subvault (peer-node/, master-node/) or the fabric root itself.
#
# `.env` is gitignored (it records machine-local paths), so a fresh clone has
# none — and a fresh clone is exactly what a node gets. Without it the wiki
# skills' config resolution walks past the role directory and lands on the
# parent fabric .env, so a peer session quietly writes into the wrong vault.
# See scripts/sparknet-wiki-env.sh for that failure mode in full.
#
# Usage:
#   scripts/sparknet-env-init.sh <role-dir|fabric-root> [--force]
#
# Writes absolute paths derived from <role-dir>, so the result is correct
# wherever the repository is checked out.
set -euo pipefail

# --help before anything resolves a target: without this guard, `--help`
# reached the directory check and exited 1 as "not a directory: --help".
case "${1:-}" in
  -h|--help)
    printf '%s\n' \
      'sparknet-env-init.sh — create a vault'"'"'s .env and wiki directory skeleton' \
      '' \
      'Usage:' \
      '  scripts/sparknet-env-init.sh <role-dir|fabric-root> [--force]' \
      '  scripts/sparknet-env-init.sh --help' \
      '' \
      'With no argument, defaults to the role subvault you are standing in' \
      '(peer-node/, master-node/) or the fabric root. --force overwrites an' \
      'existing .env. Paths written are absolute, so the result is correct' \
      'wherever the repository is checked out.'
    exit 0 ;;
esac

target="${1:-}"
force=0
[ "${2:-}" = "--force" ] && force=1

die() { printf 'sparknet-env-init: %s\n' "$1" >&2; exit 1; }

if [ -z "$target" ]; then
  # Default: whichever role subvault we are standing in.
  case "$PWD" in
    */peer-node|*/master-node) target="$PWD" ;;
    *) [ -f "$PWD/.env.example" ] && [ -d "$PWD/contracts" ] && target="$PWD" \
         || die "pass a vault directory, or run from inside peer-node/, \
master-node/, or the fabric root" ;;
  esac
fi
[ -d "$target" ] || die "not a directory: $target"

target="$(cd "$target" && pwd)"
# The fabric root is a vault in its own right — `opencode sparknet` starts there —
# so it needs a .env and a category skeleton exactly as a role does. Refusing it
# here is what left the root's documented wiki dirs as untracked phantoms that
# exist in a working tree and vanish on a fresh clone.
# Detect the fabric root structurally, never by directory name. The tree must be
# clonable anywhere, so "is this called sparknet/?" is not a question that can be
# asked. A fabric root is the directory that holds contracts/ plus a role.
case "$(basename "$target")" in
  peer-node|master-node)
    role="$(basename "$target")"; is_fabric_root=0 ;;
  *)
    if [ -d "$target/contracts" ] \
       && { [ -f "$target/peer-node/AGENTS.md" ] || [ -f "$target/master-node/AGENTS.md" ]; }; then
      role="fabric"; is_fabric_root=1
    else
      die "expected a role subvault (peer-node/ or master-node/), or the fabric \
root that holds contracts/ and peer-node/ — got: $target"
    fi
    ;;
esac

example="$target/.env.example"
[ -f "$example" ] || die "missing template: $example"

# Derive every path from the checkout location so nothing needs hand-editing.
if [ "$is_fabric_root" -eq 1 ]; then
  fabric_root="$target"
else
  fabric_root="$(dirname "$target")"
fi
raw_dir="$target/_raw"
[ -d "$fabric_root" ] || die "fabric root not found: $fabric_root"
fabric_root="$(cd "$fabric_root" && pwd)"

env_file="$target/.env"
# An .env without VAULT_PATH is treated as absent, not as user intent: a
# truncated or half-written .env is a real failure mode, and honouring it would
# leave the role permanently unresolvable with no indication why.
# An .env whose VAULT_PATH names some *other* directory is not user intent — it is
# a stale file from before the tree moved. Preserving it would leave every wiki
# page aimed at a path that no longer holds this vault, so it is regenerated even
# without --force. The preflight in sparknet-wiki-env.sh would (correctly) refuse to
# run in that state, so "leave it alone" would mean "stay broken".
_stale=""
if [ -f "$env_file" ]; then
  _recorded="$(sed -n 's/^[[:space:]]*VAULT_PATH[[:space:]]*=[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}.*/\1/p' \
               "$env_file" | tail -1)"
  if [ -n "$_recorded" ]; then
    _resolved="$(cd "$_recorded" 2>/dev/null && pwd || true)"
    [ "$_resolved" = "$target" ] || _stale="it names '$_recorded'"
  fi
fi

if [ -n "$_stale" ]; then
  printf 'sparknet-env-init: %s is stale — %s, not this vault. Regenerating.\n' \
    "$env_file" "$_stale"
fi

if [ -f "$env_file" ] && grep -q '^[[:space:]]*VAULT_PATH' "$env_file" \
   && [ "$force" -eq 0 ] && [ -z "$_stale" ]; then
  printf 'sparknet-env-init: %s already configured; leaving it alone.\n' "$env_file"
  printf '  Override with --force to regenerate from %s.\n' "$(basename "$example")"
else
  if [ -f "$env_file" ] && [ "$force" -eq 0 ]; then
    printf 'sparknet-env-init: %s has no VAULT_PATH (empty or truncated); regenerating.\n' "$env_file"
  fi
  # Substitute only the placeholder paths; everything else passes through.
  sed \
    -e "s|^VAULT_PATH=.*|VAULT_PATH=\"$target\"|" \
    -e "s|^VAULT_SOURCES_DIR=.*|VAULT_SOURCES_DIR=\"$raw_dir\"|" \
    "$example" > "$env_file"

  # Verify the write. A silently empty .env is the worst outcome here: it looks
  # configured, resolves nothing, and sends the next session to the wrong vault.
  if ! grep -q '^VAULT_PATH=' "$env_file"; then
    rm -f "$env_file"
    die "generated $env_file without a VAULT_PATH line — removed it; check $example"
  fi

  printf 'sparknet-env-init: wrote %s\n' "$env_file"
  printf '  VAULT_PATH        = %s\n' "$target"
  printf '  VAULT_SOURCES_DIR = %s\n' "$raw_dir"
  printf '  fabric root       = %s\n' "$fabric_root"
fi

# --- wiki directory skeleton ---------------------------------------------------
# The skills expect these to exist. `wiki-setup` creates them for a brand-new
# vault, but a subvault already has content, so it will not be run.
created=0

# Keep empty dirs in git so a fresh clone is already a valid vault.
_ensure_dir() {
  if [ ! -d "$target/$1" ]; then
    mkdir -p "$target/$1"
    created=$((created + 1))
  fi
  [ -f "$target/$1/.gitkeep" ] || : > "$target/$1/.gitkeep"
}

# Role vaults carry the numbered PARA layout; the wiki skills and the old
# charter still name the category dirs, so each category name is a symlink to
# its numbered home. A symlink already there is a no-op. A *real* file or dir
# under a category name is pre-restructure content — rewriting it as a symlink
# would hide it, so it is left alone and reported for a manual migration.
_ensure_shim() {
  if [ -L "$target/$1" ]; then
    return 0
  fi
  if [ -e "$target/$1" ]; then
    printf 'sparknet-env-init: %s is a real path, not a shim — left as is; move it to %s yourself\n' \
      "$1" "$2" >&2
    return 0
  fi
  ln -s "$2" "$target/$1"
  created=$((created + 1))
}

if [ "$is_fabric_root" -eq 1 ]; then
  # The fabric root keeps the wiki category layout as-is.
  for dir in concepts entities skills references synthesis journal projects \
             _raw _staging _archives sessions; do
    _ensure_dir "$dir"
  done
else
  # Role subvaults: the numbered layout, plus shims for every legacy name.
  for dir in 00_System 01_Inbox 02_Daily 03_Sources 04_Evergreen \
             05_Knowledge 05_Knowledge/concepts 05_Knowledge/entities \
             05_Knowledge/skills 05_Knowledge/synthesis 06_Projects \
             07_Archives _staging; do
    _ensure_dir "$dir"
  done
  _ensure_shim concepts 05_Knowledge/concepts
  _ensure_shim entities 05_Knowledge/entities
  _ensure_shim skills 05_Knowledge/skills
  _ensure_shim synthesis 05_Knowledge/synthesis
  _ensure_shim journal 02_Daily
  _ensure_shim sessions 02_Daily
  _ensure_shim references 03_Sources
  _ensure_shim _raw 03_Sources
  _ensure_shim projects 06_Projects
  _ensure_shim _archives 07_Archives
  # index.md and log.md move into 00_System/ only when there is content to
  # move; until then there is nothing to shim.
  if [ -f "$target/00_System/index.md" ]; then
    _ensure_shim index.md 00_System/index.md
  fi
  if [ -f "$target/00_System/log.md" ]; then
    _ensure_shim log.md 00_System/log.md
  fi
fi
printf 'sparknet-env-init: wiki dirs ready (%d created)\n' "$created"

# --- prove the skills will resolve to this vault ------------------------------
if bash -c "cd '$target' && source '$fabric_root/scripts/sparknet-wiki-env.sh'" >/dev/null; then
  printf 'sparknet-env-init: wiki preflight passes for role %s\n' "$role"
else
  printf 'sparknet-env-init: WARNING — wiki preflight did not pass; run it directly:\n' >&2
  printf '  cd %s && source %s/scripts/sparknet-wiki-env.sh\n' "$target" "$fabric_root" >&2
  exit 1
fi

printf '\nNext: cd %s && make validate\n' "$target"