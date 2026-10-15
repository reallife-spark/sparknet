"""The election-to-escalation arc, run inside the built node image.

``scripts/sparknet-rehearsal.sh`` already drives the whole arc on the host, in
real trees. This test drives the *same* script inside the shipped image
(``scripts/sparknet-election-rehearsal-container.sh``), which is the claim the
host rehearsal cannot make: that the packaged toolchain — the baked Python, the
ceremony scripts as shipped, the container runtime — can form a trust root,
start the isolated signer, publish a registry entry the elected key signs, and
refuse every escalation attempt.

It is deliberately opt-in. Building a master bundle and running the ceremony
takes minutes, so it is excluded from the default suite and only runs when
``SPARKNET_CONTAINER_TESTS=1`` is set (see ``make container-test``). When it does
run, a missing Docker daemon or image skips rather than fails: absence of the
artifact is not a protocol failure.

What this still does not prove — and cannot, in a container network namespace —
is WireGuard on a real NIC, systemd reboot survival, or deployed containment.
Those remain ``DoD: confirm: user``.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WRAPPER = REPO_ROOT / "scripts" / "sparknet-election-rehearsal-container.sh"
IMAGE = os.environ.get("SPARKNET_IMAGE", "sparknet-spark-node:dev")

pytestmark = [pytest.mark.integration, pytest.mark.slow]


def _docker() -> str | None:
    from shutil import which

    return which("docker")


def _image_present(docker: str) -> bool:
    return (
        subprocess.run(
            [docker, "image", "inspect", IMAGE],
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )


def test_election_rehearsal_runs_inside_the_node_image() -> None:
    if os.environ.get("SPARKNET_CONTAINER_TESTS") != "1":
        pytest.skip("opt-in: set SPARKNET_CONTAINER_TESTS=1 (make container-test)")

    docker = _docker()
    if docker is None:
        pytest.skip("docker not available")
    if not _image_present(docker):
        pytest.skip(f"node image {IMAGE!r} not built")

    env = dict(os.environ)
    env.setdefault("SPARKNET_IMAGE", IMAGE)
    proc = subprocess.run(
        [os.fspath(WRAPPER)],
        capture_output=True,
        text=True,
        timeout=1800,  # ceremony: bundle + three nodes + signer, minutes not seconds
        env=env,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined[-4000:]
    assert "rehearsal PASSED" in combined, combined[-4000:]

    # The wrapper prints the host transcript path last; the inner rehearsal also
    # prints its own (container) path earlier, so take the last existing match.
    candidates = [Path(p) for p in re.findall(r"transcript: (\S+)", combined)]
    transcript = next((p for p in reversed(candidates) if p.is_file()), None)
    assert transcript is not None, f"no host transcript among {candidates}\n{combined[-2000:]}"
    text = transcript.read_text(encoding="utf-8")
    assert "failed: 0" in text, text[-3000:]
