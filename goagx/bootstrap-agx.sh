#!/usr/bin/env bash
# bootstrap-agx.sh — from a clone of this repo to a running sparknet node on an
# NVIDIA AGX Xavier, in one command (fabric PLAN Step 62).
#
#   1. preflight the device: aarch64, L4T r35 (JetPack 5), docker + compose v2
#      + buildx + the nvidia container runtime, disk, and the swap the
#      vLLM/xformers source build needs on a 16 GB machine
#   2. fetch goSpark at the pinned SHA (goagx/GOSPARK_PIN) and build its
#      binaries — native Go on arm64, minutes, not hours
#   3. hand over to ../sparknet-node-setup.sh --platform agx, which stages the
#      peer bundle, renders the env-file, builds the node image (the hours-long
#      vLLM leg) and starts the services
#
# Usage: goagx/bootstrap-agx.sh [options] [sparknet-node-setup.sh args...]
#
# Options:
#   --gospark DIR       goSpark checkout to use (default: ./gospark when it
#                       exists, else .cache/goSpark fetched at the pin;
#                       forwarded to the setup script too)
#   --allow-low-swap    continue even when swap is below the build minimum
#   --allow-low-disk    continue even when free disk is below the image floor
#   -h, --help          this text
#
# Everything not listed above is forwarded to sparknet-node-setup.sh, so the
# whole surface stays available:
#
#   ./goagx/bootstrap-agx.sh --role master up
#   ./goagx/bootstrap-agx.sh --profiles embed,webui --engine vllm
#   ./goagx/bootstrap-agx.sh --master-pub KEY --registry node-authorizations.json up
#
# The device needs git + credentials that can read reallife-spark/goSpark
# (fine-grained PAT or deploy key; the repo is private). Nothing here writes
# outside .cache/ and peer-node/.state (via the setup script).
set -euo pipefail

MIN_SWAP_KB=8388608    # 8 GiB — the xformers sdist + vLLM link OOM-kill floor
MIN_DISK_MB=25600      # ~20 GB image + base layers, plus headroom

log()  { printf '\033[1;36m[bootstrap-agx]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[bootstrap-agx]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[bootstrap-agx]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
bootstrap-agx.sh — bring up a sparknet AGX Xavier node from this repo.

Usage: goagx/bootstrap-agx.sh [options] [sparknet-node-setup.sh args...]

Options:
  --gospark DIR       goSpark checkout (default: ./gospark when present, else
                      .cache/goSpark fetched at the pin from goagx/GOSPARK_PIN)
  --allow-low-swap    continue even when swap < 8 GiB (the source build
                      OOM-kills itself on a 16 GB Xavier without it)
  --allow-low-disk    continue even when free disk < ~25 GB
  -h, --help          this text

All other arguments are forwarded to sparknet-node-setup.sh, which always
runs with --platform agx. Examples:
  ./goagx/bootstrap-agx.sh up
  ./goagx/bootstrap-agx.sh --role master up
  ./goagx/bootstrap-agx.sh --master-pub KEY --registry node-authorizations.json up
EOF
}

# --- arguments (before any work: --help must do nothing) ----------------------
ALLOW_LOW_SWAP=0
ALLOW_LOW_DISK=0
GOSPARK_DIR="${GOSPARK_DIR:-}"
FORWARD=()
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)        usage; exit 0 ;;
    --allow-low-swap) ALLOW_LOW_SWAP=1; shift ;;
    --allow-low-disk) ALLOW_LOW_DISK=1; shift ;;
    --gospark)        [ $# -ge 2 ] || die "--gospark needs a directory"; GOSPARK_DIR="$2"; shift 2 ;;
    *)                FORWARD+=("$1"); shift ;;
  esac
done

# This file lives at goagx/bootstrap-agx.sh; the repo-root bootstrap-agx.sh is
# a symlink to it. Resolve the real path so the root is found either way.
SCRIPT="$(readlink -f "${BASH_SOURCE[0]}")"
ROOT="$(cd "$(dirname "$SCRIPT")/.." && pwd)"
PIN_FILE="$ROOT/goagx/GOSPARK_PIN"
SETUP="$ROOT/sparknet-node-setup.sh"
[ -f "$PIN_FILE" ] || die "missing $PIN_FILE — run from a complete repo clone"
[ -x "$SETUP" ] || die "missing $SETUP — run from a complete repo clone"

pin_get() {  # key -> value, from the pin file
  sed -n "s/^$1=//p" "$PIN_FILE" | head -1
}

# --- preflight ----------------------------------------------------------------

preflight() {
  local arch free_mb swap_kb runtimes root_dir

  arch="$(uname -m)"
  [ "$arch" = aarch64 ] || die "aarch64 required (this host is $arch) — goagx targets Jetson AGX Xavier"

  [ -r /etc/nv_tegra_release ] \
    || die "/etc/nv_tegra_release missing — not an L4T/Jetson host; this image targets JetPack 5 (L4T r35)"
  grep -q 'R35' /etc/nv_tegra_release \
    || die "L4T r35 (JetPack 5.x) required — $(head -1 /etc/nv_tegra_release); the r36/r37 stacks need the spark platform image, not goagx"

  command -v docker >/dev/null || die "docker not found — install the JetPack docker runtime"
  docker compose version >/dev/null 2>&1 || die "'docker compose' (v2 plugin) not found"
  docker buildx version >/dev/null 2>&1 || die "docker buildx not found — the node image builds with BuildKit"
  runtimes="$(docker info --format '{{json .Runtimes}}' 2>/dev/null || true)"
  case "$runtimes" in
    *nvidia*) : ;;
    *) die "the nvidia container runtime is not registered with docker (docker info shows none); install nvidia-container-toolkit / the JetPack docker runtime" ;;
  esac

  root_dir="$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || printf '/')"
  free_mb="$(df -Pm "$root_dir" 2>/dev/null | awk 'NR==2 {print $4}')"
  free_mb="${free_mb:-0}"
  if [ -n "$free_mb" ] && [ "$free_mb" -lt "$MIN_DISK_MB" ] && [ "$ALLOW_LOW_DISK" -ne 1 ]; then
    die "only ${free_mb} MB free under $root_dir (need ≥ ${MIN_DISK_MB} MB for the image build) — free space or pass --allow-low-disk"
  fi

  swap_kb="$(awk '/^SwapTotal:/ {print $2}' /proc/meminfo 2>/dev/null || printf '0')"
  if [ "${swap_kb:-0}" -lt "$MIN_SWAP_KB" ] && [ "$ALLOW_LOW_SWAP" -ne 1 ]; then
    die "swap is ${swap_kb:-0} kB (need ≥ ${MIN_SWAP_KB} kB): the xformers/vLLM source build OOM-kills itself on 16 GB without it. Add a swapfile (systemd or fallocate+mkswap+swapon), or pass --allow-low-swap to proceed anyway"
  fi

  log "preflight ok (arch=aarch64, $(head -1 /etc/nv_tegra_release | tr -d '\n'))"
  [ "$free_mb" -lt "$MIN_DISK_MB" ] && warn "disk headroom is low (${free_mb} MB under $root_dir) — proceeding on --allow-low-disk"
  [ "${swap_kb:-0}" -lt "$MIN_SWAP_KB" ] && warn "swap is below the build minimum — proceeding on --allow-low-swap; expect OOM risk"
  return 0
}

# --- goSpark at the pin -------------------------------------------------------

fetch_gospark() {
  local repo sha
  repo="$(pin_get GOSPARK_REPO)"
  sha="$(pin_get GOSPARK_SHA)"
  [ -n "$repo" ] && [ -n "$sha" ] || die "goagx/GOSPARK_PIN is missing GOSPARK_REPO/GOSPARK_SHA"

  if [ -z "$GOSPARK_DIR" ]; then
    # A fabric checkout lives at <root>/gospark; a standalone goagx distribution
    # has no such tree and falls back to the pinned fetch cache.
    if [ -d "$ROOT/gospark/.git" ]; then
      GOSPARK_DIR="$ROOT/gospark"
    else
      GOSPARK_DIR="$ROOT/.cache/goSpark"
    fi
  fi

  if [ -d "$GOSPARK_DIR/.git" ]; then
    local head
    head="$(git -C "$GOSPARK_DIR" rev-parse HEAD 2>/dev/null || true)"
    if [ "$head" != "$sha" ]; then
      die "goSpark at $GOSPARK_DIR is at ${head:-unknown}, pin is $sha — update that checkout (git fetch && git checkout $sha) or pass --gospark DIR"
    fi
    log "goSpark checkout at $GOSPARK_DIR matches the pin"
  elif [ -e "$GOSPARK_DIR" ]; then
    die "$GOSPARK_DIR exists but is not a git checkout"
  else
    log "fetching goSpark $sha into $GOSPARK_DIR"
    mkdir -p "$(dirname "$GOSPARK_DIR")"
    git init -q "$GOSPARK_DIR"
    git -C "$GOSPARK_DIR" remote add origin "$repo"
    git -C "$GOSPARK_DIR" fetch -q --depth 1 origin "$sha" \
      || die "cannot fetch $sha from $repo — credentials needed (the repo is private); configure a PAT or deploy key and retry"
    git -C "$GOSPARK_DIR" checkout -q FETCH_HEAD
  fi
  if [ ! -d "$GOSPARK_DIR/cmd/sparknet-memory" ]; then
    die "goSpark at ${sha:0:12} has no cmd/sparknet-memory; the pin predates the memory service. Bump GOSPARK_PIN to a revision that contains it, or pass --gospark DIR."
  fi
}

build_gospark() {
  log "building goSpark binaries (make build build-gpu)"
  make -C "$GOSPARK_DIR" build build-gpu \
    || die "goSpark build failed in $GOSPARK_DIR"
  local b
  for b in sparknet-agent sparknet-control sparknet-gpu sparknetctl; do
    [ -x "$GOSPARK_DIR/bin/$b" ] \
      || die "missing $GOSPARK_DIR/bin/$b after the build — see goSpark's Makefile"
  done
  log "goSpark binaries ready under $GOSPARK_DIR/bin"
}

# --- main ---------------------------------------------------------------------

preflight
fetch_gospark
build_gospark

log "handing over to sparknet-node-setup.sh --platform agx"
exec "$SETUP" --platform agx --gospark "$GOSPARK_DIR" ${FORWARD[@]+"${FORWARD[@]}"}
