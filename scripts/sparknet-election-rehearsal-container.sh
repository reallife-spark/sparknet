#!/usr/bin/env bash
# Containerised election rehearsal: the Step 12/13 election-to-escalation arc,
# run inside the built node image instead of on the host.
#
# What this proves (and what it does not):
#   It proves the *packaged artifact* — image toolchain, baked python, the
#   ceremony scripts as shipped — can build three node identities, swap keys,
#   hold the election, form a 2-of-n-ready trust root with three cosignatures,
#   run the isolated signer, publish a registry entry the elected key signs, and
#   refuse the three escalation attempts. It runs on a docker bridge network
#   namespace, so it does NOT exercise WireGuard on a real NIC, systemd reboot
#   survival, or deployed containment — those stay `DoD: confirm: user`.
#
# The ceremony logic itself is not duplicated here: this wrapper drives the
# existing scripts/sparknet-rehearsal.sh inside the container (the env overrides
# below let that script use the container's interpreter and a pre-built bundle).
#
#   ./scripts/sparknet-election-rehearsal-container.sh
#   SPARKNET_IMAGE=sparknet-spark-node:dev ./scripts/sparknet-election-rehearsal-container.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${SPARKNET_IMAGE:-sparknet-spark-node:dev}"
PYTHON_IN_IMAGE="${SPARKNET_IMAGE_PYTHON:-/opt/sparknet/venv/bin/python}"

log()  { printf '\033[1;36m[election-container]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
sparknet-election-rehearsal-container.sh — election arc inside the node image

Usage:
  scripts/sparknet-election-rehearsal-container.sh [--help]

Environment:
  SPARKNET_IMAGE          image to run          (default sparknet-spark-node:dev)
  SPARKNET_REHEARSAL_TGZ  pre-built master bundle to reuse (otherwise `make bundle`)
  SPARKNET_ELECTION_PORT  ceremony port, host-side only for documentation (default 4210)

The host transcript and node trees are written to a temp dir printed at start;
on success the node trees are removed and only the transcript is kept.
USAGE
}

case "${1:-}" in
  "") : ;;
  -h|--help) usage; exit 0 ;;
  *) printf 'unexpected argument: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
esac

command -v docker >/dev/null || die "docker not found"
docker image inspect "$IMAGE" >/dev/null 2>&1 \
  || die "image '$IMAGE' not found — build it first (./sparknet-node-setup.sh build)"

# --- bundle (host side: make, git, write access live here) --------------------
TGZ="${SPARKNET_REHEARSAL_TGZ:-}"
if [ -z "$TGZ" ]; then
  log "building a master worktree bundle (the master bundle is the whole node)"
  make -C "$REPO_ROOT" bundle ROLE=master >/dev/null
  TGZ="$(ls -t "$REPO_ROOT"/dist/sparknet-master-worktree-*.tar.gz 2>/dev/null | head -1 || true)"
  [ -n "$TGZ" ] && [ -f "$TGZ" ] || die "no master bundle produced under dist/"
fi
log "bundle: $(basename "$TGZ")"

mkdir -p /tmp/opencode
OUT="$(mktemp -d /tmp/opencode/spark-election-container-XXXXXX)"
log "work dir (transcript lands here): $OUT"

# --- run the rehearsal in the image ------------------------------------------
# - the fabric tree is mounted read-only: the script skips `make bundle`
#   (SPARKNET_REHEARSAL_TGZ) and only reads shared/ + the role scripts from it
# - --user keeps everything written to $OUT owned by the invoking user
rc=0
docker run --rm -i \
  --user "$(id -u):$(id -g)" \
  -e HOME=/tmp \
  -v "$REPO_ROOT:/fabric:ro" \
  -v "$TGZ:/bundle/master-worktree.tar.gz:ro" \
  -v "$OUT:/out" \
  -e SPARKNET_PYTHON="$PYTHON_IN_IMAGE" \
  -e SPARKNET_ELECTION_PY=/fabric/shared/sparknet-election.py \
  -e SPARKNET_SIGNER_PY=/fabric/master-node/services/sparknet-signer.py \
  -e SPARKNET_REHEARSAL_TGZ=/bundle/master-worktree.tar.gz \
  -e SPARKNET_REHEARSAL_DIR=/out \
  -e SPARKNET_ELECTION_PORT="${SPARKNET_ELECTION_PORT:-4210}" \
  --entrypoint bash \
  "$IMAGE" /fabric/scripts/sparknet-rehearsal.sh || rc=$?

# --- report -------------------------------------------------------------------
TRANSCRIPT="$(ls -t "$OUT"/rehearsal-*.log 2>/dev/null | head -1 || true)"
if [ "$rc" -eq 0 ]; then
  log "rehearsal PASSED inside $IMAGE"
  if [ -n "$TRANSCRIPT" ]; then
    # keep only the transcript; drop the (large) extracted node trees with OUT
    KEEP="${OUT}.rehearsal.log"
    cp "$TRANSCRIPT" "$KEEP"
    rm -rf "$OUT" 2>/dev/null || true
    log "transcript: $KEEP"
  fi
  exit 0
fi
log "rehearsal FAILED inside $IMAGE (rc=$rc)"
[ -n "$TRANSCRIPT" ] && { log "transcript: $TRANSCRIPT"; tail -30 "$TRANSCRIPT"; }
log "node trees kept for inspection under $OUT"
exit "$rc"
