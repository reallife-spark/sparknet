"""The AGX Xavier twin: same node contract, different engine layer.

goagx/ retargets the node distribution from NVIDIA DGX Spark (GB10, sm_121a,
CUDA 13) to NVIDIA AGX Xavier (Volta, sm_72, L4T r35, CUDA 11.4) while keeping
every service, port, profile and container name of the Spark stack. The
runbook, the contracts port table, the CPU overlay and every tool that parses
spark.compose.yml must keep working against goagx/sparknet.agx.compose.yml
without a fork — so this suite pins the parity, the image's pins, and the
setup-script / entrypoint wiring that lets one dispatcher serve both images.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
AGX_DIR = REPO_ROOT / "goagx" / "goagx"
AGX_COMPOSE = AGX_DIR / "sparknet.agx.compose.yml"
AGX_DOCKER = AGX_DIR / "sparknet.agx.docker"
SPARK_COMPOSE = REPO_ROOT / "spark.compose.yml"
SPARK_DOCKER = REPO_ROOT / "spark.docker"
SETUP = REPO_ROOT / "sparknet-node-setup.sh"
ENTRYPOINT = REPO_ROOT / "spark-entrypoint.sh"
SHIM = AGX_DIR / "sparknet-audio-shim.py"

# The engine layer is the one place the two stacks may differ. Everything
# else — names, ports, profiles, the core services' env keys — is contract.
AUX_SERVICES = {"vllm-embed", "vllm-rerank", "vllm-audio"}
CORE_SERVICES = {
    "nats",
    "vllm",
    "compute",
    "kvrouter",
    "agent",
    "memory",
    "memory-gateway",
    "control",
    "gpu",
    "webui",
    "ingest",
    "backup",
    "opencode",
}


def _services(path: Path) -> dict:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("services") or {}


def _ports(service: dict) -> set[str]:
    """Rightmost field of each published mapping = the container port."""
    return {str(entry).split(":")[-1] for entry in service.get("ports") or []}


def _env_keys(service: dict) -> set[str]:
    return set(service.get("environment") or {})


@pytest.fixture(scope="module")
def spark() -> dict:
    return _services(SPARK_COMPOSE)


@pytest.fixture(scope="module")
def agx() -> dict:
    return _services(AGX_COMPOSE)


# --- 1. the service surface is one contract ----------------------------------


def test_both_stacks_name_the_same_services(spark: dict, agx: dict):
    """Same service names: the runbook, the CPU overlay and every profile
    command (`--profile embed`, `run --rm ingest`, ...) work on either node."""
    assert set(agx) == set(spark), (
        f"service sets diverged: only-spark={sorted(set(spark) - set(agx))} only-agx={sorted(set(agx) - set(spark))}"
    )


def test_container_names_and_profiles_match(spark: dict, agx: dict):
    """A compose override file, a log line and `docker compose ps` must not
    care which hardware the node runs on."""
    for name in sorted(spark):
        assert agx[name].get("container_name") == spark[name].get("container_name"), (
            f"{name}: container_name drifted ({spark[name].get('container_name')} vs {agx[name].get('container_name')})"
        )
        spark_profiles = spark[name].get("profiles") or []
        agx_profiles = agx[name].get("profiles") or []
        assert agx_profiles == spark_profiles, f"{name}: profiles drifted ({spark_profiles} vs {agx_profiles})"


def test_published_ports_match(spark: dict, agx: dict):
    """ports.json is a cross-role contract; a node that moves a port breaks
    the peer's dial assumptions, whichever image it runs on."""
    for name in sorted(spark):
        assert _ports(agx[name]) == _ports(spark[name]), (
            f"{name}: published container ports drifted: "
            f"spark={sorted(_ports(spark[name]))} agx={sorted(_ports(agx[name]))}"
        )


def test_core_services_keep_their_env_keys(spark: dict, agx: dict):
    """The core services talk to each other through named env keys; the
    engine layer is where divergence lives (LLAMA_*/WHISPER_* on AGX), never
    here. Values may differ (a 7B default on Xavier); keys may not."""
    for name in sorted(CORE_SERVICES):
        assert _env_keys(agx[name]) == _env_keys(spark[name]), (
            f"{name}: env keys drifted: only-spark={sorted(_env_keys(spark[name]) - _env_keys(agx[name]))} "
            f"only-agx={sorted(_env_keys(agx[name]) - _env_keys(spark[name]))}"
        )


def test_engine_divergence_is_exactly_the_documented_one(spark: dict, agx: dict):
    """Commands may differ only on the three aux services plus (both say the
    same `${VLLM_SERVICE_CMD:-vllm}`); GPU reservations shrink from five
    services to two — the GPU belongs to the text model, the aux engines are
    CPU-only on Xavier."""
    for name in sorted(set(spark) - AUX_SERVICES):
        assert agx[name].get("command") == spark[name].get("command"), f"{name}: command diverged off the engine layer"

    def reserved(services: dict) -> set[str]:
        out = set()
        for name, spec in services.items():
            devices = (((spec.get("deploy") or {}).get("resources") or {}).get("reservations") or {}).get("devices")
            if devices:
                out.add(name)
        return out

    assert reserved(spark) == {"vllm", "gpu", *AUX_SERVICES}
    assert reserved(agx) == {"vllm", "gpu"}


def test_agx_defaults_fit_a_xavier(spark: dict, agx: dict):
    """Xavier has 8-16 GB unified memory, not 128: the AGX defaults must be
    the small ones, and the Spark defaults must not have been dragged along
    by the copy."""
    agx_env = agx["vllm"]["environment"]
    spark_env = spark["vllm"]["environment"]
    assert "mistralai/Mistral-7B-Instruct-v0.2" in str(agx_env["VLLM_MODEL"])
    assert "Qwen" in str(spark_env["VLLM_MODEL"])
    assert "8192" in str(agx_env["VLLM_MAX_MODEL_LEN"]), "AGX default context must fit Xavier, not the Spark"
    assert "65536" in str(spark_env["VLLM_MAX_MODEL_LEN"]), "the Spark default was dragged down by the copy"
    compose_text = AGX_COMPOSE.read_text(encoding="utf-8")
    assert "shm_size: ${VLLM_SHM_SIZE:-4gb}" in compose_text, "the AGX shm default must fit a 16 GB machine"


# --- 2. the image and its pins ------------------------------------------------


def test_agx_builds_its_own_image_from_the_repo_root(agx: dict):
    """The build context is the repo root (bundle tarball + dispatcher live
    there), the dockerfile is the AGX one, and the goSpark named context keeps
    the source out of the upload — same shape as the Spark build."""
    build = agx["vllm"]["build"]
    assert build["context"] == ".."
    assert build["dockerfile"] == "goagx/sparknet.agx.docker"
    assert "gospark" in (build.get("additional_contexts") or {}), "the goSpark named context is required"
    args = build.get("args") or {}
    assert args["L4T_BASE"].startswith("${L4T_BASE:-nvcr.io/nvidia/l4t-pytorch:r35."), (
        "the AGX base must be a pinned L4T r35 PyTorch image, never a moving tag"
    )
    spark_build = _services(SPARK_COMPOSE)["vllm"]["build"]
    for key in ("OPENCODE_VERSION", "NATS_VERSION"):
        assert args[key] == spark_build["args"][key], f"{key} must be the same pin on both platforms"
    assert "image" in agx["vllm"] and "sparknet-agx-node:" in agx["vllm"]["image"]


def test_agx_dockerfile_pins_hold():
    """No floating tags, version-shaped refs, SHA-pinned model URLs, and the
    two facts this image exists for: an r35 base and a Volta-compatible arch
    list (vLLM rejects unknown archs outright — 7.2 is not in its set, so the
    build targets 7.0+PTX and the driver JITs for sm_72)."""
    text = AGX_DOCKER.read_text(encoding="utf-8")

    assert re.search(r"ARG L4T_BASE=nvcr\.io/nvidia/l4t-pytorch:r35\.", text), "base must stay on the L4T r35 branch"
    assert re.search(r'ARG TORCH_CUDA_ARCH_LIST="7\.0\+PTX"', text), (
        "sm_70+PTX is the only arch list v0.2.7 accepts for Xavier"
    )
    assert not re.search(r":(latest|main)\b", text), "the AGX image floats a tag"

    for arg in ("VLLM_GIT_REF", "LLAMA_CPP_REF", "WHISPER_CPP_REF"):
        match = re.search(rf"ARG {arg}=(v[\d.]+)", text)
        assert match, f"{arg} must be a version-shaped release ref"
    assert re.search(r"ARG XFORMERS_PIP_SPEC=\"xformers==", text), "xformers must be pinned to the torch-2.0.0 match"

    urls = re.findall(r"https://huggingface\.co/\S+", text)
    assert len(urls) >= 3, "the three baked models must be present"
    for url in urls:
        assert re.search(r"/resolve/[0-9a-f]{40}/", url), f"model URL is not SHA-pinned: {url}"


def test_agx_image_shares_the_node_surface_pins():
    """One dispatcher, one opencode version, one NATS release across the two
    images — the tools and the bus must not fork with the hardware."""
    spark_text = SPARK_DOCKER.read_text(encoding="utf-8")
    agx_text = AGX_DOCKER.read_text(encoding="utf-8")
    for arg in ("OPENCODE_VERSION", "NATS_VERSION"):
        spark_pin = re.search(rf"ARG {arg}=([\w.\-]+)", spark_text)
        agx_pin = re.search(rf"ARG {arg}=([\w.\-]+)", agx_text)
        assert spark_pin and agx_pin, f"{arg} missing from a dockerfile"
        assert spark_pin.group(1) == agx_pin.group(1), (
            f"{arg} forked: spark={spark_pin.group(1)} agx={agx_pin.group(1)}"
        )

    for artifact in ("spark-entrypoint.sh", "spark-precontext.py"):
        assert re.search(rf"COPY {re.escape(artifact)} ", agx_text), f"{artifact} must be shipped by the AGX image too"


# --- 3. one dispatcher, two engines -------------------------------------------


def test_setup_script_wires_the_platform_flag():
    """`--platform agx` must swap the compose file AND the env-file together
    (spark.env vs spark-agx.env), keep the default at spark so the join-test
    fixture and existing habits stay valid, and advertise itself."""
    text = SETUP.read_text(encoding="utf-8")

    assert 'PLATFORM="${SPARKNET_PLATFORM:-spark}"' in text, "the default platform must remain spark"
    assert "--platform)" in text, "the setup script does not parse --platform"
    assert "--platform spark|agx" in text, "the usage text does not advertise --platform"

    agx_block = re.search(r"agx\)\s*\n(.*?)\n\s*;;", text, re.S)
    assert agx_block, "no agx branch in the platform case"
    assert "goagx/sparknet.agx.compose.yml" in agx_block.group(1), "agx must build against the AGX compose"
    assert "spark-agx.env" in agx_block.group(1), "agx needs its own env-file (never inherits spark.env)"

    spark_block = re.search(r"spark\)\s*\n(.*?)\n\s*;;", text, re.S)
    assert spark_block, "no spark branch in the platform case"
    assert "spark.compose.yml" in spark_block.group(1) and "spark.env" in spark_block.group(1)


def test_entrypoint_dispatches_the_aux_engines():
    """The AGX compose speaks `llama-embed`, `llama-rerank`, `whisper-asr`;
    the dispatcher must know them, check their baked models, and pick the
    engine through VLLM_CLI — vLLM 0.2.x has no `vllm serve` subcommand, and
    it has neither --enable-prefix-caching nor --limit-mm-per-prompt, so the
    newer-engine flags may only travel the `serve` branch."""
    text = ENTRYPOINT.read_text(encoding="utf-8")

    for subcommand in ("llama-embed", "llama-rerank", "whisper-asr"):
        impl = f"cmd_{subcommand.replace('-', '_')}"
        assert re.search(rf"^\s+{re.escape(subcommand)}\)", text, re.M), f"dispatch case is missing {subcommand}"
        assert f"{impl}()" in text, f"missing {impl} implementation"
        usage_body = text.split("usage() {", 1)[1].split("\n}", 1)[0]
        assert subcommand in usage_body, f"usage() does not document {subcommand}"

    assert "VLLM_CLI" in text and "cli=(${VLLM_CLI:-vllm serve})" in text, "the engine command must come from VLLM_CLI"
    assert 'args=(--model "$model")' in text, "a non-`serve` engine must receive --model, not a positional"
    assert '[ "$modern" = 1 ]' in text, "the newer-engine flags must be gated on the modern CLI branch"
    assert text.count('[ "$modern" = 1 ]') == 2, "both --enable-prefix-caching and --limit-mm-per-prompt must be gated"

    # baked-model guards: a missing GGUF is a build error, not a crash loop
    assert 'die "embed model missing' in text
    assert 'die "rerank model missing' in text
    assert 'die "whisper model missing' in text


def test_aux_engines_are_baked_and_healthchecked(agx: dict):
    """The three aux services must point at the SHA-pinned GGUFs baked into
    the image (seconds to start, no downloads) and healthcheck their own
    port — unlike the Spark node's aux services, whose engines load models at
    start and are deliberately unhealthchecked."""
    baked = (
        ("vllm-embed", "LLAMA_EMBED_MODEL"),
        ("vllm-rerank", "LLAMA_RERANK_MODEL"),
        ("vllm-audio", "WHISPER_MODEL"),
    )
    for name, env_key in baked:
        spec = agx[name]
        assert str(spec["environment"][env_key]).startswith("/opt/sparknet/models/"), f"{name}: model must be baked"
        assert spec.get("healthcheck"), f"{name}: a baked engine must healthcheck"
    assert agx["vllm-embed"]["command"] == ["llama-embed"]
    assert agx["vllm-rerank"]["command"] == ["llama-rerank"]
    assert agx["vllm-audio"]["command"] == ["whisper-asr"]


def test_audio_keeps_the_openai_surface():
    """whisper.cpp v1.9.5 has no /v1/audio/transcriptions; the shim is what
    keeps the contract, and the wiring must agree on the module name, the
    loopback upstream and the two install-time dependencies (multipart
    parsing for FastAPI, ffmpeg for whisper's --convert)."""
    shim = SHIM.read_text(encoding="utf-8")
    assert '@app.post("/v1/audio/transcriptions")' in shim, "the OpenAI route is the whole point of the shim"
    assert '@app.get("/health")' in shim, "the compose healthcheck hits /health on the shim"
    assert "Optional[str]" in shim, "py3.8: PEP 604 unions cannot survive FastAPI's runtime annotation evaluation"
    assert "WHISPER_MAX_UPLOAD_BYTES" in shim, "an unbounded upload read can exhaust a 16 GB machine — cap it (413)"

    docker = AGX_DOCKER.read_text(encoding="utf-8")
    assert "COPY goagx/sparknet-audio-shim.py /opt/sparknet/audio_shim.py" in docker, "the shim must ship in the image"
    assert "py_compile /opt/sparknet/audio_shim.py" in docker, "the shim must byte-compile at build time"
    assert "python-multipart" in docker, "FastAPI form parsing needs python-multipart"
    assert re.search(r"\bffmpeg\b", docker), "whisper --convert needs ffmpeg for non-WAV uploads"

    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert "--app-dir /opt/sparknet audio_shim:app" in entrypoint, "the dispatcher must launch the shim module"
    assert "--host 127.0.0.1" in entrypoint, "whisper itself must stay on loopback; only the shim is published"


# --- 5. build-time ARG scope ---------------------------------------------------


# A Dockerfile ARG declared BEFORE the first FROM lives outside every stage:
# RUN/COPY/ENV inside a stage expand it to the empty string (empirically
# pinned on Docker 28 — only an in-stage `ARG NAME`, bare being enough since
# it inherits the global default or the predefined platform value, makes the
# name visible). `docker build --check` does not catch it (lint never
# evaluates RUN), so the first real build would have died at the NATS step
# with "unsupported TARGETARCH: ". This checker closes that gap.
_PREDEFINED_PLATFORM_ARGS = {
    "TARGETARCH",
    "TARGETPLATFORM",
    "TARGETOS",
    "TARGETVARIANT",
    "BUILDARCH",
    "BUILDPLATFORM",
    "BUILDOS",
    "BUILDVARIANT",
}
_REF_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)")
_ARG_RE = re.compile(r"^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)")
_ENV_RE = re.compile(r"^\s*ENV\s+(.+)$")
_INSTR_RE = re.compile(r"^(RUN|COPY|ADD|ENV|LABEL|ENTRYPOINT|CMD|WORKDIR|USER|EXPOSE|VOLUME|SHELL|HEALTHCHECK)\b")


def _logical_lines(text: str) -> list[str]:
    """One entry per Dockerfile instruction: backslash continuations joined."""
    out: list[str] = []
    for raw in text.splitlines():
        if out and out[-1].endswith("\\"):
            out[-1] = out[-1][:-1] + raw
        else:
            out.append(raw)
    return out


def _stage_scope_problems(text: str) -> list[str]:
    """Names referenced inside a stage that are not visible in that stage."""
    global_args: set[str] = set()
    stage_args: set[str] = set()
    stage_env: set[str] = set()
    stage = 0
    problems: list[str] = []
    for lineno, line in enumerate(_logical_lines(text), 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.upper().startswith("FROM "):
            stage += 1
            stage_args = set()
            stage_env = set()
            continue
        arg_match = _ARG_RE.match(line)
        if arg_match:
            if stage == 0:
                global_args.add(arg_match.group(1))
            else:
                stage_args.add(arg_match.group(1))
            continue
        if stage == 0:
            continue
        env_match = _ENV_RE.match(line)
        if env_match:
            for word in env_match.group(1).split():
                if "=" in word:
                    stage_env.add(word.split("=", 1)[0])
        if not _INSTR_RE.match(stripped):
            continue
        scan = env_match.group(1) if env_match else stripped
        for name in _REF_RE.findall(scan):
            if name in stage_args or name in stage_env:
                continue
            if name in global_args or name in _PREDEFINED_PLATFORM_ARGS:
                problems.append(f"line {lineno}: ${{{name}}} is out of scope in its stage (needs an in-stage ARG)")
    return problems


def test_stage_scope_checker_catches_the_original_bug():
    """The checker itself, on synthetic files: the exact defect the AGX
    dockerfile shipped with must be flagged, the fixed shapes must pass."""
    bad_targetarch = 'ARG TARGETARCH\nFROM alpine:3.20\nRUN echo "$TARGETARCH" > /o\n'
    good_targetarch = 'FROM alpine:3.20\nARG TARGETARCH\nRUN echo "$TARGETARCH" > /o\n'
    bad_global_default = 'ARG GREETING=hi\nFROM alpine:3.20\nRUN echo "$GREETING"\n'
    good_global_default = 'ARG GREETING=hi\nFROM alpine:3.20\nARG GREETING\nRUN echo "$GREETING"\n'
    bad_continuation = 'FROM alpine:3.20\nRUN true \\\n && echo "$TARGETARCH"\n'
    good_env_ref = "ARG GREETING=hi\nFROM alpine:3.20\nARG GREETING\nENV HELLO=${GREETING}\nRUN true\n"
    assert _stage_scope_problems(bad_targetarch), "missed the bug that shipped"
    assert not _stage_scope_problems(good_targetarch)
    assert _stage_scope_problems(bad_global_default)
    assert not _stage_scope_problems(good_global_default)
    assert _stage_scope_problems(bad_continuation), "continuations must be joined before checking"
    assert not _stage_scope_problems(good_env_ref)


@pytest.mark.parametrize(
    "dockerfile",
    [AGX_DOCKER, SPARK_DOCKER],
    ids=["agx", "spark"],
)
def test_dockerfile_args_reach_the_stages_that_use_them(dockerfile: Path):
    """Every ARG a RUN/COPY/ENV consumes must be declared in that stage —
    pre-FROM declarations do not reach it, and the failure is an empty string
    at build time, invisible to `docker build --check`."""
    problems = _stage_scope_problems(dockerfile.read_text(encoding="utf-8"))
    assert not problems, f"{dockerfile.name}:\n  " + "\n  ".join(problems)


# --- 6. it still parses -------------------------------------------------------


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not available")
def test_agx_compose_config_resolves():
    """`docker compose config` is the ground truth for interpolation, anchors
    and the CPU overlay on top of a different compose file."""
    for args in (
        ["-f", str(AGX_COMPOSE)],
        ["-f", str(AGX_COMPOSE), "-f", str(REPO_ROOT / "spark.compose.cpu.yml")],
    ):
        proc = subprocess.run(
            ["docker", "compose", *args, "config", "-q"],
            cwd=REPO_ROOT,
            env={
                **__import__("os").environ,
                "SPARKNET_QDRANT_API_KEY": "placeholder",
                "SPARKNET_SHARED_SECRET": "placeholder",
            },
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0 and "Cannot connect to the Docker daemon" in proc.stderr:
            pytest.skip("no docker daemon")
        assert proc.returncode == 0, f"docker compose config failed:\n{proc.stderr}"


# --- 6. typed memory service -------------------------------------------------


def test_memory_service_is_loopback_and_one_plane(agx: dict, spark: dict):
    """Both node surfaces run the same Go memory service, on loopback only.
    It is the single per-vault memory plane for OpenCode and Open WebUI; a
    second surface-local store would make the same vault mean two things."""
    for services in (agx, spark):
        memory = services["memory"]
        assert memory["container_name"] == "sparknet-memory"
        assert memory["command"] == ["memory"]
        assert _ports(memory) == {"4110"}
        assert "127.0.0.1" in str(memory["ports"][0]), "memory must never be a fabric edge"
        assert memory["environment"]["GOSPARK_MEMORY_LISTEN"] == "127.0.0.1:4110"
        assert memory["environment"]["GOSPARK_MEMORY_STATE"].endswith("/.state/memory")
        assert memory.get("healthcheck"), "memory needs a readiness healthcheck"
        assert memory.get("volumes"), "memory needs the state mount and the knowledge roots"
    keys = {k for k in agx["memory"]["environment"] if k.startswith("GOSPARK_MEMORY_")}
    assert keys == {k for k in spark["memory"]["environment"] if k.startswith("GOSPARK_MEMORY_")}
    for key in keys:
        assert agx["memory"]["environment"][key] == spark["memory"]["environment"][key]


def test_memory_binary_is_in_both_images_and_the_entrypoint():
    """The dispatcher starts the service by name; a missing binary is a build
    error, not a restart loop on a real node."""
    for docker in (SPARK_DOCKER, AGX_DOCKER):
        text = docker.read_text(encoding="utf-8")
        assert "test -x /usr/local/bin/sparknet-memory" in text, f"{docker}: memory binary is not asserted"
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert re.search(r"^\s+memory\)", entrypoint, re.M), "dispatcher has no memory subcommand"
    assert "cmd_memory()" in entrypoint
    assert "sparknet-memory" in entrypoint


def test_memory_gateway_is_the_only_front_door(agx: dict, spark: dict):
    for services in (agx, spark):
        gateway = services["memory-gateway"]
        assert gateway["container_name"] == "sparknet-memory-gateway"
        assert gateway["command"] == ["memory-gateway"]
        assert gateway.get("network_mode") == "host"
        assert gateway["environment"]["SPARKNET_MEMORY_GATEWAY_BIND"] == "127.0.0.1:4093"
        assert gateway["environment"]["SPARKNET_MEMORY_URL"] == "http://127.0.0.1:4110"
        assert gateway.get("healthcheck")
    keys = {
        k
        for k in agx["memory-gateway"]["environment"]
        if k.startswith(("SPARKNET_MEMORY_", "GOSPARK_MEMORY_", "SPARKNET_USER_"))
    }
    for key in keys:
        assert agx["memory-gateway"]["environment"][key] == spark["memory-gateway"]["environment"][key]
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
    assert re.search(r"^\s+memory-gateway\)", entrypoint, re.M)
    assert "cmd_memory_gateway()" in entrypoint
    assert "sparknet-memory-gateway.py" in entrypoint
