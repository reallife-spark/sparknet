"""Self-improvement runs use a detached worktree and promote only on a pass."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from sparknet_loader import load_by_path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sparknet-self-improve.py"
SHARED = ROOT / "shared"


def _load(name, filename):
    return load_by_path(name, SHARED / filename)


improve = _load("self_improve_test", "sparknet-self-improve.py")
authz = _load("self_improve_authz_test", "sparknet-authz.py")


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "tester"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "tester@example.invalid"], check=True)
    (repo / "app.txt").write_text("old\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "base"], check=True)
    patch = tmp_path / "change.patch"
    patch.write_text("--- a/app.txt\n+++ b/app.txt\n@@ -1 +1,2 @@\n old\n+new\n")
    bench = tmp_path / "bench.py"
    bench.write_text("import json, sys; print(json.dumps({'score': float(sys.argv[1])}))\n")
    private_b64, _public_b64 = authz.generate_keypair()
    key = tmp_path / "node.key"
    key.write_text(private_b64 + "\n")
    key.chmod(0o600)
    return repo, patch, bench, key


def _run(repo, patch, bench, key, *, score, promote):
    command = [
        sys.executable,
        str(SCRIPT),
        "--repo",
        str(repo),
        "--patch",
        str(patch),
        "--benchmark",
        f"{sys.executable} {bench} {score}",
        "--thresholds",
        json.dumps({"score": 0.9}),
        "--state-dir",
        str(repo.parent / "state"),
        "--key-file",
        str(key),
        "--mode",
        "auto",
    ]
    if promote:
        command.append("--promote")
    return subprocess.run(command, capture_output=True, text=True, check=False)


def test_passing_run_promotes_and_is_signed(tmp_path):
    repo, patch, bench, key = _repo(tmp_path)
    result = _run(repo, patch, bench, key, score=1.0, promote=True)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    assert summary["decision"] == "promote"
    assert (repo / "app.txt").read_text() == "old\nnew\n"
    record = json.loads(Path(summary["run"]).read_text())
    public = authz.load_private_key(key).public_key()
    assert improve.verify_run(record, public, authz) is True
    assert record["mode"] == "worktree"


def test_failing_run_rolls_back_and_leaves_repo_unchanged(tmp_path):
    repo, patch, bench, key = _repo(tmp_path)
    result = _run(repo, patch, bench, key, score=0.5, promote=True)
    assert result.returncode == 2
    assert (repo / "app.txt").read_text() == "old\n"
    state = repo.parent / "state" / "self-improve"
    assert not list((state / "worktrees").glob("*")) if (state / "worktrees").is_dir() else True
