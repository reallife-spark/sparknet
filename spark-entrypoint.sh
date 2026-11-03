#!/usr/bin/env bash
# spark-entrypoint — the node's one dispatcher (DGX Spark and AGX Xavier).
#
# `spark.compose.yml` and `goagx/sparknet.agx.compose.yml` run THIS SAME
# SCRIPT with a different subcommand per service, so the whole node (engine,
# control plane, compute plane, bundle, precontext) is one image and one code
# path:
#
#   vllm         the OpenAI engine server, with the fabric precontext chat
#                template (VLLM_CLI picks the engine: `vllm serve` on the
#                Spark image, the source-built module on AGX)
#   compute      the Python compute-plane worker (infer/embed) beside the GPU
#   kvrouter     the RadixAttention / KV-residency index daemon
#   agent        a goSpark node: verifies signed tasks, executes, attests
#   control      the goSpark control plane (holds the Master signing key)
#   gpu          the cgo GPU-telemetry sidecar (degrades: available=false + reason)
#   nats         the NATS/JetStream bus the goSpark plane runs on
#   ingest       crawl the vault and refresh the RAG index (one-shot)
#   backup       the signed vault-snapshot daemon
#   opencode     the node's agent surface over the vault
#   llama-embed  AGX: llama.cpp embeddings server (baked GGUF)
#   llama-rerank AGX: llama.cpp reranking server (baked GGUF)
#   whisper-asr  AGX: whisper.cpp ASR behind the OpenAI transcriptions shim
#   precontext   (re)build the chat template only, then exit
#   shell        drop to a shell in the node image
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
spark-entrypoint — SparkNet node dispatcher (DGX Spark / AGX Xavier)

Usage: spark-entrypoint <subcommand> [args...]

Subcommands:
  vllm        serve the configured model with the fabric precontext template
              (engine from VLLM_CLI; flags newer than the engine are skipped)
  vllm-stub   serve a CPU-only OpenAI-compatible stub (no GPU / no model)
  compute     run the Python compute-plane worker (infer / embed)
  kvrouter    run the KV-cache residency index daemon
  agent       run the goSpark node agent (verify signed task, execute, attest)
  control     run the goSpark control plane (Master signing key)
  gpu         run the GPU-telemetry sidecar
  nats        run the NATS/JetStream bus
  ingest      crawl the vault and refresh the RAG index (one-shot)
  backup      run the signed vault-snapshot daemon
  memory      run the per-vault typed memory service (loopback 4110)
  memory-gateway  run the authority gateway in front of memory (loopback 4093)
  opencode    run the node's opencode server over the vault
  llama-embed  embeddings over the baked GGUF (LLAMA_EMBED_* env)
  llama-rerank reranking over the baked GGUF (LLAMA_RERANK_* env)
  whisper-asr  whisper.cpp ASR behind OpenAI /v1/audio/transcriptions
               (WHISPER_* env; needs ffmpeg for non-WAV uploads)
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
  VLLM_CLI                  vllm serve  (AGX image sets
                            "python3 -m vllm.entrypoints.openai.api_server")
  VLLM_MODEL                Qwen/Qwen2.5-32B-Instruct (AGX: Mistral-7B)
  VLLM_PORT                 8000
  VLLM_GPU_MEM_UTIL         0.85
  VLLM_MAX_MODEL_LEN        65536
  VLLM_EXTRA_ARGS           (word-split; model-specific flags)
  SPARKNET_MULTIMODAL       set non-empty to add --limit-mm-per-prompt
                            (engines without the flag ignore this branch)
  LLAMA_EMBED_MODEL         /opt/sparknet/models/bge-m3-q8_0.gguf
  LLAMA_RERANK_MODEL        /opt/sparknet/models/bge-reranker-v2-m3-Q4_K_M.gguf
  WHISPER_MODEL             /opt/sparknet/models/ggml-small-q5_1.bin
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
  # Fail closed on a joined node: a registry is adopted against a PINNED key. If
  # the key is missing here the node would fall through to its own self-minted
  # control key, which the Master-signed registry does not cover — the agent
  # would then run with a trust anchor that authorises nothing (or, worse, an
  # operator could mistake the failure for open mode). The setup script always
  # writes SPARKNET_MASTER_PUB whenever a registry is staged, so this only trips
  # a hand-edited or partial environment.
  if [ -n "${GOSPARK_REGISTRY_FILE:-}" ]; then
    die "GOSPARK_REGISTRY_FILE is set but SPARKNET_MASTER_PUB is empty — pass --master-pub (or a registry whose master_public_key_b64 is readable)"
  fi
  local ck="${SPARKNET_CONTROL_KEY:-$STATE_DIR/control.key}"
  ensure_key "$ck" -node "control" -role master -overlay 10.100.0.1
  pub_of "$ck"
}

export_gospark_env() {
  # Config.Load("") + GOSPARK_* env is the whole config: no file to drift.
  # Assigned then exported, so a failure in node_id/node_overlay aborts here
  # instead of exporting an empty value (the entrypoint is fail-closed).
  GOSPARK_NODE_ID="$(node_id)"
  export GOSPARK_NODE_ID
  GOSPARK_OVERLAY_IPV4="$(node_overlay)"
  export GOSPARK_OVERLAY_IPV4
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
  for f in "${SPARKNET_NODE_DIR:-/srv/sparknet/peer-node}/CONTEXT.md" \
           "$CONTEXT_DIR/masterspike-system-prompt.md" "$CONTEXT_DIR/fabric-digest.md"; do
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

  # VLLM_CLI is the whole engine command (`vllm serve` on the Spark image; a
  # module path on AGX, where the source-built vLLM 0.2.x has no `vllm`
  # subcommand). If the command ends in `serve`, the model is the first
  # positional after it; anything else gets --model. The two newer-engine
  # switches below (prefix caching, multimodal limits) are only passed when
  # the engine is the modern CLI — vLLM 0.2.x has neither flag and would
  # exit on an unknown argument; its knobs travel through VLLM_EXTRA_ARGS.
  # shellcheck disable=SC2206
  local cli=(${VLLM_CLI:-vllm serve})
  local modern=0
  local -a args=()
  if [ "${cli[-1]}" = "serve" ]; then
    cli=("${cli[@]::${#cli[@]}-1}")
    args=(serve "$model")
    modern=1
  else
    args=(--model "$model")
  fi
  args+=(
    --host 0.0.0.0
    --port "${VLLM_PORT:-8000}"
    --served-model-name "$model"
    --gpu-memory-utilization "${VLLM_GPU_MEM_UTIL:-0.85}"
    --max-model-len "${VLLM_MAX_MODEL_LEN:-65536}")
  if [ "$modern" = 1 ] && [ "${SPARKNET_PREFIX_CACHING:-1}" = "1" ]; then
    args+=(--enable-prefix-caching)
  fi
  [ -s "${tmpl:-}" ] && args+=(--chat-template "$tmpl")
  if [ "$modern" = 1 ] && [ -n "${SPARKNET_MULTIMODAL:-}" ]; then
    args+=(--limit-mm-per-prompt "${SPARKNET_MM_LIMIT:-image=4,video=1,audio=1}")
  fi
  if [ -n "${VLLM_EXTRA_ARGS:-}" ]; then
    # shellcheck disable=SC2206
    local extra=(${VLLM_EXTRA_ARGS})
    args+=("${extra[@]}")
  fi
  log "${cli[*]} ${args[*]} (precontext: ${tmpl:-none})"
  exec "${cli[@]}" "${args[@]}"
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

# The goSpark knowledge indexer: crawl the vault, chunk, embed through the
# compute plane, write the RAG index. One-shot by design (the binary has no
# daemon mode): enabling it at `up` refreshes the index once, and it exits.
# Re-run with `docker compose ... --profile ingest run --rm ingest`.
cmd_ingest() {
  ensure_state; ensure_env; ensure_secret
  local vault="${GOSPARK_KNOWLEDGE_DIR:-$NODE_DIR}"
  local out="${GOSPARK_INGEST_OUT:-$STATE_DIR/rag/index.json}"
  mkdir -p "$(dirname "$out")"
  export GOSPARK_KNOWLEDGE_DIR="$vault"
  export GOSPARK_EMBED_SECRET="${GOSPARK_EMBED_SECRET:-$SPARKNET_SHARED_SECRET}"
  local args=(-root "$vault" -out "$out")
  [ -n "${GOSPARK_EMBED_ENDPOINT:-}" ] && args+=(-embed-endpoint "$GOSPARK_EMBED_ENDPOINT")
  [ -n "${GOSPARK_EMBED_MODEL:-}" ] && args+=(-embed-model "$GOSPARK_EMBED_MODEL")
  log "ingest $vault -> $out (embed ${GOSPARK_EMBED_ENDPOINT:-none})"
  exec sparknet-ingest "${args[@]}"
}

# The goSpark signed-backup daemon: hash the vault, copy it under the target and
# write a node-signed manifest, every interval. Signed with the SAME node key as
# the agent (one path, one identity), so a restore can tell a faithful snapshot
# from a tampered one.
cmd_backup() {
  ensure_state; ensure_env; ensure_secret; export_gospark_env
  local key="${SPARKNET_NODE_KEY:-$STATE_DIR/node.key}"
  ensure_key "$key" -node "$(node_id)" -role peer -overlay "$(node_overlay)"
  local source="${GOSPARK_BACKUP_SOURCE:-$NODE_DIR}"
  local target="${GOSPARK_BACKUP_TARGET:-/srv/sparknet/backups}"
  local interval="${GOSPARK_BACKUP_INTERVAL:-6h}"
  mkdir -p "$target"
  local args=(run -source "$source" -target "$target" -key "$key" -interval "$interval")
  [ -n "${GOSPARK_BACKUP_SKIP_DIRS:-}" ] && args+=(-skip-dirs "$GOSPARK_BACKUP_SKIP_DIRS")
  log "backup $source -> $target every $interval (key $key)"
  exec sparknet-backup "${args[@]}"
}

# The per-vault typed memory service. It stores records and delegate runs; it
# holds no key and trusts only the gateway token. The token is generated once
# into the host state dir when the setup script has not already written it.
cmd_memory_gateway() {
  ensure_state; ensure_env
  local role="${SPARKNET_ROLE:-peer}"
  local webui="${SPARKNET_WEBUI_URL:-http://127.0.0.1:8180}"
  [ "$role" = master ] && webui="${SPARKNET_WEBUI_URL:-http://127.0.0.1:8080}"
  local args=(--role "$role" --bind "${SPARKNET_MEMORY_GATEWAY_BIND:-127.0.0.1:4093}"
    --vault-root "$NODE_DIR" --vault-root /srv/sparknet/knowledge
    --user-vault-root /srv/sparknet/knowledge --webui-url "$webui")
  log "memory-gateway $role on ${SPARKNET_MEMORY_GATEWAY_BIND:-127.0.0.1:4093} -> ${SPARKNET_MEMORY_URL:-http://127.0.0.1:4110}"
  exec "$FABRIC/shared/sparknet-memory-gateway.py" "${args[@]}"
}

cmd_memory() {
  ensure_state; ensure_env
  local token="${GOSPARK_MEMORY_GATEWAY_TOKEN:-}"
  local token_file="$STATE_DIR/memory.gateway.token"
  if [ -z "$token" ] && [ -s "$token_file" ]; then
    token="$(cat "$token_file")"
  fi
  if [ -z "$token" ]; then
    token="$(head -c 32 /dev/urandom | base64 | tr -d '\n')"
    printf '%s' "$token" > "$token_file"
    chmod 600 "$token_file"
  fi
  export GOSPARK_MEMORY_GATEWAY_TOKEN="$token"
  local roots="${GOSPARK_MEMORY_VAULT_ROOTS:-$NODE_DIR,/srv/sparknet/knowledge}"
  local args=(-listen "${GOSPARK_MEMORY_LISTEN:-127.0.0.1:4110}" -state "${GOSPARK_MEMORY_STATE:-$STATE_DIR/memory}" -node-id "$(node_id)")
  local root
  IFS=',' read -r -a root_list <<< "$roots"
  for root in "${root_list[@]}"; do
    [ -n "$root" ] && args+=(-vault-root "$root")
  done
  mkdir -p "$STATE_DIR/memory"
  chmod 700 "$STATE_DIR/memory" 2>/dev/null || true
  log "memory $(node_id) on ${GOSPARK_MEMORY_LISTEN:-127.0.0.1:4110} roots=$roots"
  exec sparknet-memory "${args[@]}"
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

# --- vllm stub (CPU-only) -----------------------------------------------------
cmd_vllm_stub() {
  local model="${VLLM_MODEL:-Qwen/Qwen2.5-32B-Instruct}"
  local port="${VLLM_PORT:-8000}"
  log "vllm-stub serving $model on 0.0.0.0:$port"
  exec stub-vllm -model "$model" -port "$port" -host 0.0.0.0
}

# --- aux engines (the AGX image's multimodal services) -------------------------
# Each checks its engine and baked model up front — a missing GGUF is a build
# error with a clear message, not a crash loop — runs the shared boot steps,
# then execs in the foreground, same contract as every other subcommand. All
# three are CPU-only by design: the GPU belongs to the text model.

cmd_llama_embed() {
  ensure_state; ensure_env
  command -v llama-server >/dev/null || die "llama-server not found in this image"
  local model="${LLAMA_EMBED_MODEL:-/opt/sparknet/models/bge-m3-q8_0.gguf}"
  [ -s "$model" ] || die "embed model missing: $model (image bake step failed?)"
  local port="${VLLM_PORT:-8001}"
  local args=(--host 0.0.0.0 --port "$port" --model "$model"
    --embedding --pooling mean
    --alias "${LLAMA_EMBED_ALIAS:-bge-m3}"
    --ctx-size "${LLAMA_EMBED_CTX:-512}")
  if [ -n "${LLAMA_EMBED_EXTRA_ARGS:-}" ]; then
    # shellcheck disable=SC2206
    local extra=(${LLAMA_EMBED_EXTRA_ARGS})
    args+=("${extra[@]}")
  fi
  log "llama-embed $model on 0.0.0.0:$port (OpenAI /v1/embeddings)"
  exec llama-server "${args[@]}"
}

cmd_llama_rerank() {
  ensure_state; ensure_env
  command -v llama-server >/dev/null || die "llama-server not found in this image"
  local model="${LLAMA_RERANK_MODEL:-/opt/sparknet/models/bge-reranker-v2-m3-Q4_K_M.gguf}"
  [ -s "$model" ] || die "rerank model missing: $model (image bake step failed?)"
  local port="${VLLM_PORT:-8002}"
  # --reranking implies embedding + rank pooling inside llama.cpp; the server
  # then answers both /v1/rerank and /v1/reranking (jina and cohere shapes).
  local args=(--host 0.0.0.0 --port "$port" --model "$model"
    --reranking
    --alias "${LLAMA_RERANK_ALIAS:-bge-reranker-v2-m3}"
    --ctx-size "${LLAMA_RERANK_CTX:-512}")
  if [ -n "${LLAMA_RERANK_EXTRA_ARGS:-}" ]; then
    # shellcheck disable=SC2206
    local extra=(${LLAMA_RERANK_EXTRA_ARGS})
    args+=("${extra[@]}")
  fi
  log "llama-rerank $model on 0.0.0.0:$port (OpenAI/Cohere /v1/rerank)"
  exec llama-server "${args[@]}"
}

cmd_whisper_asr() {
  ensure_state; ensure_env
  command -v whisper-server >/dev/null || die "whisper-server not found in this image"
  local model="${WHISPER_MODEL:-/opt/sparknet/models/ggml-small-q5_1.bin}"
  [ -s "$model" ] || die "whisper model missing: $model (image bake step failed?)"
  local port="${VLLM_PORT:-8003}"
  local up="${WHISPER_UPSTREAM_PORT:-8004}"
  # --convert makes whisper accept whatever an OpenAI client uploads (webm,
  # ogg, mp3) and needs ffmpeg — installed by the AGX image for this purpose.
  # The engine stays on loopback; only the shim is published.
  local wargs=(--host 127.0.0.1 --port "$up" --model "$model" --convert)
  [ -n "${WHISPER_LANGUAGE:-}" ] && wargs+=(--language "$WHISPER_LANGUAGE")
  if [ -n "${WHISPER_EXTRA_ARGS:-}" ]; then
    # shellcheck disable=SC2206
    local wextra=(${WHISPER_EXTRA_ARGS})
    wargs+=("${wextra[@]}")
  fi
  log "whisper-asr: whisper-server on 127.0.0.1:$up + OpenAI shim on 0.0.0.0:$port"
  whisper-server "${wargs[@]}" &
  local wpid=$!
  WHISPER_UPSTREAM="http://127.0.0.1:$up" "$VENV/bin/python" -m uvicorn \
    --app-dir /opt/sparknet audio_shim:app --host 0.0.0.0 --port "$port" &
  local shim_pid=$!
  trap 'kill "$wpid" "$shim_pid" 2>/dev/null || true' EXIT TERM INT
  # Supervise both: whichever exits first takes the container down, so compose
  # restarts it instead of leaving half an audio stack running.
  wait -n "$wpid" "$shim_pid"
}

# --- dispatch ----------------------------------------------------------------

case "${1:-help}" in
  --help|-h|help|"") usage; exit 0 ;;
  vllm)         shift; cmd_vllm "$@" ;;
  vllm-stub)    shift; cmd_vllm_stub "$@" ;;
  compute)      shift; cmd_compute "$@" ;;
  kvrouter)     shift; cmd_kvrouter "$@" ;;
  agent)        shift; cmd_agent "$@" ;;
  control)      shift; cmd_control "$@" ;;
  gpu)          shift; cmd_gpu "$@" ;;
  nats)         shift; cmd_nats "$@" ;;
  ingest)       shift; cmd_ingest "$@" ;;
  backup)       shift; cmd_backup "$@" ;;
  memory)       shift; cmd_memory "$@" ;;
  memory-gateway) shift; cmd_memory_gateway "$@" ;;
  opencode)     shift; cmd_opencode "$@" ;;
  llama-embed)  shift; cmd_llama_embed "$@" ;;
  llama-rerank) shift; cmd_llama_rerank "$@" ;;
  whisper-asr)  shift; cmd_whisper_asr "$@" ;;
  precontext)   shift; cmd_precontext "$@" ;;
  shell)        shift; exec /bin/bash "$@" ;;
  *) echo "spark-entrypoint: unknown subcommand: $1" >&2; usage >&2; exit 2 ;;
esac
