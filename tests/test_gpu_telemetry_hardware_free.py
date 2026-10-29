"""Hardware-free GPU telemetry: the opt-in sim backend, through the real binary.

The live GPU legs need a GB10 and an NVIDIA driver, so they cannot run in CI or
on a dev box. What *can* be proven without hardware is that the shipped
``sparknet-gpu`` binary carries the synthetic backend, that it is opt-in, and
that a host with no driver still answers honestly. That is what this file does:

* the fixture generator (``scripts/make-gpu-fixture.py``) produces a document the
  real binary accepts and reports ``available=true`` for;
* the same works via the environment (``SPARKNET_GPU_FIXTURE``) and via the flag
  (``-sim-fixture``), so both opt-in paths are covered;
* with nothing configured, the binary degrades to ``available=false`` with a
  reason — the behaviour a driverless host must always keep.

It is telemetry-only: nothing here signs, grants or places. The Go unit tests in
goSpark (``internal/gputel/sim``) cover the collector itself; this file proves
the wiring in the artifact the node image actually ships.

Skipped unless ``sparknet-gpu`` is built (``make -C <gospark> build-gpu``).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_SCRIPT = REPO_ROOT / "scripts" / "make-gpu-fixture.py"
GOSPARK_DIR = Path(os.environ.get("GOSPARK_DIR", REPO_ROOT / "gospark"))
GPU_BIN = GOSPARK_DIR / "bin" / "sparknet-gpu"

pytestmark = pytest.mark.integration


def _have_gpu_binary() -> bool:
    return GPU_BIN.is_file() and os.access(GPU_BIN, os.X_OK)


requires_binary = pytest.mark.skipif(
    not _have_gpu_binary(),
    reason=f"sparknet-gpu not built at {GPU_BIN} (run: make -C {GOSPARK_DIR} build-gpu)",
)


def _collect(args: list[str], env: dict[str, str] | None = None) -> dict:
    """Run sparknet-gpu once and return the parsed telemetry envelope."""
    full_env = dict(os.environ)
    full_env.pop("SPARKNET_GPU_FIXTURE", None)
    full_env.pop("SPARKNET_GPU_SIM_CFG", None)
    if env:
        full_env.update(env)
    proc = subprocess.run(
        [str(GPU_BIN), "-node-id", "test-node", *args],
        capture_output=True,
        text=True,
        timeout=60,
        env=full_env,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["gpu_telemetry"]


@pytest.fixture()
def fixture_file(tmp_path: Path) -> Path:
    out = tmp_path / "gpu.json"
    subprocess.run(
        [os.fspath(FIXTURE_SCRIPT), "-o", os.fspath(out)],
        check=True,
        capture_output=True,
        text=True,
    )
    return out


@requires_binary
def test_generator_fixture_is_accepted_by_binary(fixture_file: Path) -> None:
    """The document scripts/make-gpu-fixture.py writes is one the binary accepts."""
    telemetry = _collect(["-sim-fixture", os.fspath(fixture_file)])
    assert telemetry["available"] is True
    assert telemetry["source"]  # some collector answered (sim, possibly merged)
    assert any(g["name"] == "GB10-SIM" for g in telemetry.get("gpus", []))


@requires_binary
def test_flag_and_environment_opt_ins_agree(fixture_file: Path) -> None:
    via_flag = _collect(["-sim-fixture", os.fspath(fixture_file)])
    via_env = _collect([], env={"SPARKNET_GPU_FIXTURE": os.fspath(fixture_file)})
    assert via_flag["available"] is True
    assert via_env["available"] is True
    assert via_flag.get("gpus") == via_env.get("gpus")


@requires_binary
def test_no_fixture_degrades_honestly() -> None:
    """Default (nothing configured): never a fake 'available', always a reason."""
    telemetry = _collect([])
    assert telemetry["available"] is False
    assert telemetry.get("reason"), "an unavailable snapshot must explain itself"


@requires_binary
def test_unavailable_fixture_is_not_laundered(tmp_path: Path) -> None:
    """A degraded fixture stays degraded: the sim cannot invent health."""
    out = tmp_path / "down.json"
    subprocess.run(
        [os.fspath(FIXTURE_SCRIPT), "--unavailable", "-o", os.fspath(out)],
        check=True,
        capture_output=True,
        text=True,
    )
    telemetry = _collect(["-sim-fixture", os.fspath(out)])
    assert telemetry["available"] is False


def test_fixture_generator_is_git_executable() -> None:
    """The generator ships executable; a bare clone must be able to run it."""
    assert FIXTURE_SCRIPT.is_file()
    assert os.access(FIXTURE_SCRIPT, os.X_OK), f"{FIXTURE_SCRIPT} must be executable"
