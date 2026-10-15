#!/usr/bin/env bash
# spark-entrypoint — the DGX Spark node's one dispatcher.
#
# `spark.compose.yml` runs THIS SAME IMAGE with a different subcommand per
# service, so the whole node (engine, control plane, compute plane, bundle,
# precontext) is one image and one code path:
#
#   vllm       the vLLM OpenAI server, with the fabric precontext chat template
#   compute    the Python compute-plane worker (infer/embed) beside the GPU
#   kvrouter   the RadixAttention / KV-residency index daemon
#   agent      a goSpark node: verifies signed tasks, executes, attests
#   control    the goSpark control plane (holds the Master signing key)
#   gpu        the cgo GPU-telemetry sidecar (degrades: available=false + reason)
#   nats       the NATS/JetStream bus the goSpark plane runs on
#   opencode   the node's agent surface over the vault
#   precontext (re)build the chat template only, then exit
#   shell      drop to a shell in the node image
#
# Nothing here bakes a vault path or a secret. The sparknet .env is regenerated
# at boot, keys live in the host-mounted $SPARKNET_STATE_DIR (never an image
# layer), and the shared secret is generated once into that state dir and shared
# by every service through the environment.
set -euo pipefail

FABRIC="${SPARKNET_FABRIC_ROOT:-/srv/sparknet}"
NODE_DIR="$FABRIC/peer-node"
STATE_DIR="${SPARKNET_STATE_DIR:-$NODE_DIR/.state}"
CONTEXT_DIR="${SPARKNET_CONTEXT_DIR:-/opt/sparknet/context}"
VENV="${SPARKNET_VENV:-/opt/sparknet/venv}"
COMPUTE_DIR="/opt/sparknet/compute"

log() { printf '[spark] %s\n' "$*" >&2; }
die() { printf '[spark] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'EOF'
spark-entrypoint — DGX Spark SparkNet node dispatcher

Usage: spark-entrypoint <subcommand> [args...]

Subcommands:
  vllm        serve the configured model with the fabric precontext template
  compute     run the Python compute-plane worker (infer / embed)
  kvrouter    run the KV-cache residency index daemon
  agent       run the goSpark node agent (verify signed task, execute, attest)
  control     run the goSpark control plane (Master signing key)
  gpu         run the GPU-telemetry sidecar
  nats        run the NATS/JetStream bus
  opencode    run the node's opencode server over the vault
  precontext  rebuild the precontext chat template, then exit
  shell       drop into a shell
  help        this text

Key environment (all optional; defaults shown):
  SPARKNET_NODE_ID          $(hostname)
  SPARKNET_ROLE             peer | master              (peer)
  SPARKNET_OVERLAY_IPV4     10.100.0.2 / 10.100.0.1
  SPARKNET_STATE_DIR        <vault>/.state
  SPARKNET_BUS_URL          nats://nats:4222
  SPARKNET_SHARED_SECRET    generated into the state dir if unset
  VLLM_MODEL                Qwen/Qwen2.5-32B-Instruct
  VLLM_PORT                 8000
  VLLM_GPU_MEM_UTIL         0.85
  VLLM_MAX_MODEL_LEN        65536
  VLLM_EXTRA_ARGS           (word-split; model-specific flags)
  SPARKNET_MULTIMODAL       set non-empty to add --limit-mm-per-prompt
EOF
}

# --- shared boot steps -------------------------------------------------------

ensure_state() {
  mkdir -p "$STATE_DIR"
  chmod 700 "$STATE_DIR" 2>/dev/null || true
}

ensure_env() {
  # Regenerate the vault .env (idempotent). If it cannot run, that is a real
  # fault: a node without a .env resolves a different vault, silently.
  if [ -x "$FABRIC/scripts/sparknet-env-init.sh" ]; then
    "$FABRIC/scripts/sparknet-env-init.sh" "$NODE_DIR" >/dev/null \
      || die "env-init failed — refusing to start without a resolvable vault"
  else
    log "no env-init script in the bundle; continuing (vault already materialized)"
  fi
}

ensure_secret() {
  local f="$STATE_DIR/sparknet.shared.secret"
  if [ ! -s "$f" ]; then
    if [ -n "${SPARKNET_SHARED_SECRET:-}" ]; then
      printf '%s' "$SPARKNET_SHARED_SECRET" > "$f"
    else
      head -c 32 /dev/urandom | base64 | tr -d '\n' > "$f"
    fi
    chmod 600 "$f"
  fi
  SPARKNET_SHARED_SECRET="$(cat "$f")"
  export SPARKNET_SHARED_SECRET
}

node_id()      { printf '%s' "${SPARKNET_NODE_ID:-$(hostname)}"; }
node_role()    { printf '%s' "${SPARKNET_ROLE:-peer}"; }
node_overlay() {
  if [ -n "${SPARKNET_OVERLAY_IPV4:-}" ]; then printf '%s' "$SPARKNET_OVERLAY_IPV4"; return; fi
  case "$(node_role)" in
    master) printf '10.100.0.1' ;;
    *)      printf '10.100.0.2' ;;
  esac
}

ensure_key() {  # FILE  keygen-args...
  local out="$1"; shift
  if [ ! -s "$out" ]; then
    command -v sparknetctl >/dev/null || die "sparknetctl not found; cannot mint $out"
    sparknetctl keygen "$@" -out "$out" >/dev/null
    chmod 600 "$out"
  fi
}

pub_of() { jq -r '.public_key_b64' "$1"; }

master_pub() {
  if [ -n "${SPARKNET_MASTER_PUB:-}" ]; then printf '%s' "$SPARKNET_MASTER_PUB"; return; fi
  local ck="${SPARKNET_CONTROL_KEY:-$STATE_DIR/control.key}"
  ensure_key "$ck" -node "control" -role master -overlay 10.100.0.1
  pub_of "$ck"
}

export_gospark_env() {
  # Config.Load("") + GOSPARK_* env is the whole config: no file to drift.
  export GOSPARK_NODE_ID="$(node_id)"
  export GOSPARK_OVERLAY_IPV4="$(node_overlay)"
  export GOSPARK_BUS_URL="${GOSPARK_BUS_URL:-${SPARKNET_BUS_URL:-nats://nats:4222}}"
  export GOSPARK_GATEWAY_LISTEN="${GOSPARK_GATEWAY_LISTEN:-0.0.0.0:8080}"
  export GOSPARK_GATEWAY_UPSTREAM="${GOSPARK_GATEWAY_UPSTREAM:-http://vllm:8000}"
  export GOSPARK_GATEWAY_MODEL="${GOSPARK_GATEWAY_MODEL:-${VLLM_MODEL:-Qwen/Qwen2.5-32B-Instruct}}"
  export GOSPARK_COMPUTE_ENDPOINT="${GOSPARK_COMPUTE_ENDPOINT:-http://compute:9090}"
  export GOSPARK_COMPUTE_SECRET="${GOSPARK_COMPUTE_SECRET:-$SPARKNET_SHARED_SECRET}"
  export GOSPARK_COMPUTE_OPERATIONS="${GOSPARK_COMPUTE_OPERATIONS:-infer,embed}"
  export GOSPARK_KV_ENDPOINT="${GOSPARK_KV_ENDPOINT:-http://kvrouter:9100}"
  export GOSPARK_KV_SECRET="${GOSPARK_KV_SECRET:-$SPARKNET_SHARED_SECRET}"
  export GOSPARK_LOG_LEVEL="${GOSPARK_LOG_LEVEL:-info}"
  export GOSPARK_LOG_FORMAT="${GOSPARK_LOG_FORMAT:-json}"
}

# --- precontext --------------------------------------------------------------

build_precontext() {  # -> prints the template path on stdout, or "" on failure
  local model="${VLLM_MODEL:-Qwen/Qwen2.5-32B-Instruct}"
  local out="$STATE_DIR/chat_template.jinja"
  local py
  py="$(command -v python3 || command -v python)"
  local args=(template --model "$model" --out "$out")
  [ -n "${SPARKNET_PRECONTEXT_MAX_BYTES:-}" ] && args+=(--max-bytes "$SPARKNET_PRECONTEXT_MAX_BYTES")
  local f
  for f in "$CONTEXT_DIR/masterspike-system-prompt.md" "$CONTEXT_DIR/fabric-digest.md"; do
    [ -s "$f" ] && args+=(--prompt-file "$f")
  done
  if "$py" /opt/sparknet/spark-precontext.py "${args[@]}" >&2; then
    printf '%s' "$out"
  else
    printf ''
  fi
}

# --- subcommands -------------------------------------------------------------

cmd_vllm() {
  ensure_state; ensure_env
  local model="${VLLM_MODEL:-Qwen/Qwen2.5-32B-Instruct}"
  local tmpl=""
  # Precontext is for chat models. Pooling/score/ASR models have no chat
  # template (or a nonsensical one); those services set SPARKNET_PRECONTEXT=0.
  if [ "${SPARKNET_PRECONTEXT:-1}" = "1" ]; then
    tmpl="$(build_precontext || true)"
    if [ -z "$tmpl" ] || [ ! -s "$tmpl" ]; then
      log "WARN: precontext template unavailable; serving without the fabric system prompt"
    fi
  fi

  local args=(serve "$model"
    --host 0.0.0.0
    --port "${VLLM_PORT:-8000}"
    --served-model-name "$model"
    --gpu-memory-utilization "${VLLM_GPU_MEM_UTIL:-0.85}"
    --max-model-len "${VLLM_MAX_MODEL_LEN:-65536}")
  [ "${SPARKNET_PREFIX_CACHING:-1}" = "1" ] && args+=(--enable-prefix-caching)
  [ -s "${tmpl:-}" ] && args+=(--chat-template "$tmpl")
  if [ -n "${SPARKNET_MULTIMODAL:-}" ]; then
    args+=(--limit-mm-per-prompt "${SPARKNET_MM_LIMIT:-image=4,video=1,audio=1}")
  fi
  if [ -n "${VLLM_EXTRA_ARGS:-}" ]; then
    # shellcheck disable=SC2206
    local extra=(${VLLM_EXTRA_ARGS})
    args+=("${extra[@]}")
  fi
  log "vllm serve $model (precontext: ${tmpl:-none})"
  exec vllm "${args[@]}"
}

cmd_compute() {
  ensure_state; ensure_env; ensure_secret
  export COMPUTE_LISTEN_HOST="${COMPUTE_LISTEN_HOST:-0.0.0.0}"
  export COMPUTE_LISTEN_PORT="${COMPUTE_LISTEN_PORT:-9090}"
  export VLLM_ENDPOINT="${VLLM_ENDPOINT:-http://vllm:8000/v1/chat/completions}"
  export VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen2.5-32B-Instruct}"
  log "compute worker on ${COMPUTE_LISTEN_HOST}:${COMPUTE_LISTEN_PORT} -> ${VLLM_ENDPOINT}"
  cd "$COMPUTE_DIR"
  exec "$VENV/bin/python" compute_worker.py
}

cmd_kvrouter() {
  ensure_state; ensure_env; ensure_secret
  export KV_LISTEN_HOST="${KV_LISTEN_HOST:-0.0.0.0}"
  export KV_LISTEN_PORT="${KV_LISTEN_PORT:-9100}"
  log "kv-router on ${KV_LISTEN_HOST}:${KV_LISTEN_PORT}"
  cd "$COMPUTE_DIR"
  exec "$VENV/bin/python" kv_cache_router.py
}

cmd_agent() {
  ensure_state; ensure_env; ensure_secret; export_gospark_env
  local key="${SPARKNET_NODE_KEY:-$STATE_DIR/node.key}"
  ensure_key "$key" -node "$(node_id)" -role peer -overlay "$(node_overlay)"
  local mp; mp="$(master_pub)"
  log "goSpark agent $(node_id) -> bus ${GOSPARK_BUS_URL}, gateway ${GOSPARK_GATEWAY_LISTEN}"
  local args=(-key "$key" -master-pub "$mp")
  [ -n "${GOSPARK_REGISTRY_FILE:-}" ] && args+=(-registry "$GOSPARK_REGISTRY_FILE")
  exec sparknet-agent "${args[@]}"
}

cmd_control() {
  ensure_state; ensure_env; ensure_secret; export_gospark_env
  export GOSPARK_ADMIN_LISTEN="${GOSPARK_ADMIN_LISTEN:-0.0.0.0:8899}"
  export GOSPARK_METRICS_LISTEN="${GOSPARK_METRICS_LISTEN:-0.0.0.0:9180}"
  local key="${SPARKNET_CONTROL_KEY:-$STATE_DIR/control.key}"
  ensure_key "$key" -node "${SPARKNET_CONTROL_NODE_ID:-$(node_id)}" -role master -overlay "$(node_overlay)"
  log "goSpark control plane $(node_id) -> bus ${GOSPARK_BUS_URL}, admin ${GOSPARK_ADMIN_LISTEN}"
  local args=(-master-key "$key")
  [ -n "${GOSPARK_REGISTRY_FILE:-}" ] && args+=(-registry "$GOSPARK_REGISTRY_FILE")
  [ -n "${SPARKNET_DISPATCH:-}" ] && args+=(-dispatch "$SPARKNET_DISPATCH")
  exec sparknet-control "${args[@]}"
}

cmd_gpu() {
  ensure_state; ensure_env; export_gospark_env
  log "gpu sidecar $(node_id) every ${SPARKNET_GPU_INTERVAL:-30s} on ${GOSPARK_BUS_URL}"
  exec sparknet-gpu -watch -node-id "$(node_id)" -interval "${SPARKNET_GPU_INTERVAL:-30s}"
}

cmd_nats() {
  local args=(-js -a 0.0.0.0 -p "${NATS_PORT:-4222}" -m "${NATS_MONITOR_PORT:-8222}")
  [ -n "${NATS_STORE_DIR:-}" ] && { mkdir -p "$NATS_STORE_DIR"; args+=(-sd "$NATS_STORE_DIR"); }
  if [ -n "${NATS_EXTRA_ARGS:-}" ]; then
    # shellcheck disable=SC2206
    local extra=(${NATS_EXTRA_ARGS})
    args+=("${extra[@]}")
  fi
  log "nats-server ${args[*]}"
  exec nats-server "${args[@]}"
}

cmd_opencode() {
  ensure_state; ensure_env
  log "opencode serve over $(node_id)"
  exec opencode serve --hostname "${OPENCODE_HOST:-0.0.0.0}" --port "${OPENCODE_PORT:-4200}"
}

cmd_precontext() {
  ensure_state; ensure_env
  local tmpl; tmpl="$(build_precontext || true)"
  [ -n "$tmpl" ] && [ -s "$tmpl" ] || die "precontext template build failed"
  printf '%s\n' "$tmpl"
}

# --- dispatch ----------------------------------------------------------------

case "${1:-help}" in
  --help|-h|help|"") usage; exit 0 ;;
  vllm)       shift; cmd_vllm "$@" ;;
  compute)    shift; cmd_compute "$@" ;;
  kvrouter)   shift; cmd_kvrouter "$@" ;;
  agent)      shift; cmd_agent "$@" ;;
  control)    shift; cmd_control "$@" ;;
  gpu)        shift; cmd_gpu "$@" ;;
  nats)       shift; cmd_nats "$@" ;;
  opencode)   shift; cmd_opencode "$@" ;;
  precontext) shift; cmd_precontext "$@" ;;
  shell)      shift; exec /bin/bash "$@" ;;
  *) echo "spark-entrypoint: unknown subcommand: $1" >&2; usage >&2; exit 2 ;;
esac
