#!/usr/bin/env python3
"""sparknet-node-setup — bring up a SparkNet node end to end.

The shell file beside this one is a thin exec wrapper; this module is the
implementation. Idempotent: run it again and it reuses everything already in
place. It writes the node state under peer-node/.state (keys, secret, env-file,
joined registry), the staged bundle tarball, and nothing else.

Python 3.8-compatible: the deploy host may be older than the dev host.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import NoReturn

REPO = Path(__file__).resolve().parent
NODE_STATE = REPO / "peer-node" / ".state"
GOSPARK_DIR = Path(os.environ.get("GOSPARK_DIR") or (REPO / "gospark"))
ROLE = os.environ.get("SPARKNET_ROLE") or "peer"
PROFILES = os.environ.get("SPARK_PROFILES") or ""
ENGINE = os.environ.get("SPARK_ENGINE") or "vllm"
PLATFORM = os.environ.get("SPARKNET_PLATFORM") or "spark"
MODEL_SET = os.environ.get("SPARKNET_MODEL_SET") or "qwen3.6"
MASTER_PUB = os.environ.get("SPARKNET_MASTER_PUB") or ""
REGISTRY = os.environ.get("SPARKNET_REGISTRY_FILE") or ""
DO_BUILD = True
ACTION = "up"

STATE_DIR_IN_CONTAINER = "/srv/sparknet/peer-node/.state"
REGISTRY_IN_CONTAINER = STATE_DIR_IN_CONTAINER + "/node-authorizations.json"
ALL_INTERFACES = "0.0.0.0"  # noqa: S104 - the compose surface binds the API
AGX_LLM_BASE = "dustynv/llama_cpp:r35.2.1@sha256:a5659335c4b5d31f82b29ec5a04e6e77d219897eef0028db841c9d4c832b90f0"
AGX_L4T_BASE = (
    "nvcr.io/nvidia/l4t-pytorch:r35.2.1-pth2.0-py3"
    "@sha256:545a0f62fb4a5fd2d8c511134f6c55d451ae1565075dcc67123b0c422a469472"
)
AGX_TEACHER_FILE = "/opt/sparknet/models/qwen3.6-35b-a3b-q4_k_m.gguf"
AGX_STUDENT_FILE = "/opt/sparknet/models/qwen3.6-27b-q4_k_m.gguf"
AGX_MODEL_SETS = {
    "qwen3.6": {
        "master": (AGX_TEACHER_FILE, "qwen3.6-35b"),
        "peer": (AGX_STUDENT_FILE, "qwen3.6-27b"),
    },
    "qwen3": {
        "master": ("/opt/sparknet/models/qwen3-32b-q4_k_m.gguf", "qwen3-32b"),
        "peer": ("/opt/sparknet/models/qwen3-0.6b-q8_0.gguf", "qwen3-0.6b"),
    },
}

USAGE = """sparknet-node-setup.sh — bring up a SparkNet node (DGX Spark or AGX Xavier).

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
  --engine vllm|stub   model engine (default vllm; on AGX vllm means the
                        llama.cpp llama-server image; stub = CPU-only OpenAI
                        stub, no GPU/model)
  --model-set NAME     AGX teacher/student set: qwen3.6 (default) or qwen3
  --profiles A,B,C     compose profiles to enable: kv vector control webui embed rerank audio ingest backup opencode
  --master-pub KEY     the elected Master's Ed25519 public key (base64) or a file
                       holding it; joins the node to the fabric instead of running
                       open. With --registry and no key, the key is read from the
                       registry's master_public_key_b64 (less strong than pinning
                       it out of band; logged).
  --registry FILE      Master-signed node-authorizations registry to adopt; copied
                       into the node state dir and passed to the goSpark agent.
  --no-build           skip the bundle + image build (use the existing image)
  --gospark DIR        goSpark checkout (default <fabric-root>/gospark)
  -h, --help           this text
"""


def log(message: str) -> None:
    print(f"\033[1;36m[setup]\033[0m {message}", flush=True)


def warn(message: str) -> None:
    print(f"\033[1;33m[warn]\033[0m {message}", file=sys.stderr, flush=True)


def die(message: str) -> NoReturn:
    print(f"\033[1;31m[error]\033[0m {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def _run(command: list[str], *, timeout: int | None = None, quiet: bool = False) -> int:
    try:
        completed = subprocess.run(
            command,
            stdout=subprocess.DEVNULL if quiet else None,
            stderr=subprocess.DEVNULL if quiet else None,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError:
        die(f"{command[0]} not found")
    return completed.returncode


def preflight() -> None:
    if shutil.which("docker") is None:
        die("docker not found")
    if _run(["docker", "compose", "version"], quiet=True) != 0:
        die("'docker compose' (v2 plugin) not found")
    if not COMPOSE_FILE.is_file():
        die(f"compose file missing: {COMPOSE_FILE}")
    if REGISTRY and not Path(REGISTRY).is_file():
        die(f"registry file not found: {REGISTRY}")
    if DO_BUILD:
        if not GOSPARK_DIR.is_dir():
            die(f"goSpark not found at {GOSPARK_DIR} (use --gospark DIR)")
        for binary in ("sparknet-agent", "sparknet-control", "sparknet-gpu", "sparknetctl", "sparknet-understand"):
            if not (GOSPARK_DIR / "bin" / binary).is_file() or not os.access(GOSPARK_DIR / "bin" / binary, os.X_OK):
                die(f"missing {GOSPARK_DIR / 'bin' / binary} — run: make -C {GOSPARK_DIR} build build-gpu")


def compose(*args: str) -> int:
    profiles: list[str] = []
    for profile in PROFILES.replace(",", " ").split():
        profiles.extend(["--profile", profile])
    if ROLE == "master":
        profiles.extend(["--profile", "control"])
    env_file: list[str] = []
    if ENV_FILE.is_file():
        env_file = ["--env-file", str(ENV_FILE)]
    files = ["-f", str(COMPOSE_FILE)]
    if ENGINE == "stub":
        files.extend(["-f", str(REPO / "spark.compose.cpu.yml")])
    return _run(["docker", "compose", *files, *env_file, *profiles, *args])


def stage_bundle() -> None:
    log("building the sparknet peer bundle")
    if _run(["make", "-C", str(REPO / "peer-node"), "dist"]) != 0:
        die("bundle build failed")
    candidates = sorted(
        (REPO / "dist").glob("sparknet-peer-*.tar.gz"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        die("no bundle produced under dist/")
    target = REPO / "peer-node" / "container" / "context"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(candidates[0], target / "sparknet-peer.tar.gz")
    log(f"staged bundle: {candidates[0].name}")


def _secret(path: Path, size: int = 32) -> str:
    if path.is_file() and path.stat().st_size:
        # Command substitution stripped the trailing newline in the shell
        # implementation; keep the rendered env byte-identical when a secret
        # file was written by hand or by an older tool.
        return path.read_text(encoding="utf-8").strip()
    value = base64.b64encode(os.urandom(size)).decode()
    path.write_text(value, encoding="utf-8")
    path.chmod(0o600)
    return value


def resolve_join() -> tuple[str, str]:
    master = ""
    registry_path = ""
    if MASTER_PUB:
        candidate = Path(MASTER_PUB)
        if candidate.is_file():
            master = "".join(candidate.read_text(encoding="utf-8").split())
        else:
            master = "".join(MASTER_PUB.split())
        if not master:
            die("--master-pub is empty")
    if REGISTRY:
        source = Path(REGISTRY)
        if not source.is_file():
            die(f"registry file not found: {REGISTRY}")
        NODE_STATE.mkdir(parents=True, exist_ok=True)
        staged = NODE_STATE / "node-authorizations.json"
        shutil.copyfile(source, staged)
        staged.chmod(0o600)
        registry_path = REGISTRY_IN_CONTAINER
        if not master:
            try:
                document = json.loads(source.read_text(encoding="utf-8"))
                master = str(document.get("master_public_key_b64") or "")
            except (OSError, json.JSONDecodeError) as exc:
                die(f"cannot read master_public_key_b64 from {REGISTRY}: {exc}")
            if not master:
                die(f"registry {REGISTRY} has no master_public_key_b64; pass --master-pub")
            warn("no --master-pub: using the key embedded in the registry (pin it out of band for the strong form)")
    return master, registry_path


def render_env_file() -> None:
    NODE_STATE.mkdir(parents=True, exist_ok=True)
    NODE_STATE.chmod(0o700)
    master_pub, registry_path = resolve_join()

    node_id = os.environ.get("SPARKNET_NODE_ID") or os.uname().nodename
    overlay = os.environ.get("SPARKNET_OVERLAY_IPV4") or ("10.100.0.1" if ROLE == "master" else "10.100.0.2")
    image_tag = os.environ.get("SPARKNET_IMAGE_TAG") or "dev"
    if PLATFORM == "agx":
        set_file, set_alias = AGX_MODEL_SETS[MODEL_SET][ROLE]
        model = os.environ.get("VLLM_MODEL") or set_alias
        model_file = os.environ.get("SPARKNET_LLM_MODEL_FILE") or set_file
        base_line = "L4T_BASE=" + (os.environ.get("L4T_BASE") or AGX_L4T_BASE)
        max_len = "VLLM_MAX_MODEL_LEN=" + (os.environ.get("VLLM_MAX_MODEL_LEN") or "8192")
        llm_line = "\n".join(
            [
                "SPARKNET_LLM_BASE=" + (os.environ.get("SPARKNET_LLM_BASE") or AGX_LLM_BASE),
                "SPARKNET_LLM_TAG=" + (os.environ.get("SPARKNET_LLM_TAG") or "agx"),
                "SPARKNET_LLM_MODEL_FILE=" + model_file,
                "SPARKNET_LLM_CTX=" + (os.environ.get("SPARKNET_LLM_CTX") or "8192"),
                "SPARKNET_MODELS_HOST=" + (os.environ.get("SPARKNET_MODELS_HOST") or "/opt/sparknet/models"),
                "SPARKNET_MODEL_SET=" + MODEL_SET,
                "VLLM_EXTRA_ARGS=" + (os.environ.get("VLLM_EXTRA_ARGS") or "--no-mmap --fit off"),
            ]
        )
        node_line = "\n".join(
            [
                "SPARKNET_NODE_IMAGE=sparknet-agx-node:" + image_tag,
                "SPARKNET_NODE_DOCKERFILE=goagx/sparknet.agx.docker",
            ]
        )
        gpu_mem_line = ""
        image_dockerfile = "sparknet.agx.docker"
    else:
        model = os.environ.get("VLLM_MODEL") or "Qwen/Qwen2.5-32B-Instruct"
        base_line = "VLLM_BASE=" + (os.environ.get("VLLM_BASE") or "nvcr.io/nvidia/vllm:26.04-py3")
        max_len = "VLLM_MAX_MODEL_LEN=" + (os.environ.get("VLLM_MAX_MODEL_LEN") or "65536")
        llm_line = ""
        node_line = "\n".join(
            [
                "SPARKNET_NODE_IMAGE=sparknet-spark-node:" + image_tag,
                "SPARKNET_NODE_DOCKERFILE=spark.docker",
            ]
        )
        gpu_mem_line = "VLLM_GPU_MEM_UTIL=" + (os.environ.get("VLLM_GPU_MEM_UTIL") or "0.85")
        image_dockerfile = "spark.docker"

    service_cmd = "vllm-stub" if ENGINE == "stub" else "vllm"
    secret = _secret(NODE_STATE / "sparknet.shared.secret")
    qdrant = _secret(NODE_STATE / "qdrant.api.key")
    memory = _secret(NODE_STATE / "memory.gateway.token")
    _secret(NODE_STATE / "memory.local.token")
    memory_webui = _secret(NODE_STATE / "memory.webui.token")
    engine = _secret(NODE_STATE / "opencode-engine.token")
    webui = _secret(NODE_STATE / "webui.secret.key")
    admin_secret = NODE_STATE / "webui-admin-password"
    if ROLE == "master" and not (admin_secret.is_file() and admin_secret.stat().st_size):
        _secret(admin_secret, 24)
    admin = (
        admin_secret.read_text(encoding="utf-8").strip()
        if admin_secret.is_file() and admin_secret.stat().st_size
        else ""
    )

    (NODE_STATE / "opencode-engine").mkdir(parents=True, exist_ok=True)
    (NODE_STATE / "opencode-engine").chmod(0o700)

    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    memory_roots = os.environ.get("GOSPARK_MEMORY_VAULT_ROOTS") or "/srv/sparknet/peer-node,/srv/sparknet/knowledge"
    env = f"""# Generated by sparknet-node-setup.sh — do not commit ({stamp}).
SPARKNET_NODE_ID={node_id}
SPARKNET_ROLE={ROLE}
SPARKNET_OVERLAY_IPV4={overlay}
SPARKNET_SHARED_SECRET={secret}
SPARKNET_STATE_HOST={NODE_STATE}
GOSPARK_DIR={GOSPARK_DIR}
SPARKNET_IMAGE_TAG={image_tag}
{base_line}
VLLM_MODEL={model}
VLLM_SERVICE_CMD={service_cmd}
{gpu_mem_line}
{max_len}
{llm_line}
{node_line}
HF_CACHE_DIR={os.environ.get("HF_CACHE_DIR") or (Path.home() / ".cache" / "huggingface")}
SPARKNET_BIND_API={os.environ.get("SPARKNET_BIND_API") or ALL_INTERFACES}
SPARKNET_BIND_LOCAL={os.environ.get("SPARKNET_BIND_LOCAL") or "127.0.0.1"}
# Pinned foreign images. NATS_IMAGE_TAG must track NATS_VERSION in {image_dockerfile}
# (the same nats-server is also baked into the image for `spark-entrypoint nats`);
# WEBUI_TAG is a stable release, never `main`/`latest`.
NATS_IMAGE_TAG={os.environ.get("NATS_IMAGE_TAG") or "2.14.2-alpine"}
WEBUI_TAG={os.environ.get("WEBUI_TAG") or "v0.13.0"}
SPARKNET_MASTER_PUB={master_pub}
GOSPARK_REGISTRY_FILE={registry_path}
SPARKNET_QDRANT_URL={os.environ.get("SPARKNET_QDRANT_URL") or "http://127.0.0.1:6333"}
SPARKNET_QDRANT_API_KEY={qdrant}
SPARKNET_OPENCODE_ENGINE_TOKEN={engine}
SPARKNET_OPENCODE_ENGINE_TOKEN_FILE={NODE_STATE / "opencode-engine.token"}
WEBUI_SECRET_KEY={webui}
SPARKNET_WEBUI_ADMIN_EMAIL={os.environ.get("SPARKNET_WEBUI_ADMIN_EMAIL") or "admin@sparknet.local"}
SPARKNET_WEBUI_ADMIN_PASSWORD={admin}
SPARKNET_WEBUI_PUBLIC_URL={os.environ.get("SPARKNET_WEBUI_PUBLIC_URL") or "http://127.0.0.1:8181"}
GOSPARK_MEMORY_GATEWAY_TOKEN={memory}
GOSPARK_MEMORY_VAULT_ROOTS={memory_roots}
SPARKNET_MEMORY_WEBUI_TOKEN={memory_webui}
SPARKNET_MEMORY_GATEWAY_URL={os.environ.get("SPARKNET_MEMORY_GATEWAY_URL") or "http://127.0.0.1:4093"}
QDRANT_TAG={os.environ.get("QDRANT_TAG") or "v1.20.0"}
SPARKNET_UPLIFT_ENDPOINT={os.environ.get("SPARKNET_UPLIFT_ENDPOINT") or "http://10.100.0.1:8091"}
# Reflex is local-only: a local reranker/LLM, or the Master's broker, which
# answers locally too. There is no egress path and no credential. No new
# published port.
SPARKNET_REFLEX_MODE={os.environ.get("SPARKNET_REFLEX_MODE") or "local"}
SPARKNET_REFLEX_BACKEND={os.environ.get("SPARKNET_REFLEX_BACKEND") or "local"}
SPARKNET_REFLEX_LOCAL_URL={os.environ.get("SPARKNET_REFLEX_LOCAL_URL") or "http://127.0.0.1:8000"}
SPARKNET_REFLEX_LOCAL_MODEL={os.environ.get("SPARKNET_REFLEX_LOCAL_MODEL") or "local"}
SPARKNET_REFLEX_BROKER_URL={os.environ.get("SPARKNET_REFLEX_BROKER_URL") or "http://10.100.0.1:4224"}
SPARKNET_REFLEX_TIMEOUT={os.environ.get("SPARKNET_REFLEX_TIMEOUT") or "2.0"}
"""
    ENV_FILE.write_text(env, encoding="utf-8")
    ENV_FILE.chmod(0o600)

    engine_env = NODE_STATE / "opencode-engine.env"
    engine_model = "qwen3.6-35b-262k-q8:latest"
    engine_small = "gemma4-4b-131k:latest"
    engine_single = ""
    if ROLE == "master":
        engine_model = os.environ.get("SPARKNET_OPENCODE_MODEL") or "qwen3.5-9b-q8:latest"
        engine_single = "/srv/sparknet/knowledge/master-admin"
    engine_env.write_text(
        f"""# Generated by sparknet-node-setup.sh — OpenCode engine supervisor ({stamp}).
SPARKNET_OPENCODE_ENGINE_TOKEN_FILE={NODE_STATE / "opencode-engine.token"}
SPARKNET_OPENCODE_ENGINE_STATE={NODE_STATE / "opencode-engine"}
SPARKNET_KNOWLEDGE_ROOT=/srv/sparknet/knowledge
SPARKNET_OPENCODE_SINGLE_VAULT={engine_single}
SPARKNET_OPENCODE_IMAGE={os.environ.get("SPARKNET_OPENCODE_IMAGE") or "sparknet-opencode-runtime:2.2.5"}
SPARKNET_DOCKER={os.environ.get("SPARKNET_DOCKER") or "docker"}
SPARKNET_MODEL_UPSTREAM={os.environ.get("SPARKNET_MODEL_UPSTREAM") or "http://127.0.0.1:11434"}
SPARKNET_OPENCODE_MODEL={engine_model}
SPARKNET_OPENCODE_SMALL_MODEL={engine_small}
SPARKNET_OPENCODE_CONFIG_TEMPLATE={REPO / "peer-node" / "configs" / "opencode-engine" / "opencode.json.template"}
SPARKNET_OPENCODE_IDLE_SECONDS={os.environ.get("SPARKNET_OPENCODE_IDLE_SECONDS") or "1800"}
""",
        encoding="utf-8",
    )
    engine_env.chmod(0o600)
    log(f"wrote {engine_env} (engine model={engine_model})")
    image = os.environ.get("SPARKNET_OPENCODE_IMAGE") or "sparknet-opencode-runtime:2.2.5"
    if _run(["docker", "image", "inspect", image], quiet=True) != 0:
        log(f"WARNING: {image} is missing; run: make -C peer-node opencode-runtime")
    if registry_path:
        log(f"joined fabric: registry staged, master key {'pinned' if master_pub else 'from registry'}")
    log(f"wrote {ENV_FILE} (node={node_id} role={ROLE} overlay={overlay})")


def write_gpu_fixture() -> None:
    if ENGINE != "stub":
        return
    out = NODE_STATE / "gpu-sim.json"
    if out.is_file() and out.stat().st_size:
        return
    script = REPO / "scripts" / "make-gpu-fixture.py"
    if script.is_file() and os.access(script, os.X_OK):
        if _run([str(script), "-o", str(out)], quiet=True) != 0:
            warn("scripts/make-gpu-fixture.py failed; gpu sidecar will report unavailable")
            return
        out.chmod(0o644)
        log(f"wrote synthetic GPU fixture: {out}")
    else:
        warn("scripts/make-gpu-fixture.py missing; gpu sidecar will report unavailable")


def ensure_vault_env() -> None:
    source = REPO / "peer-node" / ".env"
    if not source.is_file():
        init = REPO / "scripts" / "sparknet-env-init.sh"
        if init.is_file() and os.access(init, os.X_OK):
            log("initializing the node vault .env")
            if _run([str(init), str(REPO / "peer-node")], quiet=True) != 0:
                warn("env-init failed; the image regenerates .env at start")
        else:
            warn("no scripts/sparknet-env-init.sh; the image regenerates .env at start")
    (NODE_STATE / "nats").mkdir(parents=True, exist_ok=True)
    (NODE_STATE / "webui").mkdir(parents=True, exist_ok=True)


def act_build() -> None:
    stage_bundle()
    render_env_file()
    write_gpu_fixture()
    ensure_vault_env()
    if PLATFORM == "agx":
        base = os.environ.get("L4T_BASE") or AGX_L4T_BASE
        llm_base = os.environ.get("SPARKNET_LLM_BASE") or AGX_LLM_BASE
        log(f"building the node + text-engine images ({PLATFORM}: L4T_BASE={base}, SPARKNET_LLM_BASE={llm_base})")
    else:
        base = os.environ.get("VLLM_BASE") or "nvcr.io/nvidia/vllm:26.04-py3"
        log(f"building the node image ({PLATFORM}: VLLM_BASE={base})")
    if compose("build") != 0:
        raise SystemExit(1)


def act_up() -> None:
    if DO_BUILD:
        act_build()
    if not ENV_FILE.is_file() or MASTER_PUB or REGISTRY:
        render_env_file()
    # --no-build skips act_build, but the compose mounts still need the state
    # subdirectories and the role .env; create them on every up.
    ensure_vault_env()
    write_gpu_fixture()
    log(f"starting services (role={ROLE} engine={ENGINE} profiles={PROFILES or 'none'})")
    if compose("up", "-d") != 0:
        raise SystemExit(1)
    print()
    log("node up. Endpoints:")
    bind = os.environ.get("SPARKNET_BIND_API") or ALL_INTERFACES
    print(f"    text engine API   http://{bind}:8000/v1")
    print(f"    node gateway      http://{bind}:8080/v1")
    if ROLE == "master":
        print("    control admin     http://127.0.0.1:8899/admin")
    if ",webui," in f",{PROFILES},":
        print(f"    Open WebUI        http://{bind}:3000")
    if ENGINE == "stub":
        warn("engine=stub: :8000 answers from the CPU stub, not a real model;")
        warn("the GPU sidecar reads a synthetic fixture (telemetry only).")
    print(
        """

Next steps:
  * List models:      curl -s http://127.0.0.1:8080/v1/models
  * Node logs:        ./sparknet-node-setup.sh logs
  * Stop:             ./sparknet-node-setup.sh down
  * Fabric election (choose a Master, sign the trust root) is a separate
    ceremony — see contracts/deployment-runbook.md. This script only stands a
    node up; it does not elect or sign.
"""
    )


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("action", nargs="?", default="up", choices=["up", "build", "down", "status", "logs"])
    parser.add_argument("--role", default=ROLE)
    parser.add_argument("--platform", default=PLATFORM)
    parser.add_argument("--engine", default=ENGINE)
    parser.add_argument("--model-set", default=MODEL_SET)
    parser.add_argument("--profiles", default=PROFILES)
    parser.add_argument("--master-pub", default=MASTER_PUB)
    parser.add_argument("--registry", default=REGISTRY)
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--gospark", default=str(GOSPARK_DIR))
    parser.add_argument("-h", "--help", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    global ROLE, PLATFORM, ENGINE, MODEL_SET, PROFILES, MASTER_PUB, REGISTRY, DO_BUILD, GOSPARK_DIR, ACTION
    global COMPOSE_FILE, ENV_FILE
    args = parse(argv)
    if args.help:
        print(USAGE, end="")
        return 0
    ACTION = args.action
    ROLE = args.role
    PLATFORM = args.platform
    ENGINE = args.engine
    MODEL_SET = args.model_set
    PROFILES = args.profiles
    MASTER_PUB = args.master_pub
    REGISTRY = args.registry
    GOSPARK_DIR = Path(args.gospark)
    DO_BUILD = not args.no_build
    if ENGINE not in ("vllm", "stub"):
        die(f"--engine must be 'vllm' or 'stub' (got: {ENGINE})")
    if MODEL_SET not in AGX_MODEL_SETS:
        die(f"--model-set must be one of {', '.join(sorted(AGX_MODEL_SETS))} (got: {MODEL_SET})")
    if ROLE not in ("peer", "master"):
        die(f"--role must be 'peer' or 'master' (got: {ROLE})")
    if REGISTRY and ROLE == "master":
        die(
            "--registry joins a PEER to a fabric whose Master signs elsewhere; "
            "a master node runs the control plane, which signs its own registry"
        )
    if PLATFORM == "spark":
        COMPOSE_FILE = REPO / "spark.compose.yml"
        ENV_FILE = NODE_STATE / "spark.env"
    elif PLATFORM == "agx":
        COMPOSE_FILE = REPO / "goagx" / "sparknet.agx.compose.yml"
        ENV_FILE = NODE_STATE / "spark-agx.env"
    else:
        die(f"--platform must be 'spark' or 'agx' (got: {PLATFORM})")
    if ACTION in ("down", "status", "logs"):
        DO_BUILD = False
    preflight()
    if ACTION == "build":
        act_build()
    elif ACTION == "up":
        act_up()
    elif ACTION == "down":
        return compose("down")
    elif ACTION == "status":
        return compose("ps")
    elif ACTION == "logs":
        return compose("logs", "-f", "--tail=100")
    return 0


COMPOSE_FILE = REPO / "spark.compose.yml"
ENV_FILE = NODE_STATE / "spark.env"

if __name__ == "__main__":
    raise SystemExit(main())
