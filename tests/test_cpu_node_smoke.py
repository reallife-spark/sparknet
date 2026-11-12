"""Bring the whole node graph up with no GPU, and prove the round trip.

The live node image needs a Spark. What does *not* need one is the packaging: the
CPU-only overlay (``spark.compose.cpu.yml``) drops the NVIDIA device reservations
and runs the OpenAI-compatible stub engine, so ``nats vllm compute agent gpu``
comes up on this host and the agent↔vLLM↔compute path answers.

Two tiers:

* ``test_cpu_overlay_switches_the_engine`` — pure ``docker compose config``:
  cheap, no containers, and still catches the two things that would silently
  break the CPU path (the stub not being selected, the GPU reservation surviving).
* ``test_cpu_graph_boots_and_answers`` — the actual bring-up, opt-in via
  ``SPARKNET_CONTAINER_TESTS=1`` (``make container-test``). It never publishes a
  host port and skips if a real node's containers are already running, so it
  cannot fight a node on the same box.

The GPU sidecar is fed a synthetic fixture, so it reports ``available=true`` —
telemetry only. This proves plumbing; real driver readings remain
``DoD: confirm: user``.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
BASE = REPO_ROOT / "spark.compose.yml"
CPU = REPO_ROOT / "spark.compose.cpu.yml"
FIXTURE = REPO_ROOT / "scripts" / "make-gpu-fixture.py"

pytestmark = pytest.mark.integration

SERVICES = ("nats", "vllm", "compute", "agent")


def _docker() -> str | None:
    from shutil import which

    return which("docker")


def _compose(*args: str, env: dict[str, str] | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
    docker = _docker()
    assert docker is not None
    full_env = dict(os.environ)
    full_env.setdefault("SPARKNET_QDRANT_API_KEY", "placeholder")
    full_env.update(env or {})
    return subprocess.run(
        [docker, "compose", "-f", os.fspath(BASE), "-f", os.fspath(CPU), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=full_env,
        cwd=REPO_ROOT,
    )


def test_cpu_overlay_switches_the_engine() -> None:
    if _docker() is None:
        pytest.skip("docker not available")
    proc = _compose("config", env={"VLLM_SERVICE_CMD": "vllm-stub"})
    assert proc.returncode == 0, proc.stderr
    text = proc.stdout
    # the stub engine is selected for the vllm service ...
    assert "vllm-stub" in text
    # ... and the GPU reservation is gone (or the service would not start here)
    assert "reservations: {}" in text or "capabilities:\n                - gpu" not in text


# --- the opt-in bring-up ------------------------------------------------------


def _no_ports_override(path: Path) -> None:
    """Drop every host port publication: this host already uses 8000 and 4222."""
    path.write_text(
        "services:\n"
        + "".join(
            f"  {svc}:\n    ports: !reset []\n" for svc in (*SERVICES, "gpu", "control", "kvrouter", "webui", "qdrant")
        ),
        encoding="utf-8",
    )


def _running_node_containers(docker: str) -> list[str]:
    out = subprocess.run(
        [docker, "ps", "-a", "--filter", "name=sparknet-", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def _healthy(docker: str, name: str) -> str:
    return subprocess.run(
        [docker, "inspect", "-f", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}", name],
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_cpu_graph_boots_and_answers(tmp_path: Path) -> None:
    if os.environ.get("SPARKNET_CONTAINER_TESTS") != "1":
        pytest.skip("opt-in: set SPARKNET_CONTAINER_TESTS=1 (make container-test)")
    docker = _docker()
    if docker is None:
        pytest.skip("docker not available")
    if _running_node_containers(docker):
        pytest.skip("a sparknet node is already running on this host; not disturbing it")

    state = tmp_path / "state"
    state.mkdir()
    (state / "nats").mkdir()
    subprocess.run(
        [os.fspath(FIXTURE), "-o", os.fspath(state / "gpu-sim.json")],
        check=True,
        capture_output=True,
        text=True,
    )
    env = {
        "SPARKNET_STATE_HOST": os.fspath(state),
        "SPARKNET_NODE_ID": "smoke-01",
        "SPARKNET_ROLE": "peer",
        "SPARKNET_OVERLAY_IPV4": "10.100.0.9",
        "SPARKNET_SHARED_SECRET": "smoke-secret",
        "SPARKNET_QDRANT_API_KEY": "smoke-qdrant-key",
        "VLLM_SERVICE_CMD": "vllm-stub",
        "SPARKNET_BIND_LOCAL": "127.0.0.1",
        "SPARKNET_BIND_API": "127.0.0.1",
    }
    no_ports = tmp_path / "noports.yml"
    _no_ports_override(no_ports)

    def compose(*args: str, timeout: int = 300) -> subprocess.CompletedProcess:
        full = dict(os.environ)
        full.update(env)
        return subprocess.run(
            [
                docker,
                "compose",
                "-f",
                os.fspath(BASE),
                "-f",
                os.fspath(CPU),
                "-f",
                os.fspath(no_ports),
                *args,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=full,
            cwd=REPO_ROOT,
        )

    try:
        up = compose("up", "-d")
        assert up.returncode == 0, up.stderr + up.stdout

        deadline = time.time() + 180
        pending = set(SERVICES)
        while pending and time.time() < deadline:
            pending = {s for s in pending if _healthy(docker, f"sparknet-{s}") != "healthy"}
            if pending:
                time.sleep(3)
        assert not pending, f"services never became healthy: {sorted(pending)}"

        def exec_curl(url: str, payload: str | None = None) -> str:
            args = [docker, "exec", "sparknet-agent", "curl", "-fsS", url]
            if payload:
                args += ["-H", "content-type: application/json", "-d", payload]
            proc = subprocess.run(args, capture_output=True, text=True, timeout=60)
            assert proc.returncode == 0, proc.stderr or proc.stdout
            return proc.stdout

        models = json.loads(exec_curl("http://127.0.0.1:8080/v1/models"))
        assert models["data"], "the gateway exposed no models"

        chat = json.loads(
            exec_curl(
                "http://127.0.0.1:8080/v1/chat/completions",
                '{"model":"stub","messages":[{"role":"user","content":"ping"}]}',
            )
        )
        content = chat["choices"][0]["message"]["content"]
        assert "vllm-stub" in content, f"the stub engine did not answer: {content!r}"
    finally:
        compose("down", "-v")
        # the nats image writes JetStream as root; drop anything we cannot remove
        subprocess.run(
            [
                docker,
                "run",
                "--rm",
                "-v",
                f"{tmp_path}:/t",
                "--entrypoint",
                "rm",
                os.environ.get("SPARKNET_IMAGE", "sparknet-spark-node:dev"),
                "-rf",
                "/t/state",
            ],
            capture_output=True,
            text=True,
        )
