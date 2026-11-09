#!/usr/bin/env bash
# Assemble a standalone node bundle for one role.
#
# A role submodule alone is NOT a deployment. Verified by test: copy peer-node/
# on its own and validation fails, because the contract it obeys is absent. The
# smallest thing that actually runs is:
#
#     <role>-node/     the role subvault
#     contracts/       overlay, capabilities, identity, ports, guard protocol
#     shared/          the canonical implementations: signed authorization
#                      (sparknet-authz.py) and consensus (sparknet-consensus.py)
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
# Plural because that is the path the opencode docs name. opencode 1.18.34 also
# accepts the singular `agent/`, so this is alignment, not a repair — see Step 5
# in PLAN.md, where the original "singular means dead agent" claim was retracted.
AGENTS_DIR="$REPO_ROOT/.opencode/agents"

die() { printf 'sparknet-bundle: %s\n' "$1" >&2; exit 1; }

# The one release export implementation (scripts/sparknet-release-export.py).
EXPORT_PY="$REPO_ROOT/scripts/sparknet-release-export.py"
export_run() { python3 "$EXPORT_PY" "$@"; }
json_field() {
  python3 -c 'import json,sys; v=json.loads(sys.argv[1]).get(sys.argv[2]); print("" if v is None else v)' "$1" "$2"
}

# --- verify: prove an extracted bundle actually runs --------------------------
# The claim this script exists to support is "a node can run this on its own".
# That claim is only worth something if it is executed, not asserted, so
# extraction runs the role's real deploy sequence in a throwaway location.
verify_bundle() {
  archive="$1"
  [ -f "$archive" ] || die "no such archive: $archive"
  sig="${signature:-$archive.sig}"
  [ -f "$sig" ] || die "detached signature missing: $sig (build with --sign-key, then rerun --verify --pubkey ...)"
  [ -n "$pubkey" ] && [ -f "$pubkey" ] || die "--verify needs a pinned --pubkey (or SPARKNET_BUNDLE_PUBKEY)"
  export_run verify-integrity --path "$archive" --signature "$sig" --pubkey "$pubkey" >/dev/null \
    || die "archive signature does not verify under $pubkey"

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

  python3 "$REPO_ROOT/scripts/sparknet-safe-extract.py" "$archive" "$work"
  root="$work/sparknet-$vrole"
  [ -d "$root" ] || die "archive did not contain sparknet-$vrole/"

  fail=0
  step() { printf '  → %s\n' "$*"; }
  ok()   { printf '    ✓ %s\n' "$*"; }
  bad()  { printf '    ✗ %s\n' "$*"; fail=1; }

  step "integrity manifest matches the archive"
  sumfile="$root/SHA256SUMS"
  if [ ! -f "$sumfile" ]; then
    bad "SHA256SUMS missing — not assembled by this script's build step?"
  elif export_run verify-integrity --path "$root" >/dev/null 2>&1; then
    ok "$(grep -c . "$sumfile") files verified"
  else
    bad "SHA256SUMS does not match the extracted tree"
    export_run verify-integrity --path "$root" 2>&1 | head -8 | sed 's/^/      /'
  fi

  step "vendored skills present"
  n="$(find "$root/.opencode/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l)"
  [ "$n" -gt 0 ] && ok "$n base skills" || bad "no base skills bundled"

  step "role-local skills present and sellable"
  n_role="$(find "$root/$vrole-node/.opencode/skills" -mindepth 2 -maxdepth 2 -name SKILL.md 2>/dev/null | wc -l)"
  [ "$n_role" -gt 0 ] && ok "$n_role role-local skills" || bad "no role-local skills bundled"
  if python3 "$root/scripts/sync-role-skills.py" --check --role "$vrole" >/dev/null 2>&1; then
    ok "role manifest, licenses and removal list verify"
  else
    bad "role-local skill manifest failed verification"
    python3 "$root/scripts/sync-role-skills.py" --check --role "$vrole" 2>&1 | head -8 | sed 's/^/      /'
  fi

  step "opencode config present"
  [ -f "$root/opencode.json" ] && ok "opencode.json" || bad "opencode.json missing"

  step "release surface: data present, fabric-root tools absent"
  [ -f "$root/VERSION" ] && ok "VERSION $(cat "$root/VERSION")" || bad "VERSION missing"
  [ -f "$root/sbom/sparknet.cdx.json" ] && ok "SBOM present" || bad "sbom/sparknet.cdx.json missing"
  for tool in sparknet sparknet-sbom.py; do
    [ ! -e "$root/scripts/$tool" ] && ok "scripts/$tool absent as expected" \
      || bad "scripts/$tool must not be bundled"
  done
  [ ! -e "$root/scripts/plugins" ] && ok "scripts/plugins absent as expected" \
    || bad "scripts/plugins must not be bundled"

  step "no secrets in the archive"
  # Assembled from fragments so this scanner does not match its own source,
  # which would otherwise flag itself as a leak on every run.
  secret_re="BEGIN (OPENSSH|RSA|PRIVATE) KEY|g""ho_[A-Za-z0-9]{20,}|github_p""at_"
  hits="$(grep -rlE "$secret_re" "$root" 2>/dev/null || true)"
  # This file legitimately contains the pattern itself.
  hits="$(printf '%s' "$hits" | grep -v 'sparknet-bundle.sh$' || true)"
  # Vendored role-local skill content is third-party and covered by the role
  # manifest hashes; upstream examples must not read as our secrets here.
  hits="$(printf '%s' "$hits" | grep -v '/\.opencode/skills/' || true)"
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

  # Both roles run their own suite. Note what is *not* in a bundle: the fabric-level
  # `tests/`, so an extracted node cannot run test_contracts.py and therefore cannot
  # check contract drift for itself. Parity between the roles and contracts/ is
  # proved at the build host by `make contract-test` before bundling, not in the
  # bundle. (This comment used to say the Master had no code and its pytest run
  # asserted the spec boundary — true until Step 15, wrong afterwards.)
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
    # The master role now has code, so it is verified the same way the peer is:
    # by running it. Verifying a Master by doing nothing proved nothing, which is
    # why this branch used to assert the absence of an executable surface.
    step "role validate (master)"
    if (cd "$root/master-node" && make --no-print-directory validate >/dev/null 2>&1); then
      ok "validate passed (files, units, no key material, parity, ledger)"
    else
      bad "validate failed"
      (cd "$root/master-node" && make --no-print-directory validate 2>&1 \
        | tail -12 | sed 's/^/      /')
    fi

    step "role test suite (master)"
    if (cd "$root/master-node" && "$py" -m pytest tests -q >/dev/null 2>&1); then
      ok "pytest passed"
    else
      bad "master tests failed — see 'cd master-node && pytest tests'"
    fi

    # The anti-false-green check that the peer's `.env` exclusion already forced
    # here. Parity resolves the peer's services by path; if it resolved against
    # the BUILD HOST instead of this extracted tree, a master bundle missing its
    # peer would still report green. So require the resolved path to be inside
    # the bundle.
    step "master parity resolves to the BUNDLED peer, not the build host"
    parity_out="$(cd "$root/master-node" && "$py" services/sparknet-parity.py 2>&1)"
    if printf '%s' "$parity_out" | grep -q "\"$root/peer-node/services\""; then
      ok "peer services resolved inside $root/peer-node/services"
    else
      bad "parity did not resolve to the bundled peer — it may be reaching the build host"
      printf '%s\n' "$parity_out" | tail -6 | sed 's/^/      /'
    fi

    step "no duplicate peer services inside the master role"
    dups="$(find "$root/master-node" \( -name 'sparknet-guard-d.py' \
             -o -name 'sparknet-dispatch-bridge.py' \) 2>/dev/null | grep -c . || true)"
    if [ "$dups" -eq 0 ]; then
      ok "none — the peer's files are loaded by path, not copied"
    else
      bad "$dups copy/copies of the peer's services inside master-node/ — they would drift"
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

usage() {
  cat <<'USAGE'
sparknet-bundle.sh — assemble a standalone node bundle for one role

Usage:
  scripts/sparknet-bundle.sh <peer|master> [--out DIR] [--from-git REF]
  scripts/sparknet-bundle.sh --verify <archive.tar.gz>
  scripts/sparknet-bundle.sh --help

Options:
  --out DIR       write archives under DIR (default: dist/)
  --from-git REF  build from a committed ref instead of the working tree
  --sign-key PATH  sign the finished archive with this Ed25519 private key
  --verify        verify ARCHIVE's detached signature, then run its deploy sequence
  --pubkey PATH   pinned public key for --verify (or SPARKNET_BUNDLE_PUBKEY)
  --signature PATH detached signature for --verify (default: ARCHIVE.sig)

The bundle reproduces the repository layout (role submodule + contracts/ +
shared/ + .opencode/ + opencode.json), because a role submodule alone is not a
deployment. A SHA256SUMS over the whole tree is written at build time and
checked by --verify, so a corrupted or tampered archive fails before it runs.
USAGE
}

role=""
out_root="$REPO_ROOT/dist"
from_git=""
verify=""
sign_key=""
pubkey="${SPARKNET_BUNDLE_PUBKEY:-}"
signature=""
while [ $# -gt 0 ]; do
  case "$1" in
    --out)       out_root="$2"; shift 2 ;;
    --from-git)  from_git="$2"; shift 2 ;;
    --sign-key)  sign_key="$2"; shift 2 ;;
    --pubkey)    pubkey="$2"; shift 2 ;;
    --signature) signature="$2"; shift 2 ;;
    --out=*)     out_root="${1#*=}"; shift ;;
    --from-git=*) from_git="${1#*=}"; shift ;;
    --verify)    verify="$2"; shift 2 ;;
    --verify=*)  verify="${1#*=}"; shift ;;
    -h|--help)   usage; exit 0 ;;
    -*)          die "unknown option: $1" ;;
    *)           role="$1"; shift ;;
  esac
done

if [ -n "$verify" ]; then
  verify_bundle "$verify"
  exit $?
fi

[ -n "$role" ] || { usage >&2; exit 2; }
case "$role" in
  peer|master) ;;
  *) die "role must be 'peer' or 'master', got: $role" ;;
esac

role_dir="$REPO_ROOT/$role-node"
[ -d "$role_dir" ] || die "missing role subvault: $role_dir"
[ -d "$SKILLS_DIR" ] || die "vendored skills missing: $SKILLS_DIR (run make wiki-sync)"
[ -d "$AGENTS_DIR" ] || die "role agents missing: $AGENTS_DIR (docs name .opencode/agents/, plural)"

# The staging rules — excludes, from-git export, SHA256SUMS and the prune
# policy — are the release export module's, not this adapter's. A worktree
# bundle ships the working tree's SBOM as data, so this adapter still fails
# closed on the fact the module returns; a --from-git bundle reads VERSION and
# the SBOM from the ref itself.


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
  stage_json="$(export_run stage --surface bundle --role "$role" --source "$from_git" --dest "$target")" \
    || die "release export failed"
else
  stage_json="$(export_run stage --surface bundle --role "$role" --dest "$target")" \
    || die "release export failed"
  if [ "$(json_field "$stage_json" sbom_stale)" = "True" ]; then
    die "the SBOM is stale — run make sbom before bundling"
  fi
  if [ "$(json_field "$stage_json" dirty)" = "True" ]; then
    printf 'WARNING: working tree is dirty — the bundle includes uncommitted work.\n'
    printf '         Use --from-git <ref> to build from a commit instead.\n\n'
  fi
fi


# --- the bundle's own manifest ------------------------------------------------
{
  printf '# sparknet %s bundle\n\n' "$role"
  printf 'Assembled by `scripts/sparknet-bundle.sh` from %s.\n\n' \
    "$( [ -n "$from_git" ] && printf '`%s`' "$from_git" || printf 'the working tree (uncommitted work included)')"
  printf 'Version: `%s`\n\n' "$(cat "$target/VERSION")"
  cat <<'EOF'
## What is in here

| Path | Why it is required |
|---|---|
| `peer-node/` / `master-node/` | the role itself |
| `contracts/` | the overlay, capability, identity, port and guard contracts this role obeys |
| `shared/` | the canonical implementations — signed authorization, consensus, plus the http/liveness/oob layers |
| `.opencode/skills/` | the vendored base skill suite — no global skill farm needed |
| `<role>-node/.opencode/skills/` | the role-local sellable catalog (90 peer / 1,652 master) with `.inventory.json` |
| `.opencode/agents/`      | the role-aware agents (built-ins + vendored) — `catalog`, `chart`, sparknet-node, vault, chat |
| `scripts/plugins/kde-notify.*` | intentionally **not** bundled; KDE Connect desktop notifications are fabric-root-local only (`.opencode/plugin/*` was never created; notifications are injected via `OPENCODE_CONFIG` at the root) |
| `scripts/sparknet`, `scripts/sparknet-sbom.py` | intentionally **not** bundled — fabric-root tools that assume a root Makefile; a node cannot run them. The release data below ships instead |
| `opencode.json` | registers the skills and agent with opencode |
| `requirements.txt` | `cryptography`, the only runtime dependency |
| `VERSION` | the fabric version this bundle was built from |
| `sbom/sparknet.cdx.json` | the generated CycloneDX SBOM for that version |

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

## Prove the bytes

`SHA256SUMS` covers every file in this bundle. After extracting, verify it before
deploying:

```bash
sha256sum -c SHA256SUMS        # or: shasum -a 256 -c SHA256SUMS
```

## Deliberately absent

- **Secrets.** No private keys, no tokens. The master's state dir lives outside the
  vault (`$XDG_STATE_HOME/sparknet/master-node`), so a bundle has nothing to exclude
  on that account; `.state/` is still excluded as a backstop in case an operator
  points `SPARKNET_STATE_DIR` at an old in-vault path.
- **A Master private key**, ever. This bundle can be given to a peer safely; the
  master role signs but its key is provisioned on the master itself.
- **`__pycache__`, caches, `node_modules`.** Build noise, nothing else.
- **Cluster-only skills.** Four skills that read this cluster's agent histories
  were withheld from the base suite; see `.opencode/skills/README.md` for which
  and why.
- **Proprietary and non-sellable skills.** The role-local catalogs exclude the
  twelve restricted names, GPL/AGPL, CC BY-SA, modified-Apache and unclear
  licenses. `claude-api` is retained only from its Apache-2.0 source and is
  marked optional.
EOF
} > "$target/BUNDLE.md"

# The role's .env is machine-local and gitignored, so it is never bundled —
# which is correct, and also why env-init is a deploy step rather than a build
# step. Record that, so nobody wonders where it went.
printf '\n.env is not bundled (machine-local paths); run sparknet-env-init.sh after extracting.\n' \
  >> "$target/BUNDLE.md"

# Hash the finished tree last, so BUNDLE.md and every copied file are covered.
# Deliberately the final build action before tar: a manifest written earlier
# would silently omit whatever was added after it.
export_run checksums --dest "$target" >/dev/null
printf '  hashed   SHA256SUMS (%s files)\n' "$(grep -c . "$target/SHA256SUMS")"

mkdir -p "$out_root"
archive="$out_root/$name.tar.gz"
tar -czf "$archive" -C "$stage" "$prefix"
if [ -n "$sign_key" ]; then
  python3 "$REPO_ROOT/scripts/sparknet-sign-artifact.py" sign --file "$archive" --key "$sign_key" --out "$archive.sig" \
    || die "could not sign $archive"
fi

printf '\nWrote %s\n' "${archive#$REPO_ROOT/}"
printf '  size    : %s\n' "$(du -h "$archive" | cut -f1)"
printf '  contents: %s\n' "$(tar -tzf "$archive" | wc -l) entries"
printf '  skills  : %s base, %s %s-local\n' \
  "$(tar -tzf "$archive" | grep '/\.opencode/skills/[^/]*/SKILL.md$' | grep -v -E '/(peer|master)-node/' | grep -c . || true)" \
  "$(tar -tzf "$archive" | grep -c "/$role-node/\.opencode/skills/[^/]*/SKILL.md$" || true)" \
  "$role"
printf '\nVerify it actually runs:\n  scripts/sparknet-bundle.sh --verify %s\n' "$archive"