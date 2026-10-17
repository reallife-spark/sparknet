"""The cluster-join path: `sparknet-node-setup.sh --master-pub/--registry`.

A standalone node runs open and self-signed — correct for an appliance, wrong
once the node is a member of the elected fabric. Joining hands the node the two
artefacts the election produced (the Master's operational public key and a
Master-signed registry entry) and the env-file carries them to the goSpark agent.

These tests drive the setup script against a throwaway copy of itself with a
stubbed `docker`, so they exercise the real argument parsing, the resolve step
and the rendered env-file without building an image or touching the host state
tree. The companion test for the *signature* itself — that a registry staged
this way really verifies in both languages — is
`tests/test_registry_crossverify.py`.

The entrypoint's fail-closed leg is here too: a staged registry with no pinned
key must refuse to start the agent rather than fall back to a self-minted trust
anchor the Master-signed entries do not cover.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SETUP = REPO_ROOT / "sparknet-node-setup.sh"
ENTRYPOINT = REPO_ROOT / "spark-entrypoint.sh"
GOSPARK_DIR = Path(os.environ.get("GOSPARK_DIR", "/mnt/knowledge/goSpark"))
CTL = GOSPARK_DIR / "bin" / "sparknetctl"

pytestmark = pytest.mark.integration

# The in-container path the env-file must carry (the state dir is a bind mount).
REGISTRY_IN_CONTAINER = "/srv/sparknet/peer-node/.state/node-authorizations.json"

MASTER_PUB = "I+8r6I3PR/sAHD5zphk5U2fPzCMGBrGZYMPf6AJMpeU="


@pytest.fixture()
def node(tmp_path: Path) -> Path:
    """A throwaway repo holding the setup script, compose files and stub docker."""
    for name in ("sparknet-node-setup.sh", "spark.compose.yml", "spark.compose.cpu.yml"):
        shutil.copy(REPO_ROOT / name, tmp_path / name)
    (tmp_path / "sparknet-node-setup.sh").chmod(0o755)

    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    docker = stub_bin / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 0\n")
    docker.chmod(0o755)
    return tmp_path


def _run(node: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{node / 'bin'}:{env['PATH']}"
    env.pop("SPARKNET_MASTER_PUB", None)
    env.pop("SPARKNET_REGISTRY_FILE", None)
    return subprocess.run(
        ["bash", str(node / "sparknet-node-setup.sh"), *args],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=os.fspath(node),
    )


def _env_file(node: Path) -> dict[str, str]:
    text = (node / "peer-node" / ".state" / "spark.env").read_text()
    out: dict[str, str] = {}
    for line in text.splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            out[key] = value
    return out


def _registry(node: Path, master_pub: str, name: str = "registry.json") -> Path:
    """A minimal Master-signed-shaped registry document (signature not exercised here)."""
    path = node / name
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "master_public_key_b64": master_pub,
                "authorizations": [],
            },
            indent=2,
        )
    )
    return path


def test_join_stages_registry_and_pins_master_pub(node: Path) -> None:
    """--master-pub + --registry: the env-file carries both, the registry is staged."""
    reg = _registry(node, MASTER_PUB)
    proc = _run(
        node,
        "--no-build",
        "--master-pub",
        MASTER_PUB,
        "--registry",
        str(reg),
        "up",
    )
    assert proc.returncode == 0, proc.stderr

    env = _env_file(node)
    assert env["SPARKNET_MASTER_PUB"] == MASTER_PUB
    assert env["GOSPARK_REGISTRY_FILE"] == REGISTRY_IN_CONTAINER

    staged = node / "peer-node" / ".state" / "node-authorizations.json"
    assert staged.is_file()
    assert json.loads(staged.read_text())["master_public_key_b64"] == MASTER_PUB
    assert oct(staged.stat().st_mode & 0o777) == "0o600"


def test_join_reads_master_pub_from_registry_when_not_pinned(node: Path) -> None:
    """With only --registry, the key comes from the document's master_public_key_b64.

    The weaker form, so it must be visibly logged — an operator should see that
    the key was read from the very document it authenticates.
    """
    reg = _registry(node, MASTER_PUB)
    proc = _run(node, "--no-build", "--registry", str(reg), "up")
    assert proc.returncode == 0, proc.stderr
    assert "pin it out of band" in proc.stderr

    env = _env_file(node)
    assert env["SPARKNET_MASTER_PUB"] == MASTER_PUB
    assert env["GOSPARK_REGISTRY_FILE"] == REGISTRY_IN_CONTAINER


def test_master_pub_accepts_a_file_holding_the_key(node: Path) -> None:
    """--master-pub may be a path; the env-file gets the key, not the path."""
    keyfile = node / "master.pub.b64"
    keyfile.write_text(f"  {MASTER_PUB}\n")
    proc = _run(node, "--no-build", "--master-pub", str(keyfile), "up")
    assert proc.returncode == 0, proc.stderr
    assert _env_file(node)["SPARKNET_MASTER_PUB"] == MASTER_PUB


def test_join_refuses_master_role(node: Path) -> None:
    """A master node runs the control plane (the registry authority); it cannot join one."""
    reg = _registry(node, MASTER_PUB)
    proc = _run(
        node,
        "--no-build",
        "--role",
        "master",
        "--registry",
        str(reg),
        "up",
    )
    assert proc.returncode != 0
    assert "control plane" in proc.stderr


def test_no_join_flags_leaves_node_open(node: Path) -> None:
    """Without the flags the node is standalone: no key pinned, no registry staged."""
    proc = _run(node, "--no-build", "up")
    assert proc.returncode == 0, proc.stderr
    env = _env_file(node)
    assert env["SPARKNET_MASTER_PUB"] == ""
    assert env["GOSPARK_REGISTRY_FILE"] == ""


def test_join_fails_when_registry_file_is_missing(node: Path) -> None:
    """A registry named but absent is an error, not a silent open-mode fallback."""
    proc = _run(node, "--no-build", "--registry", str(node / "nope.json"), "up")
    assert proc.returncode != 0
    assert "registry file not found" in proc.stderr


# --- entrypoint fail-closed leg ----------------------------------------------

requires_ctl = pytest.mark.skipif(
    not (CTL.is_file() and os.access(CTL, os.X_OK)),
    reason=f"sparknetctl not built at {CTL} (run: make -C {GOSPARK_DIR} build)",
)


@requires_ctl
def test_entrypoint_refuses_registry_without_pinned_master_pub(tmp_path: Path) -> None:
    """A staged registry with no SPARKNET_MASTER_PUB must not fall back to a self-minted key.

    Falling back would pin the agent to a local key the Master never signed with:
    the registry would authorise nothing, and the failure mode would be silent
    confusion rather than a refusal. The setup script always writes the key when
    it stages a registry, so this only catches a hand-edited environment.
    """
    state = tmp_path / "state"
    state.mkdir()
    env = dict(os.environ)
    env["PATH"] = f"{GOSPARK_DIR / 'bin'}:{env['PATH']}"
    env.pop("SPARKNET_MASTER_PUB", None)
    env["GOSPARK_REGISTRY_FILE"] = REGISTRY_IN_CONTAINER
    env["SPARKNET_STATE_DIR"] = str(state)
    env["SPARKNET_NODE_ID"] = "join-test"
    proc = subprocess.run(
        ["bash", str(ENTRYPOINT), "agent"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=os.fspath(tmp_path),
    )
    assert proc.returncode != 0
    assert "SPARKNET_MASTER_PUB is empty" in proc.stderr
    # The node's own identity key is minted regardless — that is not the trust
    # anchor. What must NOT appear is a self-minted *control* key standing in for
    # the elected Master, which is the fallback this refusal exists to prevent.
    assert not (state / "control.key").exists()
