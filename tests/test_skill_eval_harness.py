"""Golden-diff evaluation for the review skills.

The golden set pins the findings a competent reviewer must produce for a small
diff (and a clean diff that must produce none). The offline runner uses the
skills' explicit rule vocabulary, so it is deterministic and needs no model.
Live scoring is operator-gated and is not exercised here.

A gate that cannot fail is not a gate: one test disables a rule and requires the
evaluation to go red.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from sparknet_loader import load_by_path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sparknet-skill-eval.py"
GOLDEN = ROOT / "tests" / "skill-evals" / "code-review-golden.json"


def _skill_eval():
    return load_by_path("sparknet_skill_eval_harness_test", ROOT / "shared" / "sparknet-skill-eval.py")


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--golden", str(GOLDEN), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_golden_set_names_the_rule_vocabulary() -> None:
    golden = json.loads(GOLDEN.read_text())
    assert golden["schema"] == "sparknet-skill-eval-golden/1"
    assert golden["skill"] == "code-review"
    assert golden["rules"] == ["tdd.missing-test", "security.shell-true", "authority.second-copy"]
    assert {case["id"] for case in golden["cases"]} == {
        "tdd-missing-test",
        "security-shell-true",
        "authority-second-copy",
        "clean-test-only-change",
    }


def test_the_offline_evaluation_passes_the_golden_set_and_emits_a_record() -> None:
    result = _run()
    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["precision"] == 1.0
    assert payload["recall"] == 1.0
    record = payload["record"]
    assert record["schema"] == "sparknet-skill-eval/1"
    assert record["verdict"] == "pass"
    assert record["skill"]["name"] == "code-review"
    assert record["subject"]["kind"] == "skill"
    assert _skill_eval().validate_record(record) == record


def test_disabling_a_rule_makes_the_evaluation_fail() -> None:
    result = _run("--disable-rule", "tdd.missing-test")
    assert result.returncode == 2, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["recall"] < 1.0
    assert payload["record"]["verdict"] == "fail"
    assert any(finding["rule"] == "golden.miss" for finding in payload["record"]["findings"])


def test_the_runner_needs_no_network() -> None:
    source = SCRIPT.read_text()
    for forbidden in ("urllib", "requests", "http.client", "socket"):
        assert forbidden not in source, f"offline runner reaches the network via {forbidden}"
