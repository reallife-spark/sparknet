"""No key material may ever be tracked.

`git` cannot un-write history, so the only safe moment to notice a private key
in the tree is *before* the commit — which is what `scripts/sparknet-keys-check.sh`
and `.githooks/pre-commit` are for. Three independent defences, each tested
here on a throwaway directory rather than on the repository, so the tests can
plant a key on purpose:

1. `.gitignore` blocks the key-shaped names;
2. `keys-check` fails on a tracked key-shaped name or a PEM block, and proves
   the `.gitignore` backstop is still present;
3. the pre-commit hook actually calls it.

A key on disk (`.state/keys/`) is legitimate — private keys live there at mode
0600. What is not legitimate is a loose mode or a tracked copy.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHECKER = REPO_ROOT / "scripts" / "sparknet-keys-check.sh"
HOOK = REPO_ROOT / ".githooks" / "pre-commit"
KEY_PATTERNS = ("*.ed25519", "*.pem", "*.key", "privkey*", "id_ed25519*", "*.seed")


def run_checker(*args: Path | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(CHECKER), *(str(a) for a in args)],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )


@pytest.fixture()
def scratch(tmp_path: Path) -> Path:
    """A standalone directory (no .git) with a complete .gitignore."""
    (tmp_path / ".gitignore").write_text("\n".join(KEY_PATTERNS) + "\n")
    return tmp_path


# --- the checker --------------------------------------------------------------


def test_the_repository_is_clean():
    result = run_checker()
    assert result.returncode == 0, result.stderr
    assert "clean" in result.stdout


def test_the_peer_vault_is_clean():
    result = run_checker(REPO_ROOT / "peer-node")
    assert result.returncode == 0, result.stderr


def test_a_key_shaped_name_fails(scratch: Path):
    (scratch / "node.key").write_text("whatever")
    result = run_checker(scratch)
    assert result.returncode == 1
    assert "node.key" in result.stderr


@pytest.mark.parametrize(
    "name",
    [
        "id_ed25519",
        "privkey-wireguard",
        "node.pem",
        "bundle.seed",
        "x.ed25519",
    ],
)
def test_every_key_shaped_name_fails(scratch: Path, name: str):
    (scratch / name).write_text("x")
    result = run_checker(scratch)
    assert result.returncode == 1, name


# The PEM marker is assembled at runtime, never written as one literal here:
# this file is itself scanned by the checker, and a tracked file containing the
# block it exists to detect is precisely what it reports.
PEM_MARKER = "-----BEGIN " + "PRIVATE KEY-----"


def test_a_pem_block_in_a_ordinary_file_fails(scratch: Path):
    (scratch / "notes.md").write_text(
        "someone pasted this:\n" + PEM_MARKER + "\nMCowBQYDK2Vw\n-----END " + "PRIVATE KEY-----\n"
    )
    result = run_checker(scratch)
    assert result.returncode == 1
    assert "private key block" in result.stderr


def test_the_gitignore_backstop_is_required(scratch: Path):
    (scratch / ".gitignore").write_text("*.ed25519\n")  # patterns deleted
    result = run_checker(scratch)
    assert result.returncode == 1
    assert ".gitignore does not block" in result.stderr


def test_a_missing_gitignore_is_not_a_pass(scratch: Path):
    """Failing open on a tree with no backstop at all would defeat the point."""
    (scratch / ".gitignore").unlink()
    (scratch / "loose.key").write_text("x")
    result = run_checker(scratch)
    assert result.returncode == 1


def test_a_loose_state_key_fails(scratch: Path):
    keys = scratch / ".state" / "keys"
    keys.mkdir(parents=True, mode=0o700)
    (keys / "user.ed25519").write_text("private")
    os.chmod(keys, 0o700)
    os.chmod(keys / "user.ed25519", 0o644)
    result = run_checker(scratch)
    assert result.returncode == 1
    assert "0600" in result.stderr


def test_a_loose_state_dir_fails(scratch: Path):
    """The directory the key sits in is part of the key's protection."""
    state = scratch / ".state"
    state.mkdir(mode=0o755)
    (state / "keys").mkdir(mode=0o700)
    result = run_checker(scratch)
    assert result.returncode == 1
    assert ".state is mode" in result.stderr and "0700" in result.stderr


def test_the_peers_state_dir_is_locked_down():
    state = REPO_ROOT / "peer-node" / ".state"
    if not state.is_dir():
        pytest.skip("no key generated on this node yet")
    assert oct(state.stat().st_mode & 0o777) == "0o700"


def test_a_properly_permitted_state_key_passes(scratch: Path):
    (scratch / ".state").mkdir(mode=0o700)
    keys = scratch / ".state" / "keys"
    keys.mkdir(parents=True, mode=0o700)
    (keys / "user.ed25519").write_text("private")
    os.chmod(keys, 0o700)
    os.chmod(keys / "user.ed25519", 0o600)
    result = run_checker(scratch)
    assert result.returncode == 0, result.stderr


# --- non-key secrets (.state/secrets/) ---------------------------------------
#
# A key-ed25519 and an API token are different objects with the same
# requirement: nothing looser than its owner. The resource-first helper reads
# .state/secrets/build-nvidia.env, so the directory is gated like the key store.


def test_a_loose_state_secret_fails(scratch: Path):
    secrets = scratch / ".state" / "secrets"
    secrets.mkdir(parents=True, mode=0o700)
    (secrets / "build-nvidia.env").write_text("BUILD_NVIDIA_API_KEY=nvapi-secret\n")
    os.chmod(secrets, 0o700)
    os.chmod(secrets / "build-nvidia.env", 0o644)
    result = run_checker(scratch)
    assert result.returncode == 1
    assert "0600" in result.stderr


def test_a_loose_state_secrets_dir_fails(scratch: Path):
    state = scratch / ".state"
    state.mkdir(mode=0o700)
    (state / "secrets").mkdir(mode=0o755)
    result = run_checker(scratch)
    assert result.returncode == 1
    assert ".state/secrets is mode" in result.stderr and "0700" in result.stderr


def test_a_properly_permitted_state_secret_passes(scratch: Path):
    (scratch / ".state").mkdir(mode=0o700)
    secrets = scratch / ".state" / "secrets"
    secrets.mkdir(parents=True, mode=0o700)
    (secrets / "build-nvidia.env").write_text("BUILD_NVIDIA_API_KEY=nvapi-secret\n")
    os.chmod(secrets, 0o700)
    os.chmod(secrets / "build-nvidia.env", 0o600)
    result = run_checker(scratch)
    assert result.returncode == 0, result.stderr


# --- the backstop -------------------------------------------------------------


@pytest.mark.parametrize("rel", [".gitignore", "peer-node/.gitignore"])
def test_the_gitignore_blocks_every_pattern(rel: str):
    lines = set((REPO_ROOT / rel).read_text().splitlines())
    missing = [p for p in KEY_PATTERNS if p not in lines]
    assert not missing, f"{rel} does not block {missing}"


# --- the hook -----------------------------------------------------------------


def test_the_hook_exists_and_calls_the_checker():
    assert HOOK.is_file()
    assert os.access(HOOK, os.X_OK), ".githooks/pre-commit is not executable"
    body = HOOK.read_text()
    assert "sparknet-keys-check.sh" in body
    assert "show-toplevel" in body


def test_the_hook_wires_up():
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert "core.hooksPath .githooks" in makefile
    # Activation is per clone, on purpose: this assertion must not depend on
    # this machine having run `make hooks`.
    configured = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    ).stdout.strip()
    assert configured in ("", ".githooks")


def test_the_hook_blocks_a_bad_commit(tmp_path: Path):
    """End to end: staged key → hook refuses; removed key → hook passes."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / ".githooks").mkdir(exist_ok=True)
    shutil.copy(CHECKER, tmp_path / "scripts" / "sparknet-keys-check.sh")
    shutil.copy(HOOK, tmp_path / ".githooks" / "pre-commit")
    os.chmod(tmp_path / ".githooks" / "pre-commit", 0o755)
    (tmp_path / ".gitignore").write_text("\n".join(KEY_PATTERNS) + "\n")

    (tmp_path / "leaked.key").write_text(PEM_MARKER + "\nx\n")
    subprocess.run(["git", "add", "-f", "leaked.key"], cwd=tmp_path, check=True)
    bad = subprocess.run(["bash", ".githooks/pre-commit"], cwd=tmp_path, capture_output=True, text=True)
    assert bad.returncode == 1, bad.stdout + bad.stderr

    subprocess.run(["git", "rm", "-q", "--cached", "leaked.key"], cwd=tmp_path, check=True)
    (tmp_path / "leaked.key").unlink()
    good = subprocess.run(["bash", ".githooks/pre-commit"], cwd=tmp_path, capture_output=True, text=True)
    assert good.returncode == 0, good.stdout + good.stderr
