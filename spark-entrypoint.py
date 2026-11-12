#!/usr/bin/env python3
"""spark-entrypoint — the node's one dispatcher (DGX Spark and AGX Xavier).

The shell file beside this one is a thin exec wrapper; this module is the
implementation. `spark.compose.yml` and `goagx/sparknet.agx.compose.yml` run the
same dispatcher with a different subcommand per service, so the whole node is
one image and one code path.

Nothing here bakes a vault path or a secret. The sparknet .env is regenerated at
boot, keys live in the host-mounted $SPARKNET_STATE_DIR, and the shared secret
is generated once into that state dir.

Python 3.8-compatible: this file runs inside the AGX image as well as the Spark
image.
"""

from __future__ import annotations

import contextlib
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import NoReturn

FABRIC = Path(os.environ.get("SPARKNET_FABRIC_ROOT") or "/srv/sparknet")
NODE_DIR = FABRIC / "peer-node"
STATE_DIR = Path(os.environ.get("SPARKNET_STATE_DIR") or (NODE_DIR / ".state"))
CONTEXT_DIR = Path(os.environ.get("SPARKNET_CONTEXT_DIR") or "/opt/sparknet/context")
VENV = Path(os.environ.get("SPARKNET_VENV") or "/opt/sparknet/venv")
COMPUTE_DIR = Path("/opt/sparknet/compute")
DEFAULT_MODEL = "Qwen/Qwen2.5-32B-Instruct"
DEFAULT_OVERLAY = "10.100.0.2"
ALL_INTERFACES = "0.0.0.0"  # noqa: S104 - container services bind their interface
GATEWAY_LISTEN_DEFAULT = ALL_INTERFACES + ":8080"
ADMIN_LISTEN_DEFAULT = ALL_INTERFACES + ":8899"
METRICS_LISTEN_DEFAULT = ALL_INTERFACES + ":9180"

USAGE = """spark-entrypoint — SparkNet node dispatcher (DGX Spark / AGX Xavier)

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
"""


def log(message: str) -> None:
    print(f"[spark] {message}", file=sys.stderr, flush=True)


def die(message: str) -> NoReturn:
    print(f"[spark] ERROR: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def _exec(command: str, args: list[str], *, env: dict[str, str] | None = None) -> NoReturn:
    try:
        os.execvpe(command, [command, *args], env if env is not None else os.environ)  # noqa: S606 - fixed argv
    except FileNotFoundError:
        print(f"spark-entrypoint: {command}: not found", file=sys.stderr, flush=True)
        raise SystemExit(127) from None


def _run(command: str, args: list[str], *, stdout: object = subprocess.DEVNULL) -> int:
    try:
        return subprocess.run([command, *args], stdout=stdout, check=False).returncode
    except FileNotFoundError:
        print(f"spark-entrypoint: {command}: not found", file=sys.stderr, flush=True)
        raise SystemExit(127) from None


def ensure_state() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        STATE_DIR.chmod(0o700)


def ensure_env() -> None:
    script = FABRIC / "scripts" / "sparknet-env-init.sh"
    if script.is_file() and os.access(script, os.X_OK):
        if _run(str(script), [str(NODE_DIR)]) != 0:
            die("env-init failed — refusing to start without a resolvable vault")
    else:
        log("no env-init script in the bundle; continuing (vault already materialized)")


def ensure_secret() -> None:
    path = STATE_DIR / "sparknet.shared.secret"
    if not (path.is_file() and path.stat().st_size):
        supplied = os.environ.get("SPARKNET_SHARED_SECRET")
        if supplied:
            path.write_text(supplied, encoding="utf-8")
        else:
            path.write_bytes(os.urandom(32))
            import base64

            path.write_text(base64.b64encode(path.read_bytes()).decode(), encoding="utf-8")
        path.chmod(0o600)
    os.environ["SPARKNET_SHARED_SECRET"] = path.read_text(encoding="utf-8")


def node_id() -> str:
    return os.environ.get("SPARKNET_NODE_ID") or os.uname().nodename


def node_role() -> str:
    return os.environ.get("SPARKNET_ROLE") or "peer"


def node_overlay() -> str:
    explicit = os.environ.get("SPARKNET_OVERLAY_IPV4")
    if explicit:
        return explicit
    return "10.100.0.1" if node_role() == "master" else DEFAULT_OVERLAY


def ensure_key(path: Path, *args: str) -> None:
    if path.is_file() and path.stat().st_size:
        return
    if shutil.which("sparknetctl") is None:
        die(f"sparknetctl not found; cannot mint {path}")
    if _run("sparknetctl", ["keygen", *args, "-out", str(path)]) != 0:
        die(f"sparknetctl keygen failed for {path}")
    path.chmod(0o600)


def pub_of(path: Path) -> str:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        value = document["public_key_b64"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        die(f"cannot read public_key_b64 from {path}: {exc}")
    if not isinstance(value, str) or not value:
        die(f"{path} holds no public_key_b64")
    return value


def master_pub() -> str:
    pinned = os.environ.get("SPARKNET_MASTER_PUB")
    if pinned:
        return pinned
    if os.environ.get("GOSPARK_REGISTRY_FILE"):
        die(
            "GOSPARK_REGISTRY_FILE is set but SPARKNET_MASTER_PUB is empty — pass --master-pub "
            "(or a registry whose master_public_key_b64 is readable)"
        )
    control = Path(os.environ.get("SPARKNET_CONTROL_KEY") or (STATE_DIR / "control.key"))
    ensure_key(control, "-node", "control", "-role", "master", "-overlay", "10.100.0.1")
    return pub_of(control)


def export_gospark_env() -> None:
    secrets = os.environ.get("SPARKNET_SHARED_SECRET", "")
    mapping = {
        "GOSPARK_NODE_ID": node_id(),
        "GOSPARK_OVERLAY_IPV4": node_overlay(),
        "GOSPARK_BUS_URL": os.environ.get("GOSPARK_BUS_URL")
        or os.environ.get("SPARKNET_BUS_URL")
        or "nats://nats:4222",
        "GOSPARK_GATEWAY_LISTEN": os.environ.get("GOSPARK_GATEWAY_LISTEN") or GATEWAY_LISTEN_DEFAULT,
        "GOSPARK_GATEWAY_UPSTREAM": os.environ.get("GOSPARK_GATEWAY_UPSTREAM") or "http://vllm:8000",
        "GOSPARK_GATEWAY_MODEL": os.environ.get("GOSPARK_GATEWAY_MODEL")
        or os.environ.get("VLLM_MODEL")
        or DEFAULT_MODEL,
        "GOSPARK_COMPUTE_ENDPOINT": os.environ.get("GOSPARK_COMPUTE_ENDPOINT") or "http://compute:9090",
        "GOSPARK_COMPUTE_SECRET": os.environ.get("GOSPARK_COMPUTE_SECRET") or secrets,
        "GOSPARK_COMPUTE_OPERATIONS": os.environ.get("GOSPARK_COMPUTE_OPERATIONS") or "infer,embed",
        "GOSPARK_KV_ENDPOINT": os.environ.get("GOSPARK_KV_ENDPOINT") or "http://kvrouter:9100",
        "GOSPARK_KV_SECRET": os.environ.get("GOSPARK_KV_SECRET") or secrets,
        "GOSPARK_LOG_LEVEL": os.environ.get("GOSPARK_LOG_LEVEL") or "info",
        "GOSPARK_LOG_FORMAT": os.environ.get("GOSPARK_LOG_FORMAT") or "json",
    }
    for key, value in mapping.items():
        os.environ[key] = value


def build_precontext() -> str:
    model = os.environ.get("VLLM_MODEL") or DEFAULT_MODEL
    out = STATE_DIR / "chat_template.jinja"
    python = shutil.which("python3") or shutil.which("python")
    if python is None:
        return ""
    args = ["template", "--model", model, "--out", str(out)]
    max_bytes = os.environ.get("SPARKNET_PRECONTEXT_MAX_BYTES")
    if max_bytes:
        args.extend(["--max-bytes", max_bytes])
    for candidate in (
        Path(os.environ.get("SPARKNET_NODE_DIR") or str(NODE_DIR)) / "CONTEXT.md",
        CONTEXT_DIR / "masterspike-system-prompt.md",
        CONTEXT_DIR / "fabric-digest.md",
    ):
        if candidate.is_file() and candidate.stat().st_size:
            args.extend(["--prompt-file", str(candidate)])
    try:
        completed = subprocess.run(
            [python, "/opt/sparknet/spark-precontext.py", *args],
            stdout=sys.stderr,
            check=False,
        )
    except OSError:
        return ""
    return str(out) if completed.returncode == 0 else ""


def cmd_vllm(_args: list[str]) -> NoReturn:
    ensure_state()
    ensure_env()
    model = os.environ.get("VLLM_MODEL") or DEFAULT_MODEL
    template = ""
    if os.environ.get("SPARKNET_PRECONTEXT", "1") == "1":
        template = build_precontext()
        if not template or not Path(template).is_file() or not Path(template).stat().st_size:
            log("WARN: precontext template unavailable; serving without the fabric system prompt")

    cli = (os.environ.get("VLLM_CLI") or "vllm serve").split()
    modern = False
    if cli and cli[-1] == "serve":
        cli = cli[:-1]
        args = ["serve", model]
        modern = True
    else:
        args = ["--model", model]
    args.extend(
        [
            "--host",
            ALL_INTERFACES,
            "--port",
            os.environ.get("VLLM_PORT") or "8000",
            "--served-model-name",
            model,
            "--gpu-memory-utilization",
            os.environ.get("VLLM_GPU_MEM_UTIL") or "0.85",
            "--max-model-len",
            os.environ.get("VLLM_MAX_MODEL_LEN") or "65536",
        ]
    )
    if modern and os.environ.get("SPARKNET_PREFIX_CACHING", "1") == "1":
        args.append("--enable-prefix-caching")
    if template:
        args.extend(["--chat-template", template])
    if modern and os.environ.get("SPARKNET_MULTIMODAL"):
        args.extend(["--limit-mm-per-prompt", os.environ.get("SPARKNET_MM_LIMIT") or "image=4,video=1,audio=1"])
    extra = os.environ.get("VLLM_EXTRA_ARGS")
    if extra:
        args.extend(shlex.split(extra))
    log(f"{' '.join(cli)} {' '.join(args)} (precontext: {template or 'none'})")
    if not cli:
        die("VLLM_CLI is empty")
    _exec(cli[0], [*cli[1:], *args])


def cmd_compute(_args: list[str]) -> NoReturn:
    ensure_state()
    ensure_env()
    ensure_secret()
    os.environ["COMPUTE_LISTEN_HOST"] = os.environ.get("COMPUTE_LISTEN_HOST") or ALL_INTERFACES
    os.environ["COMPUTE_LISTEN_PORT"] = os.environ.get("COMPUTE_LISTEN_PORT") or "9090"
    os.environ["VLLM_ENDPOINT"] = os.environ.get("VLLM_ENDPOINT") or "http://vllm:8000/v1/chat/completions"
    os.environ["VLLM_MODEL"] = os.environ.get("VLLM_MODEL") or DEFAULT_MODEL
    log(
        f"compute worker on {os.environ['COMPUTE_LISTEN_HOST']}:{os.environ['COMPUTE_LISTEN_PORT']} "
        f"-> {os.environ['VLLM_ENDPOINT']}"
    )
    os.chdir(COMPUTE_DIR)
    _exec(str(VENV / "bin" / "python"), ["compute_worker.py"])


def cmd_kvrouter(_args: list[str]) -> NoReturn:
    ensure_state()
    ensure_env()
    ensure_secret()
    os.environ.setdefault("KV_LISTEN_HOST", ALL_INTERFACES)
    os.environ.setdefault("KV_LISTEN_PORT", "9100")
    log(f"kv-router on {os.environ['KV_LISTEN_HOST']}:{os.environ['KV_LISTEN_PORT']}")
    os.chdir(COMPUTE_DIR)
    _exec(str(VENV / "bin" / "python"), ["kv_cache_router.py"])


def cmd_agent(_args: list[str]) -> NoReturn:
    ensure_state()
    ensure_env()
    ensure_secret()
    export_gospark_env()
    key = Path(os.environ.get("SPARKNET_NODE_KEY") or (STATE_DIR / "node.key"))
    ensure_key(key, "-node", node_id(), "-role", "peer", "-overlay", node_overlay())
    pinned = master_pub()
    log(
        f"goSpark agent {node_id()} -> bus {os.environ['GOSPARK_BUS_URL']}, "
        f"gateway {os.environ['GOSPARK_GATEWAY_LISTEN']}"
    )
    args = ["-key", str(key), "-master-pub", pinned]
    registry = os.environ.get("GOSPARK_REGISTRY_FILE")
    if registry:
        args.extend(["-registry", registry])
    _exec("sparknet-agent", args)


def cmd_control(_args: list[str]) -> NoReturn:
    ensure_state()
    ensure_env()
    ensure_secret()
    export_gospark_env()
    os.environ.setdefault("GOSPARK_ADMIN_LISTEN", ADMIN_LISTEN_DEFAULT)
    os.environ.setdefault("GOSPARK_METRICS_LISTEN", METRICS_LISTEN_DEFAULT)
    key = Path(os.environ.get("SPARKNET_CONTROL_KEY") or (STATE_DIR / "control.key"))
    ensure_key(
        key,
        "-node",
        os.environ.get("SPARKNET_CONTROL_NODE_ID") or node_id(),
        "-role",
        "master",
        "-overlay",
        node_overlay(),
    )
    log(
        f"goSpark control plane {node_id()} -> bus {os.environ['GOSPARK_BUS_URL']}, "
        f"admin {os.environ['GOSPARK_ADMIN_LISTEN']}"
    )
    args = ["-master-key", str(key)]
    registry = os.environ.get("GOSPARK_REGISTRY_FILE")
    if registry:
        args.extend(["-registry", registry])
    if os.environ.get("SPARKNET_DISPATCH"):
        args.extend(["-dispatch", os.environ["SPARKNET_DISPATCH"]])
    _exec("sparknet-control", args)


def cmd_gpu(_args: list[str]) -> NoReturn:
    ensure_state()
    ensure_env()
    export_gospark_env()
    interval = os.environ.get("SPARKNET_GPU_INTERVAL") or "30s"
    log(f"gpu sidecar {node_id()} every {interval} on {os.environ['GOSPARK_BUS_URL']}")
    _exec("sparknet-gpu", ["-watch", "-node-id", node_id(), "-interval", interval])


def cmd_nats(_args: list[str]) -> NoReturn:
    args = [
        "-js",
        "-a",
        ALL_INTERFACES,
        "-p",
        os.environ.get("NATS_PORT") or "4222",
        "-m",
        os.environ.get("NATS_MONITOR_PORT") or "8222",
    ]
    store = os.environ.get("NATS_STORE_DIR")
    if store:
        Path(store).mkdir(parents=True, exist_ok=True)
        args.extend(["-sd", store])
    extra = os.environ.get("NATS_EXTRA_ARGS")
    if extra:
        args.extend(shlex.split(extra))
    log(f"nats-server {' '.join(args)}")
    _exec("nats-server", args)


def cmd_ingest(_args: list[str]) -> NoReturn:
    ensure_state()
    ensure_env()
    ensure_secret()
    vault = os.environ.get("GOSPARK_KNOWLEDGE_DIR") or str(NODE_DIR)
    out = os.environ.get("GOSPARK_INGEST_OUT") or str(STATE_DIR / "rag" / "index.json")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    os.environ["GOSPARK_KNOWLEDGE_DIR"] = vault
    os.environ["GOSPARK_EMBED_SECRET"] = os.environ.get("GOSPARK_EMBED_SECRET") or os.environ.get(
        "SPARKNET_SHARED_SECRET", ""
    )
    args = ["-root", vault, "-out", out]
    if os.environ.get("GOSPARK_EMBED_ENDPOINT"):
        args.extend(["-embed-endpoint", os.environ["GOSPARK_EMBED_ENDPOINT"]])
    if os.environ.get("GOSPARK_EMBED_MODEL"):
        args.extend(["-embed-model", os.environ["GOSPARK_EMBED_MODEL"]])
    log(f"ingest {vault} -> {out} (embed {os.environ.get('GOSPARK_EMBED_ENDPOINT') or 'none'})")
    _exec("sparknet-ingest", args)


def cmd_backup(_args: list[str]) -> NoReturn:
    ensure_state()
    ensure_env()
    ensure_secret()
    export_gospark_env()
    key = Path(os.environ.get("SPARKNET_NODE_KEY") or (STATE_DIR / "node.key"))
    ensure_key(key, "-node", node_id(), "-role", "peer", "-overlay", node_overlay())
    source = os.environ.get("GOSPARK_BACKUP_SOURCE") or str(NODE_DIR)
    target = os.environ.get("GOSPARK_BACKUP_TARGET") or "/srv/sparknet/backups"
    interval = os.environ.get("GOSPARK_BACKUP_INTERVAL") or "6h"
    Path(target).mkdir(parents=True, exist_ok=True)
    args = ["run", "-source", source, "-target", target, "-key", str(key), "-interval", interval]
    if os.environ.get("GOSPARK_BACKUP_SKIP_DIRS"):
        args.extend(["-skip-dirs", os.environ["GOSPARK_BACKUP_SKIP_DIRS"]])
    log(f"backup {source} -> {target} every {interval} (key {key})")
    _exec("sparknet-backup", args)


def cmd_memory_gateway(_args: list[str]) -> NoReturn:
    ensure_state()
    ensure_env()
    role = os.environ.get("SPARKNET_ROLE") or "peer"
    webui = os.environ.get("SPARKNET_WEBUI_URL") or (
        "http://127.0.0.1:8080" if role == "master" else "http://127.0.0.1:8180"
    )
    bind = os.environ.get("SPARKNET_MEMORY_GATEWAY_BIND") or "127.0.0.1:4093"
    args = [
        "--role",
        role,
        "--bind",
        bind,
        "--vault-root",
        str(NODE_DIR),
        "--vault-root",
        "/srv/sparknet/knowledge",
        "--user-vault-root",
        "/srv/sparknet/knowledge",
        "--webui-url",
        webui,
    ]
    log(f"memory-gateway {role} on {bind} -> {os.environ.get('SPARKNET_MEMORY_URL') or 'http://127.0.0.1:4110'}")
    # The gateway imports cryptography, which lives in the image venv, not in
    # the system interpreter that launches the thin dispatcher wrapper.
    interpreter = VENV / "bin" / "python"
    if not interpreter.is_file():
        interpreter = Path(sys.executable)
    _exec(str(interpreter), [str(FABRIC / "shared" / "sparknet-memory-gateway.py"), *args])


def cmd_memory(_args: list[str]) -> NoReturn:
    ensure_state()
    ensure_env()
    token = os.environ.get("GOSPARK_MEMORY_GATEWAY_TOKEN") or ""
    token_file = STATE_DIR / "memory.gateway.token"
    if not token and token_file.is_file() and token_file.stat().st_size:
        token = token_file.read_text(encoding="utf-8")
    if not token:
        import base64

        token = base64.b64encode(os.urandom(32)).decode()
        token_file.write_text(token, encoding="utf-8")
        token_file.chmod(0o600)
    os.environ["GOSPARK_MEMORY_GATEWAY_TOKEN"] = token
    roots = os.environ.get("GOSPARK_MEMORY_VAULT_ROOTS") or f"{NODE_DIR},/srv/sparknet/knowledge"
    args = [
        "-listen",
        os.environ.get("GOSPARK_MEMORY_LISTEN") or "127.0.0.1:4110",
        "-state",
        os.environ.get("GOSPARK_MEMORY_STATE") or str(STATE_DIR / "memory"),
        "-node-id",
        node_id(),
    ]
    for root in roots.split(","):
        if root:
            args.extend(["-vault-root", root])
    (STATE_DIR / "memory").mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        (STATE_DIR / "memory").chmod(0o700)
    log(f"memory {node_id()} on {os.environ.get('GOSPARK_MEMORY_LISTEN') or '127.0.0.1:4110'} roots={roots}")
    _exec("sparknet-memory", args)


def cmd_opencode(_args: list[str]) -> NoReturn:
    ensure_state()
    ensure_env()
    if not os.environ.get("OPENCODE_SERVER_PASSWORD"):
        die("opencode v2 requires OPENCODE_SERVER_PASSWORD; the 4204 engine is the supported user surface")
    log(f"opencode serve over {node_id()}")
    _exec(
        "opencode",
        [
            "serve",
            "--hostname",
            os.environ.get("OPENCODE_HOST") or ALL_INTERFACES,
            "--port",
            os.environ.get("OPENCODE_PORT") or "4200",
        ],
    )


def cmd_precontext(_args: list[str]) -> int:
    ensure_state()
    ensure_env()
    template = build_precontext()
    if not template or not Path(template).is_file() or not Path(template).stat().st_size:
        die("precontext template build failed")
    print(template)
    return 0


def cmd_vllm_stub(_args: list[str]) -> NoReturn:
    model = os.environ.get("VLLM_MODEL") or DEFAULT_MODEL
    port = os.environ.get("VLLM_PORT") or "8000"
    log(f"vllm-stub serving {model} on 0.0.0.0:{port}")
    _exec("stub-vllm", ["-model", model, "-port", port, "-host", ALL_INTERFACES])


def cmd_llama_embed(_args: list[str]) -> NoReturn:
    ensure_state()
    ensure_env()
    if shutil.which("llama-server") is None:
        die("llama-server not found in this image")
    model = os.environ.get("LLAMA_EMBED_MODEL") or "/opt/sparknet/models/bge-m3-q8_0.gguf"
    if not Path(model).is_file() or not Path(model).stat().st_size:
        die(f"embed model missing: {model} (image bake step failed?)")
    port = os.environ.get("VLLM_PORT") or "8001"
    args = [
        "--host",
        ALL_INTERFACES,
        "--port",
        port,
        "--model",
        model,
        "--embedding",
        "--pooling",
        "mean",
        "--alias",
        os.environ.get("LLAMA_EMBED_ALIAS") or "bge-m3",
        "--ctx-size",
        os.environ.get("LLAMA_EMBED_CTX") or "512",
    ]
    extra = os.environ.get("LLAMA_EMBED_EXTRA_ARGS")
    if extra:
        args.extend(shlex.split(extra))
    log(f"llama-embed {model} on 0.0.0.0:{port} (OpenAI /v1/embeddings)")
    _exec("llama-server", args)


def cmd_llama_rerank(_args: list[str]) -> NoReturn:
    ensure_state()
    ensure_env()
    if shutil.which("llama-server") is None:
        die("llama-server not found in this image")
    model = os.environ.get("LLAMA_RERANK_MODEL") or "/opt/sparknet/models/bge-reranker-v2-m3-Q4_K_M.gguf"
    if not Path(model).is_file() or not Path(model).stat().st_size:
        die(f"rerank model missing: {model} (image bake step failed?)")
    port = os.environ.get("VLLM_PORT") or "8002"
    args = [
        "--host",
        ALL_INTERFACES,
        "--port",
        port,
        "--model",
        model,
        "--reranking",
        "--alias",
        os.environ.get("LLAMA_RERANK_ALIAS") or "bge-reranker-v2-m3",
        "--ctx-size",
        os.environ.get("LLAMA_RERANK_CTX") or "512",
    ]
    extra = os.environ.get("LLAMA_RERANK_EXTRA_ARGS")
    if extra:
        args.extend(shlex.split(extra))
    log(f"llama-rerank {model} on 0.0.0.0:{port} (OpenAI/Cohere /v1/rerank)")
    _exec("llama-server", args)


def _supervise(commands: list[tuple[list[str], dict[str, str] | None]]) -> int:
    children = [subprocess.Popen(command, env=env) for command, env in commands]
    stopped = {"value": False}

    def _stop(_signum: int, _frame: object) -> None:
        stopped["value"] = True

    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(OSError, ValueError):
            previous[sig] = signal.signal(sig, _stop)
    try:
        while True:
            for child in children:
                if child.poll() is not None:
                    return child.returncode
            if stopped["value"]:
                return 0
            time.sleep(0.2)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def cmd_whisper_asr(_args: list[str]) -> int:
    ensure_state()
    ensure_env()
    if shutil.which("whisper-server") is None:
        die("whisper-server not found in this image")
    model = os.environ.get("WHISPER_MODEL") or "/opt/sparknet/models/ggml-small-q5_1.bin"
    if not Path(model).is_file() or not Path(model).stat().st_size:
        die(f"whisper model missing: {model} (image bake step failed?)")
    port = os.environ.get("VLLM_PORT") or "8003"
    upstream = os.environ.get("WHISPER_UPSTREAM_PORT") or "8004"
    whisper = ["whisper-server", "--host", "127.0.0.1", "--port", upstream, "--model", model, "--convert"]
    if os.environ.get("WHISPER_LANGUAGE"):
        whisper.extend(["--language", os.environ["WHISPER_LANGUAGE"]])
    extra = os.environ.get("WHISPER_EXTRA_ARGS")
    if extra:
        whisper.extend(shlex.split(extra))
    shim = [
        str(VENV / "bin" / "python"),
        "-m",
        "uvicorn",
        "--app-dir",
        "/opt/sparknet",
        "audio_shim:app",
        "--host",
        ALL_INTERFACES,
        "--port",
        port,
    ]
    log(f"whisper-asr: whisper-server on 127.0.0.1:{upstream} + OpenAI shim on 0.0.0.0:{port}")
    shim_env = {**os.environ, "WHISPER_UPSTREAM": f"http://127.0.0.1:{upstream}"}
    return _supervise([(whisper, None), (shim, shim_env)])


COMMANDS = {
    "vllm": cmd_vllm,
    "vllm-stub": cmd_vllm_stub,
    "compute": cmd_compute,
    "kvrouter": cmd_kvrouter,
    "agent": cmd_agent,
    "control": cmd_control,
    "gpu": cmd_gpu,
    "nats": cmd_nats,
    "ingest": cmd_ingest,
    "backup": cmd_backup,
    "memory": cmd_memory,
    "memory-gateway": cmd_memory_gateway,
    "opencode": cmd_opencode,
    "llama-embed": cmd_llama_embed,
    "llama-rerank": cmd_llama_rerank,
    "whisper-asr": cmd_whisper_asr,
    "precontext": cmd_precontext,
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "help"
    if command in ("--help", "-h", "help", ""):
        print(USAGE, end="")
        return 0
    rest = args[1:]
    if command == "shell":
        os.execv("/bin/bash", ["/bin/bash", *rest])  # noqa: S606 - the shell subcommand is the point
    handler = COMMANDS.get(command)
    if handler is None:
        print(f"spark-entrypoint: unknown subcommand: {command}", file=sys.stderr)
        print(USAGE, end="", file=sys.stderr)
        return 2
    return handler(rest)


if __name__ == "__main__":
    raise SystemExit(main())
