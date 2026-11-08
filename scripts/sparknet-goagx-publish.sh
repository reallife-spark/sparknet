#!/usr/bin/env bash
# sparknet-goagx-publish.sh — assemble, verify and publish the goagx
# distribution (the standalone AGX Xavier deployment repo, reallife-spark/goagx)
# from this fabric (PLAN Step 62).
#
# The distribution is GENERATED, never hand-edited on the forge side. It
# reproduces the monorepo layout for the subtrees a node needs — the same set
# scripts/sparknet-bundle.sh ships, plus the goagx/ image surface and the root
# glue the image build copies — so every existing code path
# (sparknet-node-setup.sh --platform agx, make -C peer-node dist, the unit
# installers) runs unmodified from a clone of the published repo.
#
# Usage:
#   scripts/sparknet-goagx-publish.sh --out DIR [--from-git REF] [--force]
#   scripts/sparknet-goagx-publish.sh --verify PATH      # staged dir or .tar.gz
#   scripts/sparknet-goagx-publish.sh --push [--from-git REF] [--create]
#   scripts/sparknet-goagx-publish.sh --drift [--from-git REF]
#   scripts/sparknet-goagx-publish.sh --help
#
#   --out      stage the distribution into DIR (must be empty unless --force)
#   --verify   prove a staged tree is complete and internally consistent
#              (integrity manifest, pin files, --help surface, py3.8 shim
#              grammar, compose resolution, no key material) — no network
#   --push     stage, then publish to the goagx repo as one release commit
#   --drift    stage from the tree and diff against the published repo's tip;
#              self-skips with a notice when the private remote cannot be
#              fetched (the codeql pattern) unless SPARKNET_GOAGX_STRICT=1
#   --from-git release-grade: export committed content at REF only
#
# Default source is the working tree (dirty => warned, like the bundle
# script). goSpark's pin lives in goagx/GOSPARK_PIN; VERSIONS.json records
# every pin in the published manifest.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_DEFAULT="https://github.com/reallife-spark/goagx.git"

log()  { printf '\033[1;36m[goagx-publish]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[goagx-publish]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[goagx-publish]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
sparknet-goagx-publish.sh — assemble/verify/publish the goagx distribution.

Usage:
  scripts/sparknet-goagx-publish.sh --out DIR [--from-git REF] [--force]
  scripts/sparknet-goagx-publish.sh --verify PATH
  scripts/sparknet-goagx-publish.sh --push [--from-git REF] [--create]
  scripts/sparknet-goagx-publish.sh --drift [--from-git REF]
  scripts/sparknet-goagx-publish.sh --help

  --out DIR       stage the distribution into DIR (empty unless --force)
  --verify PATH   check a staged dir or .tar.gz; no network needed
  --push          stage and push one release commit to reallife-spark/goagx
  --drift         diff the staged tree against the published tip
  --from-git REF  export committed content at REF (default: working tree)
  --create        with --push: create the repo (gh) if it does not exist
  --force         with --out: allow staging into a non-empty DIR

Env: SPARKNET_GOAGX_REMOTE (default https://github.com/reallife-spark/goagx.git),
SPARKNET_GOAGX_STRICT=1 makes --drift fail instead of self-skipping when the
remote cannot be fetched.
EOF
}

# --- arguments ----------------------------------------------------------------
ACTION=""
OUT=""
FROM_GIT=""
FORCE=0
CREATE=0
VERIFY_PATH=""
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)     usage; exit 0 ;;
    --out)         [ $# -ge 2 ] || die "--out needs a directory"; ACTION="out"; OUT="$2"; shift 2 ;;
    --verify)      [ $# -ge 2 ] || die "--verify needs a path"; ACTION="verify"; VERIFY_PATH="$2"; shift 2 ;;
    --push)        ACTION="push"; shift ;;
    --drift)       ACTION="drift"; shift ;;
    --from-git)    [ $# -ge 2 ] || die "--from-git needs a ref"; FROM_GIT="$2"; shift 2 ;;
    --create)      CREATE=1; shift ;;
    --force)       FORCE=1; shift ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done
[ -n "$ACTION" ] || { usage >&2; exit 2; }

REMOTE="${SPARKNET_GOAGX_REMOTE:-$REMOTE_DEFAULT}"

# --- export surface -----------------------------------------------------------
# The layout a node needs: both role subvaults (a master image runs the peer
# bundle too — services/sparknet-parity.py loads peer services by path), the
# contract + shared implementation the bundle already deems non-optional, the
# fabric scripts the node machinery calls, the vendored wiki suite + agents,
# the goagx image surface, and the root files the image build COPYs or the
# setup script drives.
SUBTREES=(peer-node master-node contracts shared scripts .opencode/skills .opencode/agents goagx sbom)
# Root files the image build or the node flow names. spark.docker and
# spark.compose.yml stay: the setup script's default platform IS spark, and a
# distribution shipping half the platform pair fails the moment it runs bare.
# .env.example is what env-init copies into every role vault.
# USER_MANUAL.md is the fabric's master manual: the goagx distribution is a
# mirror of the fabric, so it carries the manual that describes the mirror.
ROOT_FILES=(
  spark-entrypoint.sh spark-precontext.py spark.compose.cpu.yml
  torch-dist-l4t-compat.py spark-vllm-l4t-patch.py spark-vllm-xformers-gqa-patch.py
  sparknet-node-setup.sh bootstrap-agx.sh
  spark.docker spark.compose.yml
  .env.example
  .dockerignore .gitignore opencode.json requirements.txt
  USER_MANUAL.md
  VERSION
)
TEMPLATES="$REPO_ROOT/goagx/publish-templates"

# The release *data* (VERSION, sbom/) ships; the fabric-root tools do not. A
# distribution has no root Makefile, so `scripts/sparknet` would exit "no
# makefile found" and `scripts/sparknet-sbom.py` would have nothing to read a
# root version from. Same policy as `scripts/sparknet-bundle.sh`.
EXCLUDE_SCRIPT_FILES=(sparknet sparknet-sbom.py)
EXCLUDE_SCRIPT_DIRS=(plugins)

prune_fabric_only_tools() {  # <root>
  local root="$1" name
  for name in "${EXCLUDE_SCRIPT_FILES[@]}"; do rm -f "$root/scripts/$name"; done
  for name in "${EXCLUDE_SCRIPT_DIRS[@]}"; do rm -rf "$root/scripts/$name"; done
}

# The export surface is selected with git's own view of the tree: tracked
# files plus untracked files git would not refuse to add. That keeps .env,
# .state, .obsidian and the staged bundle tarball out automatically — anything
# .gitignore hides in the fabric stays hidden in the distribution, so the
# staged tree and the published commit can never disagree on contents.
# NUL-delimited because paths may carry spaces.
copy_worktree() {  # <path relative to repo root>
  local rel="$1" f
  while IFS= read -r -d '' f; do
    [ -e "$REPO_ROOT/$f" ] || [ -L "$REPO_ROOT/$f" ] || continue  # deleted in the worktree
    mkdir -p "$target/$(dirname "$f")"
    cp -a "$REPO_ROOT/$f" "$target/$f"
  done < <(git -C "$REPO_ROOT" ls-files -z --cached --others --exclude-standard -- "$rel")
}

pin_get() { sed -n "s/^$1=//p" "$REPO_ROOT/goagx/GOSPARK_PIN" | head -1; }

dockerfile_arg() {  # ARG name -> default from the AGX dockerfile
  sed -n "s/^ARG $1=//p" "$REPO_ROOT/goagx/sparknet.agx.docker" | head -1
}

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  elif command -v shasum >/dev/null 2>&1; then shasum -a 256 "$1" | cut -d' ' -f1
  else return 1; fi
}

write_sums() {  # <root>: SHA256SUMS over every file but itself and .git
  local root="$1" rel
  ( cd "$root" && find . -path ./.git -prune -o -type f -print | LC_ALL=C sort | while IFS= read -r f; do
      rel="${f#./}"
      [ "$rel" = "SHA256SUMS" ] && continue
      printf '%s  %s\n' "$(sha256_of "$f")" "$rel"
    done
  ) > "$root/SHA256SUMS"
}

resolved_sha() {  # the sparknet revision this export represents
  if [ -n "$FROM_GIT" ]; then
    git -C "$REPO_ROOT" rev-parse "$FROM_GIT^{commit}"
  else
    git -C "$REPO_ROOT" rev-parse HEAD
  fi
}

# --- stage --------------------------------------------------------------------

stage_into() {  # <target-dir>
  local target="$1" subtree f sha
  mkdir -p "$target"

  if [ -n "$FROM_GIT" ]; then
    git -C "$REPO_ROOT" rev-parse "${FROM_GIT}^{commit}" >/dev/null 2>&1 \
      || die "no such ref: $FROM_GIT"
    for subtree in "${SUBTREES[@]}"; do
      if git -C "$REPO_ROOT" cat-file -e "${FROM_GIT}:${subtree}" 2>/dev/null; then
        git -C "$REPO_ROOT" archive --format=tar "$FROM_GIT" "$subtree" | tar -xf - -C "$target"
        log "from-git $subtree"
      else
        die "subtree missing at $FROM_GIT: $subtree"
      fi
    done
    for f in "${ROOT_FILES[@]}"; do
      git -C "$REPO_ROOT" cat-file -e "${FROM_GIT}:${f}" 2>/dev/null \
        || die "root file missing at $FROM_GIT: $f"
      git -C "$REPO_ROOT" archive --format=tar "$FROM_GIT" "$f" | tar -xf - -C "$target"
    done
  else
    [ -z "$(git -C "$REPO_ROOT" status --porcelain 2>/dev/null)" ] \
      || warn "working tree is dirty — the export includes uncommitted work (use --from-git for release-grade)"
    for subtree in "${SUBTREES[@]}"; do
      [ -e "$REPO_ROOT/$subtree" ] || die "subtree missing: $subtree"
      copy_worktree "$subtree"
      log "copied  $subtree"
    done
    for f in "${ROOT_FILES[@]}"; do
      [ -e "$REPO_ROOT/$f" ] || die "root file missing: $f"
      copy_worktree "$f"
    done
  fi

  prune_fabric_only_tools "$target"

  # Generated artefacts: the deploy-first README, the machine-readable pin
  # manifest, and the distribution's own CI workflow (same verify command).
  [ -f "$TEMPLATES/README.md.tmpl" ] || die "missing template $TEMPLATES/README.md.tmpl"
  [ -f "$TEMPLATES/verify.yml.tmpl" ] || die "missing template $TEMPLATES/verify.yml.tmpl"
  sha="$(resolved_sha)"
  sed -e "s|{{SPARKNET_SHA}}|$sha|g" \
      -e "s|{{GOSPARK_SHA}}|$(pin_get GOSPARK_SHA)|g" \
      -e "s|{{GOSPARK_REPO}}|$(pin_get GOSPARK_REPO)|g" \
      -e "s|{{PUBLISHED}}|$(date -u +%Y-%m-%dT%H:%M:%SZ)|g" \
      -e "s|{{VLLM_REF}}|$(dockerfile_arg VLLM_GIT_REF)|g" \
      -e "s|{{L4T_BASE}}|$(dockerfile_arg L4T_BASE)|g" \
      "$TEMPLATES/README.md.tmpl" > "$target/README.md"
  mkdir -p "$target/.github/workflows"
  cp "$TEMPLATES/verify.yml.tmpl" "$target/.github/workflows/verify.yml"

  python3 - "$target/VERSIONS.json" "$REPO_ROOT" "$sha" "$FROM_GIT" <<'PY'
import datetime, json, pathlib, re, sys

out, root, sha, from_git = sys.argv[1:5]
root = pathlib.Path(root)

def dockerfile_arg(name: str) -> str:
    text = (root / "goagx" / "sparknet.agx.docker").read_text()
    m = re.search(rf"^ARG {re.escape(name)}=(.*)$", text, re.M)
    return m.group(1).strip().strip('"') if m else ""

pin = {}
for line in (root / "goagx" / "GOSPARK_PIN").read_text().splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        pin[k.strip()] = v.strip()

manifest = {
    "name": "goagx",
    "description": "sparknet node distribution for NVIDIA AGX Xavier (sm_72, L4T r35)",
    "platform": "agx",
    "sparknet_repo": "https://github.com/reallife-spark/sparknet.git",
    "sparknet_sha": sha,
    "sparknet_from_git": from_git or "worktree",
    "gospark_repo": pin.get("GOSPARK_REPO", ""),
    "gospark_sha": pin.get("GOSPARK_SHA", ""),
    "l4t_base": dockerfile_arg("L4T_BASE"),
    "vllm_git_ref": dockerfile_arg("VLLM_GIT_REF"),
    "opencode_version": dockerfile_arg("OPENCODE_VERSION"),
    "nats_version": dockerfile_arg("NATS_VERSION"),
    "published": datetime.datetime.now(datetime.timezone.utc)
    .replace(microsecond=0)
    .isoformat()
    .replace("+00:00", "Z"),
}
pathlib.Path(out).write_text(json.dumps(manifest, indent=2) + "\n")
PY

  write_sums "$target"
  log "staged $(find "$target" -type f | wc -l) files into $target"
  log "verify it: scripts/sparknet-goagx-publish.sh --verify $target"
}

# --- verify -------------------------------------------------------------------

# Claim: a staged tree is a complete, internally consistent goagx
# distribution. Proven by extraction-side checks only — no network, so it
# runs on the publish host, in a CI runner, and inside the published repo
# itself (the generated verify workflow calls this same mode).
verify_tree() {  # <root>
  local root="$1" fail=0
  step() { printf '  → %s\n' "$*"; }
  ok()   { printf '    ✓ %s\n' "$*"; }
  bad()  { printf '    ✗ %s\n' "$*" >&2; fail=1; }
  skip() { printf '    · skipped: %s\n' "$*"; }

  step "required layout"
  local p
  for p in \
    goagx/sparknet.agx.docker goagx/sparknet.agx.compose.yml \
    goagx/sparknet-audio-shim.py goagx/bootstrap-agx.sh goagx/GOSPARK_PIN \
    goagx/README.md goagx/USER_MANUAL.md \
    sparknet-node-setup.sh spark-entrypoint.sh spark-precontext.py \
    spark.compose.cpu.yml bootstrap-agx.sh \
    contracts shared scripts peer-node master-node \
    .opencode/skills .opencode/agents opencode.json requirements.txt \
    VERSION sbom/sparknet.cdx.json \
    README.md USER_MANUAL.md VERSIONS.json SHA256SUMS .github/workflows/verify.yml
  do
    [ -e "$root/$p" ] && ok "$p" || bad "missing $p"
  done

  step "release surface: fabric-root tools absent"
  for tool in sparknet sparknet-sbom.py; do
    [ ! -e "$root/scripts/$tool" ] && ok "scripts/$tool absent as expected" \
      || bad "scripts/$tool must not be published"
  done
  [ ! -e "$root/scripts/plugins" ] && ok "scripts/plugins absent as expected" \
    || bad "scripts/plugins must not be published"

  step "role-local skill catalogs"
  local role n_role
  for role in peer master; do
    n_role="$(find "$root/$role-node/.opencode/skills" -mindepth 2 -maxdepth 2 -name SKILL.md 2>/dev/null | wc -l)"
    [ "$n_role" -gt 0 ] && ok "$role-node: $n_role role-local skills" || bad "$role-node: no role-local skills"
    if python3 "$root/scripts/sync-role-skills.py" --check --role "$role" >/dev/null 2>&1; then
      ok "$role-node: role manifest, licenses and removal list verify"
    else
      bad "$role-node: role-local skill manifest failed verification"
    fi
  done

  step "integrity manifest (SHA256SUMS)"
  if [ ! -f "$root/SHA256SUMS" ]; then
    bad "SHA256SUMS missing"
  elif ( cd "$root" && { sha256sum -c SHA256SUMS 2>/dev/null || shasum -a 256 -c SHA256SUMS 2>/dev/null; } ) >/dev/null; then
    ok "$(grep -c . "$root/SHA256SUMS") files verified"
  else
    bad "SHA256SUMS does not match the tree"
    ( cd "$root" && sha256sum -c SHA256SUMS 2>&1 | grep -v ': OK$' | head -8 | sed 's/^/      /' )
  fi

  # Symlinks carry no hash (SHA256SUMS is regular files only) — but the
  # legacy-name shims and the root bootstrap entry are links a node depends
  # on, so prove every one still resolves inside the distribution.
  step "symlinks resolve"
  local dangling
  dangling="$(cd "$root" && find . -type l ! -exec test -e {} \; -print | sed 's|^\./||' | head -8)"
  if [ -z "$dangling" ]; then
    ok "$(cd "$root" && find . -type l | wc -l) symlinks, none dangling"
  else
    bad "dangling symlinks"
    printf '%s\n' "$dangling" | sed 's/^/      /' >&2
  fi

  step "VERSIONS.json"
  if python3 - "$root/VERSIONS.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
required = ("name", "sparknet_sha", "gospark_sha", "l4t_base", "vllm_git_ref", "published")
missing = [k for k in required if not m.get(k)]
sys.exit(1 if missing else 0)
PY
  then ok "parses and carries every pin key"
  else bad "VERSIONS.json missing or missing pin keys"
  fi

  step "GOSPARK_PIN"
  local gosh
  gosh="$(sed -n 's/^GOSPARK_SHA=//p' "$root/goagx/GOSPARK_PIN" | head -1)"
  if printf '%s' "$gosh" | grep -qE '^[0-9a-f]{40}$'; then
    ok "goSpark pin is a full SHA ($gosh)"
  else
    bad "GOSPARK_SHA is not a 40-hex SHA: ${gosh:-<empty>}"
  fi

  step "--help surface"
  local s
  for s in bootstrap-agx.sh sparknet-node-setup.sh scripts/sparknet-goagx-publish.sh; do
    if bash "$root/$s" --help >/dev/null 2>&1; then ok "$s --help"; else bad "$s --help failed"; fi
  done

  step "audio shim is Python 3.8 grammar"
  if python3 - "$root/goagx/sparknet-audio-shim.py" <<'PY'
import ast, sys
ast.parse(open(sys.argv[1]).read(), feature_version=(3, 8))
PY
  then ok "ast.parse(feature_version=(3, 8))"
  else bad "shim does not parse as Python 3.8"
  fi

  step "compose resolves"
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    if ( cd "$root" && SPARKNET_QDRANT_API_KEY=verify-placeholder SPARKNET_SHARED_SECRET=verify-placeholder docker compose -f goagx/sparknet.agx.compose.yml config -q ) >/dev/null 2>&1; then
      ok "docker compose config -q"
    else
      bad "docker compose config failed on goagx/sparknet.agx.compose.yml"
    fi
  else
    skip "docker compose not available here"
  fi

  step "no key material"
  # Same patterns as scripts/sparknet-keys-check.sh — including the PEM
  # regex, whose character class is what keeps the check from matching the
  # detection strings in the checker scripts themselves.
  local keys pem
  # Vendored role-local skill content is third-party and covered by the role
  # manifest hashes; upstream examples must not read as our key material.
  keys="$(cd "$root" && find . -type f -not -path './.git/*' -not -path '*/.opencode/skills/*' | sed 's|^\./||' \
    | grep -E '(\.ed25519|\.pem|\.key|\.seed)$|(^|/)privkey|(^|/)id_ed25519' | head -5 || true)"
  pem="$(cd "$root" && find . -type f -not -path './.git/*' -not -path '*/.opencode/skills/*' -print0 2>/dev/null \
    | xargs -0 grep -lsE -- '-----BEGIN [A-Z ]*PRIVATE KEY-----' 2>/dev/null | head -5 || true)"
  if [ -n "$keys" ]; then
    bad "key-shaped files present: $keys"
  elif [ -n "$pem" ]; then
    bad "a PEM private key block is present in: $pem"
  else
    ok "no key-shaped filenames, no PEM private keys"
  fi

  if [ "$fail" -ne 0 ]; then
    printf '\nverify: FAILED\n' >&2
    return 1
  fi
  printf '\nverify: ok — the distribution is complete and consistent\n'
}

# --- push ---------------------------------------------------------------------------

clone_remote() {  # <dir>: shallow clone of the published repo
  local dir="$1"
  git clone --depth 1 "$REMOTE" "$dir" 2>/dev/null
}

push_release() {  # <stage>
  local stage="$1" work
  work="$(mktemp -d)"
  if ! clone_remote "$work/goagx"; then
    if [ "$CREATE" = 1 ]; then
      command -v gh >/dev/null || die "--create needs the gh CLI"
      log "creating $REMOTE (private)"
      gh repo create reallife-spark/goagx --private --description \
        "sparknet node distribution for NVIDIA AGX Xavier (generated — do not edit)" \
        || die "gh repo create failed"
      clone_remote "$work/goagx" || die "clone failed even after create"
    else
      rm -rf "$work"
      die "cannot clone $REMOTE (missing or no credentials) — pass --create to create it"
    fi
  fi
  rsync -a --delete --exclude=.git "$stage/" "$work/goagx/"
  git -C "$work/goagx" add -A
  if git -C "$work/goagx" diff --cached --quiet; then
    rm -rf "$work"
    log "nothing changed — the published tree already matches this export"
    return 0
  fi
  local sha gosh author_name author_email
  sha="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["sparknet_sha"])' "$stage/VERSIONS.json")"
  gosh="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["gospark_sha"][:12])' "$stage/VERSIONS.json")"
  # The release commit is authored in a throwaway clone, which inherits no
  # repo-local identity — carry the fabric's over, else fall back to a fixed
  # publish identity rather than failing on an empty ident.
  author_name="$(git -C "$REPO_ROOT" config user.name 2>/dev/null || true)"
  author_email="$(git -C "$REPO_ROOT" config user.email 2>/dev/null || true)"
  git -C "$work/goagx" -c user.name="${author_name:-sparknet-goagx-publish}" \
      -c user.email="${author_email:-goagx-publish@localhost}" \
      commit -q -m \
    "release: sparknet ${sha:0:12} · goSpark ${gosh} · generated by the fabric

Full-tree publish (scripts/sparknet-goagx-publish.sh --push). Hand edits are
overwritten by the next release — fix upstream in reallife-spark/sparknet."
  git -C "$work/goagx" push origin main
  rm -rf "$work"
  log "pushed to $REMOTE"
}

# --- drift ------------------------------------------------------------------------

drift_check() {  # stage from the tree, diff against the published tip
  local stage remote_work
  stage="$(mktemp -d)"
  remote_work="$(mktemp -d)"
  stage_into "$stage" >/dev/null
  if ! clone_remote "$remote_work/goagx"; then
    rm -rf "$stage" "$remote_work"
    if [ "${SPARKNET_GOAGX_STRICT:-0}" = 1 ]; then
      die "cannot fetch $REMOTE to compare drift (strict mode)"
    fi
    warn "SKIPPED: cannot fetch $REMOTE (private remote unreachable or unauthenticated) — goagx drift not measured"
    return 0
  fi
  # Generation metadata, stamped at stage time: the manifest timestamp, how
  # the tip happened to be published (worktree vs a ref — the sparknet_sha
  # field still catches an old ref), the README's Published row and the
  # hashes those set in SHA256SUMS. Normalizing keeps --drift from flagging
  # its own clock/mode — real content drift still shows.
  for tree in "$remote_work/goagx" "$stage"; do
    python3 - "$tree/VERSIONS.json" <<'PY'
import json, sys
path = sys.argv[1]
m = json.load(open(path))
for key in ("published", "sparknet_from_git"):
    m.pop(key, None)
with open(path, "w") as fh:
    json.dump(m, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY
    LC_ALL=C sed -i -E "s/[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z/<published>/g" "$tree/README.md"
    write_sums "$tree"
  done
  if diff -r --exclude=.git "$remote_work/goagx" "$stage" >"$remote_work/diff.txt" 2>&1; then
    rm -rf "$stage" "$remote_work"
    log "no drift: the published repo matches this tree"
    return 0
  fi
  warn "DRIFT: the published repo differs from this tree:"
  head -40 "$remote_work/diff.txt" | sed 's/^/    /' >&2
  warn "… $(grep -c '^[<>]' "$remote_work/diff.txt" || true) changed lines — republish with: make goagx-publish"
  rm -rf "$stage" "$remote_work"
  return 1
}

# --- main --------------------------------------------------------------------------

case "$ACTION" in
  out)
    if [ -d "$OUT" ] && [ -n "$(ls -A "$OUT" 2>/dev/null)" ] && [ "$FORCE" -ne 1 ]; then
      die "$OUT is not empty (use --force)"
    fi
    stage_into "$OUT"
    ;;
  verify)
    root="$VERIFY_PATH"
    if [ -f "$root" ]; then
      case "$root" in
        *.tar.gz|*.tgz)
          tmp="$(mktemp -d)"
          python3 "$REPO_ROOT/scripts/sparknet-safe-extract.py" "$root" "$tmp"
          root="$tmp"
          ;;
        *) die "--verify needs a staged directory or a .tar.gz (got: $VERIFY_PATH)" ;;
      esac
    fi
    [ -d "$root" ] || die "no such directory: $VERIFY_PATH"
    verify_tree "$root"
    ;;
  push)
    stage="$(mktemp -d)"
    stage_into "$stage"
    verify_tree "$stage" || die "verify failed — refusing to publish a broken tree"
    push_release "$stage"
    rm -rf "$stage"
    ;;
  drift)
    drift_check
    ;;
esac
