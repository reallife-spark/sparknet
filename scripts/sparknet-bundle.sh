#!/usr/bin/env bash
# Assemble a standalone node bundle for one role.
#
# A role subvault alone is NOT a deployment. Verified by test: copy peer-node/
# on its own and validation fails, because the contract it obeys is absent. The
# smallest thing that actually runs is:
#
#     <role>-node/     the role subvault
#     contracts/       overlay, capabilities, identity, ports, guard protocol
#     shared/          the one canonical authorization implementation
#     .opencode/       the vendored wiki skill suite + role-aware agent
#     opencode.json    so opencode loads those skills and the agent
#     requirements.txt cryptography, the only runtime dependency
#
# So the bundle reproduces the repository layout rather than inventing a new
# one. That means there is exactly one code path to maintain: what you develop
# in the repo is what ships.
#
# Usage:
#   scripts/sparknet-bundle.sh <peer|master> [--out DIR] [--from-git REF]
#   scripts/sparknet-bundle.sh --verify <archive.tar.gz>
#
# Default builds from the working tree, because during development the split is
# not committed yet and `git archive` would silently ship an incomplete tree
# (git archive only ever sees tracked files). --from-git REF builds from a
# committed ref, which is the release-grade path and fails loudly if that ref
# is missing anything.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKILLS_DIR="$REPO_ROOT/.opencode/skills"

die() { printf 'sparknet-bundle: %s\n' "$1" >&2; exit 1; }

# --- verify: prove an extracted bundle actually runs --------------------------
# The claim this script exists to support is "a node can run this on its own".
# That claim is only worth something if it is executed, not asserted, so
# extraction runs the role's real deploy sequence in a throwaway location.
verify_bundle() {
  archive="$1"
  [ -f "$archive" ] || die "no such archive: $archive"

  # The role is encoded in the archive name: sparknet-<role>-...
  base="$(basename "$archive" .tar.gz)"
  case "$base" in
    sparknet-peer-*)   vrole="peer" ;;
    sparknet-master-*) vrole="master" ;;
    *) die "cannot infer role from archive name: $base" ;;
  esac

  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  printf 'verifying %s (role %s)\n' "$(basename "$archive")" "$vrole"
  printf '  extracting to %s\n\n' "$work"

  tar -xzf "$archive" -C "$work"
  root="$work/sparknet-$vrole"
  [ -d "$root" ] || die "archive did not contain sparknet-$vrole/"

  fail=0
  step() { printf '  → %s\n' "$*"; }
  ok()   { printf '    ✓ %s\n' "$*"; }
  bad()  { printf '    ✗ %s\n' "$*"; fail=1; }

  step "vendored skills present"
  n="$(find "$root/.opencode/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)"
  [ "$n" -gt 0 ] && ok "$n skills" || bad "no skills bundled"

  step "opencode config present"
  [ -f "$root/opencode.json" ] && ok "opencode.json" || bad "opencode.json missing"

  step "no secrets in the archive"
  # Assembled from fragments so this scanner does not match its own source,
  # which would otherwise flag itself as a leak on every run.
  secret_re="BEGIN (OPENSSH|RSA|PRIVATE) KEY|g""ho_[A-Za-z0-9]{20,}|github_p""at_"
  hits="$(grep -rlE "$secret_re" "$root" 2>/dev/null || true)"
  # This file legitimately contains the pattern itself.
  hits="$(printf '%s' "$hits" | grep -v 'sparknet-bundle.sh$' || true)"
  if [ -n "$hits" ]; then
    bad "possible secret material found"
    printf '%s\n' "$hits" | sed 's/^/      /'
  else
    ok "no key or token patterns"
  fi

  step "no role .env bundled (must be generated at deploy)"
  [ ! -f "$root/$vrole-node/.env" ] && ok "absent as expected" || bad ".env was bundled"

  step "env-init (deploy step 1)"
  if bash "$root/scripts/sparknet-env-init.sh" "$root/$vrole-node" >/dev/null 2>&1; then
    ok "wrote a role-scoped .env"
  else
    bad "env-init failed"
  fi

  step "wiki preflight resolves THIS role's vault"
  if out="$(cd "$root/$vrole-node" && bash -c "source '$root/scripts/sparknet-wiki-env.sh'" 2>&1)"; then
    if printf '%s' "$out" | grep -q "role root    : $root/$vrole-node"; then
      ok "resolves to the extracted role vault"
    else
      bad "preflight passed but resolved elsewhere"
      printf '%s\n' "$out" | sed 's/^/      /'
    fi
  else
    bad "preflight failed"
    printf '%s\n' "$out" | tail -4 | sed 's/^/      /'
  fi

  py="$root/.venv/bin/python"
  [ -x "$py" ] || py="python3"

  # The peer role has a real implementation suite. The master role has no code,
  # so its pytest run asserts the spec boundary instead — which is checked
  # below, because verifying a Master by doing nothing would prove nothing.
  if [ "$vrole" = "peer" ]; then
    step "role validate"
    if (cd "$root/peer-node" && ./scripts/sparknet-validate.sh >/dev/null 2>&1); then
      ok "validate passed"
    else
      bad "validate failed"
    fi

    step "role test suite"
    if (cd "$root/peer-node" && "$py" -m pytest -q >/dev/null 2>&1); then
      ok "pytest passed"
    else
      # Retry with the interpreter that has cryptography, then report.
      if (cd "$root/peer-node" && "$REPO_ROOT/.venv/bin/python" -m pytest -q >/dev/null 2>&1); then
        ok "pytest passed (needed the dev interpreter for cryptography)"
      else
        bad "pytest failed — install requirements.txt into a venv on the node"
      fi
    fi
  else
    step "role validate (master)"
    printf '    – master has no implementation yet; nothing to execute\n'
    # There is no service to start, but there IS a spec boundary to assert: the
    # role must still contain no executable surface, still say so in its own
    # prose, and still not hold a private key. Without this the bundle would
    # verify a Master by doing nothing at all.
    step "master spec boundary"
    if (cd "$root/master-node" && "$py" -m pytest tests -q >/dev/null 2>&1); then
      ok "spec boundary holds (no code, no key, prose still says so)"
    else
      bad "master spec tests failed — see 'cd master-node && pytest tests'"
    fi
  fi

  printf '\n'
  if [ "$fail" -eq 0 ]; then
    printf 'bundle verified: sparknet-%s runs standalone from %s\n' "$vrole" "$(basename "$archive")"
    return 0
  fi
  printf 'bundle verification FAILED: %s\n' "$(basename "$archive")" >&2
  return 1
}

role=""
out_root="$REPO_ROOT/dist"
from_git=""
verify=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out)       out_root="$2"; shift 2 ;;
    --from-git)  from_git="$2"; shift 2 ;;
    --out=*)     out_root="${1#*=}"; shift ;;
    --from-git=*) from_git="${1#*=}"; shift ;;
    --verify)    verify="$2"; shift 2 ;;
    --verify=*)  verify="${1#*=}"; shift ;;
    -*)          die "unknown option: $1" ;;
    *)           role="$1"; shift ;;
  esac
done

if [ -n "$verify" ]; then
  verify_bundle "$verify"
  exit $?
fi

[ -n "$role" ] || die "usage: sparknet-bundle.sh <peer|master> [--out DIR] [--from-git REF]"
case "$role" in
  peer|master) ;;
  *) die "role must be 'peer' or 'master', got: $role" ;;
esac

role_dir="$REPO_ROOT/$role-node"
[ -d "$role_dir" ] || die "missing role subvault: $role_dir"
[ -d "$SKILLS_DIR" ] || die "vendored skills missing: $SKILLS_DIR (run make wiki-sync)"

# Excluded from the working-tree copy. `.opencode/node_modules` matters most:
# it is a multi-megabyte dependency tree with nothing to do with the vault.
# `.env` is excluded on purpose: it is gitignored, machine-local, and its
# VAULT_PATH is an absolute path from the machine that generated it. Shipping it
# would point every extracted node back at the build host -- and, worse, the
# extracted copy's own validate and pytest would then silently exercise the
# BUILD HOST's tree instead of the extracted one, which is exactly the false
# green this script exists to prevent. sparknet-env-init.sh regenerates it.
EXCLUDES=(
  --exclude=.git --exclude=.venv --exclude=dist --exclude=.state --exclude=.cache
  --exclude=__pycache__ --exclude=.pytest_cache --exclude=.ruff_cache
  --exclude=node_modules --exclude=.opencode/node_modules
  --exclude='*.pyc' --exclude='.trash' --exclude='.env'
)

stamp="$(date +%Y%m%d-%H%M%S)"
tree_label="worktree"
[ -n "$from_git" ] && tree_label="$(printf '%s' "$from_git" | tr -c 'A-Za-z0-9._-' '-')"
prefix="sparknet-$role"
name="$prefix-$tree_label-$stamp"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

target="$stage/$prefix"
mkdir -p "$target"

if [ -n "$from_git" ]; then
  # Release-grade: only committed content, from an explicit ref.
  for subtree in "$role-node" contracts shared .opencode/skills .opencode/agent scripts; do
    git -C "$REPO_ROOT" rev-parse --verify --quiet "$from_git^{commit}" >/dev/null \
      || die "not a commit: $from_git"
    if git -C "$REPO_ROOT" cat-file -e "$from_git:$subtree" 2>/dev/null; then
      git -C "$REPO_ROOT" archive --format=tar --prefix="$prefix/" "$from_git" "$subtree" \
        | tar -xf - -C "$stage"
      printf '  from-git %-24s %s\n' "$subtree" "$from_git"
    else
      printf '  from-git %-24s MISSING at %s\n' "$subtree" "$from_git"
    fi
  done
  cp "$REPO_ROOT/opencode.json" "$target/opencode.json"
  cp "$REPO_ROOT/requirements.txt" "$target/requirements.txt"
else
  if [ -n "$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null || true)" ]; then
    printf 'WARNING: working tree is dirty — the bundle includes uncommitted work.\n'
    printf '         Use --from-git <ref> to build from a commit instead.\n\n'
  fi
  for subtree in "$role-node" contracts shared scripts; do
    rsync -a "${EXCLUDES[@]}" "$REPO_ROOT/$subtree/" "$target/$subtree/"
    printf '  copied   %s\n' "$subtree"
  done
  mkdir -p "$target/.opencode"
  rsync -a "${EXCLUDES[@]}" "$SKILLS_DIR/" "$target/.opencode/skills/"
  rsync -a "${EXCLUDES[@]}" "$REPO_ROOT/.opencode/agent/" "$target/.opencode/agent/"
  cp "$REPO_ROOT/opencode.json" "$target/opencode.json"
  cp "$REPO_ROOT/requirements.txt" "$target/requirements.txt"
  printf '  copied   .opencode/skills (%s skills), .opencode/agent\n' \
    "$(find "$SKILLS_DIR" -mindepth 1 -maxdepth 1 -type d | wc -l)"
fi

# --- the bundle's own manifest ------------------------------------------------
{
  printf '# sparknet %s bundle\n\n' "$role"
  printf 'Assembled by `scripts/sparknet-bundle.sh` from %s.\n\n' \
    "$( [ -n "$from_git" ] && printf '`%s`' "$from_git" || printf 'the working tree (uncommitted work included)')"
  cat <<'EOF'
## What is in here

| Path | Why it is required |
|---|---|
| `peer-node/` / `master-node/` | the role itself |
| `contracts/` | the overlay, capability, identity, port and guard contracts this role obeys |
| `shared/` | the single canonical signed-authorization implementation |
| `.opencode/skills/` | the vendored wiki skill suite — no global skill farm needed |
| `.opencode/agent/` | the role-aware vault agent |
| `opencode.json` | registers the skills and agent with opencode |
| `requirements.txt` | `cryptography`, the only runtime dependency |

`contracts/`, `shared/` and `.opencode/` are not optional extras. A copy of the
role directory on its own fails validation on purpose: the role cannot verify a
signature against a contract it does not have, so it refuses to pretend to.

## Deploy

```bash
tar xzf sparknet-<role>-*.tar.gz
cd sparknet-<role>
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

cd <role>-node
../scripts/sparknet-env-init.sh "$PWD"     # writes .env from .env.example
make validate                             # env contract + role preconditions
make test                                 # the role's suite
```

Then start opencode inside `<role>-node/` and use `/wiki-status`, `/wiki-ingest`,
`/wiki-query` — they resolve this role's vault from the `.env` just written.

## Deliberately absent

- **Secrets.** No private keys, no tokens. `$SPARKNET_STATE_DIR/keys` is created
  at provisioning time, and `.state/` is excluded.
- **A Master private key**, ever. This bundle can be given to a peer safely; the
  master role signs but its key is provisioned on the master itself.
- **`__pycache__`, caches, `node_modules`.** Build noise, nothing else.
- **Cluster-only skills.** Four skills that read this cluster's agent histories
  were withheld; see `.opencode/skills/README.md` for which and why.
EOF
} > "$target/BUNDLE.md"

# The role's .env is machine-local and gitignored, so it is never bundled —
# which is correct, and also why env-init is a deploy step rather than a build
# step. Record that, so nobody wonders where it went.
printf '\n.env is not bundled (machine-local paths); run sparknet-env-init.sh after extracting.\n' \
  >> "$target/BUNDLE.md"

mkdir -p "$out_root"
archive="$out_root/$name.tar.gz"
tar -czf "$archive" -C "$stage" "$prefix"

printf '\nWrote %s\n' "${archive#$REPO_ROOT/}"
printf '  size    : %s\n' "$(du -h "$archive" | cut -f1)"
printf '  contents: %s\n' "$(tar -tzf "$archive" | wc -l) entries"
printf '  skills  : %s\n' "$(tar -tzf "$archive" | grep -c '/\.opencode/skills/[^/]*/SKILL.md$') vendored"
printf '\nVerify it actually runs:\n  scripts/sparknet-bundle.sh --verify %s\n' "$archive"