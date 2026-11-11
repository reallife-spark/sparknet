"""Self-improvement runs use a detached worktree and promote only on a pass."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.integration


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


def _run(repo, patch, bench, key, *, score, promote, require_review=False, skill_eval_path=None):
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
    if require_review:
        command.append("--require-review")
    if skill_eval_path is not None:
        command.extend(["--skill-eval", str(skill_eval_path)])
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


# --- the skill-evaluation gate ------------------------------------------------

BLOCK = {"severity": "block", "rule": "review.defect", "message": "the patch leaves a broken path"}
WARN = {"severity": "warn", "rule": "review.naming", "message": "the name hides the intent"}


def _review(*, verdict="pass", findings=None, **overrides):
    skill_eval = _load("skill_eval_for_improve_test", "sparknet-skill-eval.py")
    fields = {
        "eval_id": "review-1",
        "skill": {"name": "code-review", "origin": "mattpocock"},
        "subject": {"kind": "self-improve-candidate", "ref": "candidate/1"},
        "verdict": verdict,
        "findings": findings or [],
        "evaluator": {"kind": "harness", "id": "test"},
        "created_at": "2026-11-11T00:00:00Z",
    }
    fields.update(overrides)
    return skill_eval.make_record(**fields)


METRICS = {"score": 1.0}
THRESHOLDS = {"score": 0.9}


def test_non_gate_mode_is_byte_identical_to_the_legacy_decision():
    verdict = improve.evaluate(METRICS, THRESHOLDS)
    assert verdict["decision"] == "promote"
    assert set(verdict) == {"decision", "metrics"}


def test_gate_blocks_promotion_without_a_review():
    verdict = improve.evaluate(METRICS, THRESHOLDS, gate=True)
    assert verdict["decision"] == "pending"
    assert verdict["review"] == {"passed": False, "reason": "missing"}


def test_gate_blocks_a_warn_verdict():
    verdict = improve.evaluate(METRICS, THRESHOLDS, gate=True, skill_eval=_review(verdict="warn", findings=[WARN]))
    assert verdict["decision"] == "pending"
    assert verdict["review"]["passed"] is False
    assert verdict["review"]["reason"] == "warn"


def test_gate_blocks_a_failing_verdict():
    verdict = improve.evaluate(METRICS, THRESHOLDS, gate=True, skill_eval=_review(verdict="fail", findings=[BLOCK]))
    assert verdict["decision"] == "pending"
    assert verdict["review"]["reason"] == "fail"


def test_gate_blocks_a_tampered_record():
    record = _review()
    record["verdict"] = "warn"
    verdict = improve.evaluate(METRICS, THRESHOLDS, gate=True, skill_eval=record)
    assert verdict["decision"] == "pending"
    assert verdict["review"]["reason"] == "invalid"


def test_gate_blocks_an_authority_shaped_record():
    record = _review()
    record["grant"] = {"scope": "vault"}
    verdict = improve.evaluate(METRICS, THRESHOLDS, gate=True, skill_eval=record)
    assert verdict["decision"] == "pending"
    assert verdict["review"]["reason"] == "invalid"


def test_gate_promotes_only_on_pass_and_thresholds():
    verdict = improve.evaluate(METRICS, THRESHOLDS, gate=True, skill_eval=_review())
    assert verdict["decision"] == "promote"
    assert verdict["review"] == {"passed": True, "reason": "pass"}


def test_a_benchmark_regression_still_rolls_back_with_a_passing_review():
    verdict = improve.evaluate({"score": 0.5}, THRESHOLDS, gate=True, skill_eval=_review())
    assert verdict["decision"] == "rollback"


def test_cli_require_review_without_a_record_never_promotes(tmp_path):
    repo, patch, bench, key = _repo(tmp_path)
    result = _run(repo, patch, bench, key, score=1.0, promote=True, require_review=True)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    assert summary["decision"] == "pending"
    assert (repo / "app.txt").read_text() == "old\n"


def test_cli_require_review_with_a_passing_record_promotes(tmp_path):
    repo, patch, bench, key = _repo(tmp_path)
    record_path = tmp_path / "review.json"
    record_path.write_text(json.dumps(_review()))
    result = _run(repo, patch, bench, key, score=1.0, promote=True, require_review=True, skill_eval_path=record_path)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    assert summary["decision"] == "promote"
    assert (repo / "app.txt").read_text() == "old\nnew\n"


def test_cli_require_review_with_a_failing_record_never_promotes(tmp_path):
    repo, patch, bench, key = _repo(tmp_path)
    record_path = tmp_path / "review.json"
    record_path.write_text(json.dumps(_review(verdict="fail", findings=[BLOCK])))
    result = _run(repo, patch, bench, key, score=1.0, promote=True, require_review=True, skill_eval_path=record_path)
    assert result.returncode == 0, result.stdout + result.stderr
    summary = json.loads(result.stdout)
    assert summary["decision"] == "pending"
    assert (repo / "app.txt").read_text() == "old\n"
