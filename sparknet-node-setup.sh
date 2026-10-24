#!/usr/bin/env bash
# sparknet-node-setup.sh — bring up a SparkNet node end to end (DGX Spark by
# default; AGX Xavier with --platform agx).
#
# One command from a clean checkout to a running node: build the sparknet bundle,
# stage it for the image, mint the shared secret, write the compose env-file,
# build the node image, and `docker compose up` the services. Idempotent: run it
# again and it reuses everything already in place.
#
#   ./sparknet-node-setup.sh                 # text node: nats vllm compute agent gpu
#   ./sparknet-node-setup.sh --role master   # also start the control plane (:control)
#   ./sparknet-node-setup.sh --profiles embed,webui
#   ./sparknet-node-setup.sh --engine stub   # no GPU: CPU stub engine + sim telemetry
#   ./sparknet-node-setup.sh --platform agx  # AGX Xavier: goagx/sparknet.agx.* image+compose
#   ./sparknet-node-setup.sh up              # build step already done -> just run
#
# Join a running fabric by handing the node the elected Master's public key and
# the Master-signed registry (instead of running open, self-signed):
#
#   ./sparknet-node-setup.sh --master-pub "$MASTER_PUB" \
#     --registry /path/to/node-authorizations.json up
#
# It writes exactly three host things: the node state under peer-node/.state
# (keys, secret, env-file, the joined registry — gitignored, mode 0600/0700), the
# staged bundle tarball at peer-node/container/context/sparknet-peer.tar.gz, and
# nothing else. No secret ever enters an image layer.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NODE_STATE="$REPO/peer-node/.state"
ENV_FILE="$NODE_STATE/spark.env"
COMPOSE_FILE="$REPO/spark.compose.yml"
GOSPARK_DIR="${GOSPARK_DIR:-/mnt/knowledge/goSpark}"

ROLE="${SPARKNET_ROLE:-peer}"
PROFILES="${SPARK_PROFILES:-}"
ENGINE="${SPARK_ENGINE:-vllm}"   # vllm (real GPU engine) | stub (CPU-only OpenAI-compatible stub)
PLATFORM="${SPARKNET_PLATFORM:-spark}"  # spark (DGX Spark image) | agx (AGX Xavier image)
MASTER_PUB="${SPARKNET_MASTER_PUB:-}"   # b64 string or a file containing it
REGISTRY="${SPARKNET_REGISTRY_FILE:-}"  # Master-signed node-authorizations registry
DO_BUILD=1
ACTION="up"

log()  { printf '\033[1;36m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[error]\033[0m %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
sparknet-node-setup.sh — bring up a SparkNet node (DGX Spark or AGX Xavier).

Usage: sparknet-node-setup.sh [action] [options]

Actions:
  up        (default) build everything needed, then start the services
  build     build the bundle + image only, do not start
  down      stop the services
  status    show service status
  logs      tail the services

Options:
  --role peer|master   node role (default peer; master also enables the control plane)
  --platform spark|agx target image/compose (default spark = DGX Spark;
                        agx = AGX Xavier, goagx/sparknet.agx.* — its own
                        env-file, so switching platforms never inherits
                        the other's base/model lines)
  --engine vllm|stub   model engine (default vllm; stub = CPU-only OpenAI stub, no GPU/model)
  --profiles A,B,C     compose profiles to enable: kv control webui embed rerank audio ingest backup opencode
  --master-pub KEY     the elected Master's Ed25519 public key (base64) or a file
                       holding it; joins the node to the fabric instead of running
                       open. With --registry and no key, the key is read from the
                       registry's master_public_key_b64 (less strong than pinning
                       it out of band; logged).
  --registry FILE      Master-signed node-authorizations registry to adopt; copied
                       into the node state dir and passed to the goSpark agent.
  --no-build           skip the bundle + image build (use the existing image)
  --gospark DIR        goSpark checkout (default /mnt/knowledge/goSpark)
  -h, --help           this text
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    up|build|down|status|logs) ACTION="$1"; shift ;;
    --role)       ROLE="$2"; shift 2 ;;
    --platform)   PLATFORM="$2"; shift 2 ;;
    --engine)     ENGINE="$2"; shift 2 ;;
    --profiles)   PROFILES="$2"; shift 2 ;;
    --master-pub) MASTER_PUB="$2"; shift 2 ;;
    --registry)   REGISTRY="$2"; shift 2 ;;
    --no-build)   DO_BUILD=0; shift ;;
    --gospark)   GOSPARK_DIR="$2"; shift 2 ;;
    -h|--help)   usage; exit 0 ;;
    *) die "unknown argument: $1 (try --help)" ;;
  esac
done

case "$ENGINE" in
  vllm|stub) ;;
  *) die "--engine must be 'vllm' or 'stub' (got: $ENGINE)" ;;
esac
case "$ROLE" in
  peer|master) ;;
  *) die "--role must be 'peer' or 'master' (got: $ROLE)" ;;
esac
if [ -n "$REGISTRY" ] && [ "$ROLE" = master ]; then
  die "--registry joins a PEER to a fabric whose Master signs elsewhere; a master node runs the control plane, which signs its own registry"
fi

# The platform selects the compose file and the env-file together: an AGX node
# must never build against spark.compose.yml, and the two platforms keep
# separate env-files (spark.env vs spark-agx.env) so a switch never inherits
# the other's base/model lines.
case "$PLATFORM" in
  spark)
    COMPOSE_FILE="$REPO/spark.compose.yml"
    ENV_FILE="$NODE_STATE/spark.env"
    ;;
  agx)
    COMPOSE_FILE="$REPO/goagx/sparknet.agx.compose.yml"
    ENV_FILE="$NODE_STATE/spark-agx.env"
    ;;
  *) die "--platform must be 'spark' or 'agx' (got: $PLATFORM)" ;;
esac

# --- preflight ---------------------------------------------------------------

preflight() {
  command -v docker >/dev/null || die "docker not found"
  docker compose version >/dev/null 2>&1 || die "'docker compose' (v2 plugin) not found"
  [ -f "$COMPOSE_FILE" ] || die "compose file missing: $COMPOSE_FILE"
  if [ -n "$REGISTRY" ]; then
    [ -f "$REGISTRY" ] || die "registry file not found: $REGISTRY"
  fi
  if [ "$DO_BUILD" = 1 ]; then
    [ -d "$GOSPARK_DIR" ] || die "goSpark not found at $GOSPARK_DIR (use --gospark DIR)"
    for b in sparknet-agent sparknet-control sparknet-gpu sparknetctl; do
      [ -x "$GOSPARK_DIR/bin/$b" ] \
        || die "missing $GOSPARK_DIR/bin/$b — run: make -C $GOSPARK_DIR build build-gpu"
    done
  fi
}

compose() {
  local -a pf=()
  local p
  for p in ${PROFILES//,/ }; do [ -n "$p" ] && pf+=(--profile "$p"); done
  [ "$ROLE" = master ] && pf+=(--profile control)
  local -a ef=()
  [ -f "$ENV_FILE" ] && ef=(--env-file "$ENV_FILE")
  local -a files=(-f "$COMPOSE_FILE")
  # CPU-only overlay: drops the GPU device reservations and runs the stub engine.
  [ "$ENGINE" = stub ] && files+=(-f "$REPO/spark.compose.cpu.yml")
  docker compose "${files[@]}" "${ef[@]}" "${pf[@]}" "$@"
}

# --- build the node image ----------------------------------------------------

stage_bundle() {
  log "building the sparknet peer bundle"
  make -C "$REPO/peer-node" dist
  local tarball
  tarball="$(ls -t "$REPO"/dist/sparknet-peer-*.tar.gz 2>/dev/null | head -1)"
  [ -n "$tarball" ] || die "no bundle produced under dist/"
  mkdir -p "$REPO/peer-node/container/context"
  cp "$tarball" "$REPO/peer-node/container/context/sparknet-peer.tar.gz"
  log "staged bundle: $(basename "$tarball")"
}

# --- env-file + state --------------------------------------------------------

# In-container paths (the state dir is a host bind mount; see spark.compose.yml).
STATE_DIR_IN_CONTAINER=/srv/sparknet/peer-node/.state
REGISTRY_IN_CONTAINER="$STATE_DIR_IN_CONTAINER/node-authorizations.json"

# Resolve the fabric-join inputs (--master-pub / --registry) into the values the
# env-file carries. Joining is opt-in: with neither, the node runs open and
# self-signed exactly as before.
#
#   * --master-pub may be the base64 key itself or a path to a file holding it;
#   * --registry is copied verbatim into the node state dir (never an image
#     layer) and its path handed to the goSpark agent;
#   * when a registry is given without a pinned key, the operational key is read
#     from the registry's own master_public_key_b64 field — the key the elected
#     root names — and a warning is logged, because a key read from the same
#     document it is meant to authenticate is weaker than one pinned out of band.
resolve_join() {
  JOIN_MASTER_PUB=""
  JOIN_REGISTRY_PATH=""

  if [ -n "$MASTER_PUB" ]; then
    if [ -f "$MASTER_PUB" ]; then
      JOIN_MASTER_PUB="$(tr -d '[:space:]' < "$MASTER_PUB")"
    else
      JOIN_MASTER_PUB="$(printf '%s' "$MASTER_PUB" | tr -d '[:space:]')"
    fi
    [ -n "$JOIN_MASTER_PUB" ] || die "--master-pub is empty"
  fi

  if [ -n "$REGISTRY" ]; then
    [ -f "$REGISTRY" ] || die "registry file not found: $REGISTRY"
    mkdir -p "$NODE_STATE"
    cp "$REGISTRY" "$NODE_STATE/node-authorizations.json"
    chmod 600 "$NODE_STATE/node-authorizations.json"
    JOIN_REGISTRY_PATH="$REGISTRY_IN_CONTAINER"
    if [ -z "$JOIN_MASTER_PUB" ]; then
      command -v python3 >/dev/null || die "python3 needed to read master_public_key_b64 from the registry"
      JOIN_MASTER_PUB="$(python3 -c \
        'import json,sys;print(json.load(open(sys.argv[1])).get("master_public_key_b64",""))' \
        "$REGISTRY")"
      [ -n "$JOIN_MASTER_PUB" ] \
        || die "registry $REGISTRY has no master_public_key_b64; pass --master-pub"
      warn "no --master-pub: using the key embedded in the registry (pin it out of band for the strong form)"
    fi
  fi
}

render_env_file() {
  mkdir -p "$NODE_STATE"
  chmod 700 "$NODE_STATE" 2>/dev/null || true
  resolve_join

  local id role overlay model secret base_line max_len_line img_dockerfile
  id="${SPARKNET_NODE_ID:-$(hostname)}"
  role="$ROLE"
  if [ -n "${SPARKNET_OVERLAY_IPV4:-}" ]; then overlay="$SPARKNET_OVERLAY_IPV4"
  elif [ "$role" = master ]; then overlay="10.100.0.1"; else overlay="10.100.0.2"; fi
  # Platform-conditional block: the AGX node builds from an L4T base with a
  # 7B default (Xavier has 8-16 GB, not 128) and a tighter context/shm; the
  # Spark node keeps its vLLM base, 32B default and 65536 context. The build
  # escape hatches (VLLM_GIT_URL, MAX_JOBS, ...) pass through the shell
  # environment, so they are deliberately not written here.
  if [ "$PLATFORM" = agx ]; then
    model="${VLLM_MODEL:-mistralai/Mistral-7B-Instruct-v0.2}"
    base_line="L4T_BASE=${L4T_BASE:-nvcr.io/nvidia/l4t-pytorch:r35.2.1-pth2.0-py3}"
    max_len_line="VLLM_MAX_MODEL_LEN=${VLLM_MAX_MODEL_LEN:-8192}
VLLM_SHM_SIZE=${VLLM_SHM_SIZE:-4gb}"
    img_dockerfile=sparknet.agx.docker
  else
    model="${VLLM_MODEL:-Qwen/Qwen2.5-32B-Instruct}"
    base_line="VLLM_BASE=${VLLM_BASE:-nvcr.io/nvidia/vllm:26.04-py3}"
    max_len_line="VLLM_MAX_MODEL_LEN=${VLLM_MAX_MODEL_LEN:-65536}"
    img_dockerfile=spark.docker
  fi

  # One secret for the whole node, shared by compute/agent/control/kvrouter. It
  # lives in the host state dir and is passed to every service through the
  # env-file, so the containers cannot disagree about it.
  # VLLM_SERVICE_CMD picks the engine the `vllm` service runs: `vllm` (real) or
  # `vllm-stub` (CPU-only stub) — see --engine.
  service_cmd="vllm"
  [ "$ENGINE" = stub ] && service_cmd="vllm-stub"
  secret="$NODE_STATE/sparknet.shared.secret"
  if [ ! -s "$secret" ]; then
    head -c 32 /dev/urandom | base64 | tr -d '\n' > "$secret"
    chmod 600 "$secret"
  fi
  local secret_val; secret_val="$(cat "$secret")"

  umask 077
  cat > "$ENV_FILE" <<EOF
# Generated by sparknet-node-setup.sh — do not commit ($(date -Iseconds)).
SPARKNET_NODE_ID=$id
SPARKNET_ROLE=$role
SPARKNET_OVERLAY_IPV4=$overlay
SPARKNET_SHARED_SECRET=$secret_val
SPARKNET_STATE_HOST=$NODE_STATE
GOSPARK_DIR=$GOSPARK_DIR
SPARKNET_IMAGE_TAG=${SPARKNET_IMAGE_TAG:-dev}
$base_line
VLLM_MODEL=$model
VLLM_SERVICE_CMD=$service_cmd
VLLM_GPU_MEM_UTIL=${VLLM_GPU_MEM_UTIL:-0.85}
$max_len_line
HF_CACHE_DIR=${HF_CACHE_DIR:-$HOME/.cache/huggingface}
SPARKNET_BIND_API=${SPARKNET_BIND_API:-0.0.0.0}
SPARKNET_BIND_LOCAL=${SPARKNET_BIND_LOCAL:-127.0.0.1}
# Pinned foreign images. NATS_IMAGE_TAG must track NATS_VERSION in $img_dockerfile
# (the same nats-server is also baked into the image for `spark-entrypoint nats`);
# WEBUI_TAG is a stable release, never `main`/`latest`.
NATS_IMAGE_TAG=${NATS_IMAGE_TAG:-2.14.2-alpine}
WEBUI_TAG=${WEBUI_TAG:-v0.12.2}
SPARKNET_MASTER_PUB=${JOIN_MASTER_PUB:-}
GOSPARK_REGISTRY_FILE=${JOIN_REGISTRY_PATH:-}
# Reflex is local-only: a local reranker/LLM, or the Master's broker, which
# answers locally too. There is no egress path and no credential. No new
# published port.
SPARKNET_REFLEX_MODE=${SPARKNET_REFLEX_MODE:-local}
SPARKNET_REFLEX_BACKEND=${SPARKNET_REFLEX_BACKEND:-local}
SPARKNET_REFLEX_LOCAL_URL=${SPARKNET_REFLEX_LOCAL_URL:-http://127.0.0.1:8000}
SPARKNET_REFLEX_LOCAL_MODEL=${SPARKNET_REFLEX_LOCAL_MODEL:-local}
SPARKNET_REFLEX_BROKER_URL=${SPARKNET_REFLEX_BROKER_URL:-http://10.100.0.1:4224}
SPARKNET_REFLEX_TIMEOUT=${SPARKNET_REFLEX_TIMEOUT:-2.0}
EOF
  chmod 600 "$ENV_FILE"
  if [ -n "${JOIN_REGISTRY_PATH:-}" ]; then
    log "joined fabric: registry staged, master key $([ -n "$JOIN_MASTER_PUB" ] && echo pinned || echo 'from registry')"
  fi
  log "wrote $ENV_FILE (node=$id role=$role overlay=$overlay)"
}

# Stub engine: write a synthetic GPU fixture so the `gpu` sidecar reports
# available=true on a host with no driver. Telemetry only, and only ever active
# together with the CPU overlay (see spark.compose.cpu.yml).
write_gpu_fixture() {
  [ "$ENGINE" = stub ] || return 0
  local out="$NODE_STATE/gpu-sim.json"
  [ -s "$out" ] && return 0
  if [ -x "$REPO/scripts/make-gpu-fixture.py" ]; then
    "$REPO/scripts/make-gpu-fixture.py" -o "$out" >/dev/null
    chmod 644 "$out"
    log "wrote synthetic GPU fixture: $out"
  else
    warn "scripts/make-gpu-fixture.py missing; gpu sidecar will report unavailable"
  fi
}

ensure_vault_env() {
  if [ ! -f "$REPO/peer-node/.env" ]; then
    if [ -x "$REPO/scripts/sparknet-env-init.sh" ]; then
      log "initializing the node vault .env"
      "$REPO/scripts/sparknet-env-init.sh" "$REPO/peer-node" >/dev/null
    else
      warn "no scripts/sparknet-env-init.sh; the image regenerates .env at start"
    fi
  fi
  mkdir -p "$NODE_STATE/nats" "$NODE_STATE/webui"
}

# --- actions -----------------------------------------------------------------

act_build() {
  stage_bundle
  render_env_file
  write_gpu_fixture
  ensure_vault_env
  if [ "$PLATFORM" = agx ]; then
    log "building the node image ($PLATFORM: L4T_BASE=${L4T_BASE:-nvcr.io/nvidia/l4t-pytorch:r35.2.1-pth2.0-py3})"
  else
    log "building the node image ($PLATFORM: VLLM_BASE=${VLLM_BASE:-nvcr.io/nvidia/vllm:26.04-py3})"
  fi
  compose build
}

act_up() {
  [ "$DO_BUILD" = 1 ] && act_build
  # Re-render whenever join inputs are (re)specified, so an already-running node
  # can be joined without hand-editing the env-file; otherwise render only if the
  # env-file does not exist yet (never clobber a hand-tuned one).
  if [ ! -f "$ENV_FILE" ] || [ -n "$MASTER_PUB" ] || [ -n "$REGISTRY" ]; then
    render_env_file
  fi
  write_gpu_fixture
  log "starting services (role=$ROLE engine=${ENGINE} profiles=${PROFILES:-none})"
  compose up -d
  echo
  log "node up. Endpoints:"
  printf '    vLLM OpenAI API   http://%s:8000/v1\n' "${SPARKNET_BIND_API:-0.0.0.0}"
  printf '    node gateway      http://%s:8080/v1\n' "${SPARKNET_BIND_API:-0.0.0.0}"
  [ "$ROLE" = master ] && printf '    control admin     http://127.0.0.1:8899/admin\n'
  case ",$PROFILES," in *,webui,*) printf '    Open WebUI        http://%s:3000\n' "${SPARKNET_BIND_API:-0.0.0.0}" ;; esac
  if [ "$ENGINE" = stub ]; then
    warn "engine=stub: :8000 answers from the CPU stub, not a real model;"
    warn "the GPU sidecar reads a synthetic fixture (telemetry only)."
  fi
  cat <<'EOF'

Next steps:
  * List models:      curl -s http://127.0.0.1:8080/v1/models
  * Node logs:        ./sparknet-node-setup.sh logs
  * Stop:             ./sparknet-node-setup.sh down
  * Fabric election (choose a Master, sign the trust root) is a separate
    ceremony — see contracts/deployment-runbook.md. This script only stands a
    node up; it does not elect or sign.
EOF
}

# --- main --------------------------------------------------------------------

# down/status/logs never need a build or the goSpark checkout.
case "$ACTION" in down|status|logs) DO_BUILD=0 ;; esac

preflight
case "$ACTION" in
  build)  act_build ;;
  up)     act_up ;;
  down)   compose down ;;
  status) compose ps ;;
  logs)   compose logs -f --tail=100 ;;
esac
