"""06_Projects lifecycle: create a signed project, file a signed report.

The script is exercised as a subprocess against a throwaway vault and a fake
memory gateway. It must not need a live node; the report signature is the same
provenance implementation the vault uses.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.integration


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sparknet-project.py"
PEER = ROOT / "peer-node"
SHARED = ROOT / "shared"


def _load(name: str, filename: str):
    return load_by_path(name, SHARED / filename)


prov = _load("sparknet_provenance_project_test", "sparknet-provenance.py")


class Gateway(BaseHTTPRequestHandler):
    calls: ClassVar[list[dict]] = []
    review: ClassVar[dict | None] = None

    def log_message(self, *args):
        return

    def _reply(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.calls.append({"method": "GET", "path": self.path})
        if "/v1/delegates/runs/run-1" in self.path:
            result = {
                "summary": "Option B wins on latency.",
                "files_changed": ["NOTES/option-b.md"],
                "verification": "pytest -q",
            }
            if self.review is not None:
                result["skill_eval"] = self.review
            self._reply(
                200,
                {
                    "ok": True,
                    "run": {
                        "run_id": "run-1",
                        "status": "succeeded",
                        "harness": "command",
                        "task": {"description": "compare three options"},
                        "result": result,
                        "error": "",
                    },
                },
            )
            return
        self._reply(200, {"ok": True, "runs": []})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        self.calls.append({"method": "POST", "path": self.path, "body": body})
        self._reply(202, {"ok": True, "runs": [{"run_id": "run-1", "plan_id": "plan-1"}]})


def _run(script_args: list[str], vault: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--vault", str(vault), *script_args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_project_and_report_lifecycle(tmp_path: Path, monkeypatch) -> None:
    vault = tmp_path / "vault"
    shutil.copytree(PEER, vault, ignore=shutil.ignore_patterns(".git", ".state", ".opencode", "__pycache__"))
    state = tmp_path / "state"
    env = {**os.environ, "SPARKNET_STATE_DIR": str(state), "SPARKNET_OWNER_ID": "U-12345"}
    monkeypatch.setenv("SPARKNET_STATE_DIR", str(state))
    monkeypatch.setenv("SPARKNET_OWNER_ID", "U-12345")
    prov.user_init(vault, owner_id="U-12345", force=True)

    created = _run(["new", "alpha", "--title", "Alpha project"], vault, env)
    assert created.returncode == 0, created.stderr
    project = vault / "06_Projects" / "alpha" / "PROJECT.md"
    plan = vault / "06_Projects" / "alpha" / "PLAN.md"
    assert prov.verify_note(project, vault=vault)[0] == "valid"
    assert prov.verify_note(plan, vault=vault)[0] == "valid"

    listed = _run(["list"], vault, env)
    assert listed.returncode == 0
    payload = json.loads(listed.stdout)
    assert payload["projects"][0]["project_id"] == "alpha"

    token = state / "memory.local.token"
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text("local-token-1234567890\n")
    gateway = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    thread.start()
    try:
        env["SPARKNET_MEMORY_GATEWAY_URL"] = f"http://127.0.0.1:{gateway.server_port}"
        run = _run(["run", "alpha", "--task", "compare options"], vault, env)
        assert run.returncode == 0, run.stderr
        assert Gateway.calls[-1]["path"] == "/v1/delegates/plan"
        assert Gateway.calls[-1]["body"]["plan"]["project_id"] == "alpha"

        report = _run(["report", "alpha", "--run-id", "run-1", "--title", "Option memo"], vault, env)
        assert report.returncode == 0, report.stderr
        report_path = vault / "06_Projects" / "alpha" / "REPORTS" / report_path_name(report)
        assert report_path.is_file()
        assert "Option B wins on latency." in report_path.read_text()
        assert prov.verify_note(report_path, vault=vault)[0] == "valid"

        status = _run(["status", "alpha"], vault, env)
        assert status.returncode == 0, status.stderr
        assert json.loads(status.stdout)["project_id"] == "alpha"
    finally:
        gateway.shutdown()
        gateway.server_close()


def report_path_name(completed: subprocess.CompletedProcess[str]) -> str:
    payload = json.loads(completed.stdout)
    return Path(payload["report"]).name


# --- the reviewer gate on report filing ---------------------------------------

REVIEW_RECORD = {
    "eval_id": "review-alpha-1",
    "skill": {"name": "code-review", "origin": "mattpocock"},
    "subject": {"kind": "delegate-run", "ref": "run-1"},
    "verdict": "pass",
    "findings": [],
    "evaluator": {"kind": "agent", "id": "project-reviewer"},
    "created_at": "2026-11-11T00:00:00Z",
}


def _skill_eval():
    return _load("sparknet_skill_eval_project_test", "sparknet-skill-eval.py")


def _review(**overrides):
    fields = dict(REVIEW_RECORD)
    fields.update(overrides)
    return _skill_eval().make_record(**fields)


def _gated_vault(tmp_path: Path, monkeypatch):
    vault = tmp_path / "vault"
    shutil.copytree(PEER, vault, ignore=shutil.ignore_patterns(".git", ".state", ".opencode", "__pycache__"))
    state = tmp_path / "state"
    env = {**os.environ, "SPARKNET_STATE_DIR": str(state), "SPARKNET_OWNER_ID": "U-12345"}
    monkeypatch.setenv("SPARKNET_STATE_DIR", str(state))
    monkeypatch.setenv("SPARKNET_OWNER_ID", "U-12345")
    prov.user_init(vault, owner_id="U-12345", force=True)
    assert _run(["new", "alpha", "--title", "Alpha project"], vault, env).returncode == 0
    token = state / "memory.local.token"
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text("local-token-1234567890\n")
    gateway = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
    thread = threading.Thread(target=gateway.serve_forever, daemon=True)
    thread.start()
    env["SPARKNET_MEMORY_GATEWAY_URL"] = f"http://127.0.0.1:{gateway.server_port}"
    return vault, env, gateway


def _reports(vault: Path) -> list[Path]:
    return sorted((vault / "06_Projects" / "alpha" / "REPORTS").glob("*.md"))


def test_report_requires_review_when_asked_and_a_missing_record_blocks(tmp_path, monkeypatch):
    vault, env, gateway = _gated_vault(tmp_path, monkeypatch)
    try:
        result = _run(["report", "alpha", "--run-id", "run-1", "--require-review"], vault, env)
        assert result.returncode != 0
        assert "review" in (result.stdout + result.stderr).lower()
        assert _reports(vault) == []
    finally:
        gateway.shutdown()
        gateway.server_close()


def test_report_with_a_passing_record_is_written_and_does_not_embed_the_record(tmp_path, monkeypatch):
    vault, env, gateway = _gated_vault(tmp_path, monkeypatch)
    record = _review()
    path = tmp_path / "review.json"
    path.write_text(json.dumps(record))
    try:
        result = _run(
            ["report", "alpha", "--run-id", "run-1", "--require-review", "--skill-eval", str(path)],
            vault,
            env,
        )
        assert result.returncode == 0, result.stderr
        reports = _reports(vault)
        assert len(reports) == 1
        assert "review-alpha-1" not in reports[0].read_text()
        assert prov.verify_note(reports[0], vault=vault)[0] == "valid"
    finally:
        gateway.shutdown()
        gateway.server_close()


def test_report_with_a_failing_or_tampered_record_is_refused(tmp_path, monkeypatch):
    vault, env, gateway = _gated_vault(tmp_path, monkeypatch)
    try:
        failing = _review(
            verdict="fail",
            findings=[{"severity": "block", "rule": "review.defect", "message": "broken path"}],
        )
        path = tmp_path / "failing.json"
        path.write_text(json.dumps(failing))
        result = _run(
            ["report", "alpha", "--run-id", "run-1", "--require-review", "--skill-eval", str(path)],
            vault,
            env,
        )
        assert result.returncode != 0
        assert _reports(vault) == []

        tampered = _review()
        tampered["verdict"] = "warn"
        path.write_text(json.dumps(tampered))
        result = _run(
            ["report", "alpha", "--run-id", "run-1", "--require-review", "--skill-eval", str(path)],
            vault,
            env,
        )
        assert result.returncode != 0
        assert _reports(vault) == []
    finally:
        gateway.shutdown()
        gateway.server_close()


def test_report_can_read_the_review_from_the_run_result(tmp_path, monkeypatch):
    vault, env, gateway = _gated_vault(tmp_path, monkeypatch)
    Gateway.review = _review()
    try:
        result = _run(["report", "alpha", "--run-id", "run-1", "--require-review"], vault, env)
        assert result.returncode == 0, result.stderr
        assert len(_reports(vault)) == 1
    finally:
        Gateway.review = None
        gateway.shutdown()
        gateway.server_close()
