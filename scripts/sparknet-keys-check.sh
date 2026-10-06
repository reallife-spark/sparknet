#!/usr/bin/env bash
# No key material may be tracked, and no key on disk may be readable by others.
#
# Three lines of defence, all cheap enough to run before every commit:
#
#   1. a tracked file whose *name* looks like a key (`*.ed25519`, `privkey*`, …)
#   2. a tracked file containing a PEM private-key block
#   3. a key under .state/keys/ that is looser than 0600 (its directory than 0700)
#
# plus a check that the .gitignore backstop is still there — a pattern deleted
# from .gitignore is silent until someone commits a key by accident.
#
# Usage: scripts/sparknet-keys-check.sh [dir ...]
#   no args  → the whole repository
#   with args → each directory, standalone (works in an extracted bundle, which
#               ships without .git and is therefore scanned on disk)
set -euo pipefail

PATTERN='(\.ed25519|\.pem|\.key|\.seed)$|(^|/)privkey|(^|/)id_ed25519'
REQUIRED_PATTERNS=('*.ed25519' '*.pem' '*.key' 'privkey*' 'id_ed25519*' '*.seed')
# On-disk fallback only (a bundle has no .git): skip places where a key-shaped
# name is either not content or is the key store itself — .state/keys is
# *meant* to hold private keys and is checked by mode below, not by name.
EXCLUDE='(^|/)(\.git|\.venv|\.state|\.cache|node_modules|dist|__pycache__|\.pytest_cache|\.ruff_cache|\.mypy_cache|\.trash)/'

fail=0
problems=()

note_problem() {
  problems+=("$1")
  fail=1
}

list_files() {
  # Tracked when this is a work tree — "tracked" is the guarantee being made.
  # A bundle has no .git, so there the whole tree is the subject.
  local dir="$1"
  if git -C "$dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    git -C "$dir" ls-files -z | tr '\0' '\n'
  else
    (cd "$dir" && find . -type f | sed 's|^\./||' | grep -Ev "$EXCLUDE" || true)
  fi
}

check_dir() {
  local dir="$1"
  [ -d "$dir" ] || { note_problem "not a directory: $dir"; return; }
  dir="$(cd "$dir" && pwd)"

  local files
  files="$(list_files "$dir")"

  # 1. names
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    if printf '%s\n' "$path" | grep -Eq "$PATTERN"; then
      note_problem "$dir: tracked file looks like key material: $path"
    fi
  done <<< "$files"

  # 2. PEM blocks in tracked content
  if command -v grep >/dev/null 2>&1; then
    local matched
    matched="$(printf '%s\n' "$files" \
      | sed "s|^|$dir/|" \
      | while IFS= read -r f; do
          [ -f "$f" ] || continue
          if grep -qsE -- '-----BEGIN [A-Z ]*PRIVATE KEY-----' "$f"; then
            printf '%s\n' "${f#"$dir"/}"
          fi
        done)"
    if [ -n "$matched" ]; then
      while IFS= read -r m; do
        note_problem "$dir: tracked file contains a private key block: $m"
      done <<< "$matched"
    fi
  fi

  # 3. the .gitignore backstop
  if [ -f "$dir/.gitignore" ]; then
    local want
    for want in "${REQUIRED_PATTERNS[@]}"; do
      if ! grep -qxF -- "$want" "$dir/.gitignore"; then
        note_problem "$dir/.gitignore does not block $want"
      fi
    done
  fi

  # 4. loose keys on disk
  local key
  if [ -d "$dir/.state" ]; then
    local smode
    smode="$(stat -c '%a' "$dir/.state" 2>/dev/null || stat -f '%Lp' "$dir/.state")"
    case "$smode" in
      700|500) : ;;
      *) note_problem "$dir/.state is mode $smode, not 0700" ;;
    esac
  fi
  if [ -d "$dir/.state/keys" ]; then
    while IFS= read -r key; do
      [ -n "$key" ] || continue
      local mode
      mode="$(stat -c '%a' "$key" 2>/dev/null || stat -f '%Lp' "$key")"
      case "$mode" in
        600|400) : ;;
        *) note_problem "$key is mode $mode, not 0600" ;;
      esac
    done < <(find "$dir/.state/keys" -type f 2>/dev/null)
    local dmode
    dmode="$(stat -c '%a' "$dir/.state/keys" 2>/dev/null || stat -f '%Lp' "$dir/.state/keys")"
    case "$dmode" in
      700|500) : ;;
      *) note_problem "$dir/.state/keys is mode $dmode, not 0700" ;;
    esac
  fi
}

if [ "$#" -eq 0 ]; then
  if root="$(git rev-parse --show-toplevel 2>/dev/null)"; then
    check_dir "$root"
  else
    check_dir "$PWD"
  fi
else
  for target in "$@"; do
    check_dir "$target"
  done
fi

if [ "$fail" -ne 0 ]; then
  printf 'keys-check: FAILED\n' >&2
  for p in "${problems[@]}"; do
    printf '  %s\n' "$p" >&2
  done
  exit 1
fi
printf 'keys-check: clean (no key-shaped names, no PEM blocks, .gitignore backstop present)\n'
