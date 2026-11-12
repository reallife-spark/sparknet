"""The signed peer→Master eval-audit report envelope."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
from sparknet_loader import load_by_path  # noqa: E402 - the shared path shim

REPORT = load_by_path("sparknet_eval_report", ROOT / "shared" / "sparknet-eval-report.py")

pytestmark = pytest.mark.unit


def _record() -> dict:
    return {
        "schema": "sparknet-skill-eval/1",
        "eval_id": "eval-1",
        "verdict": "pass",
        "findings": [],
        "skill": {"name": "code-review", "origin": "mattpocock", "digest": "a" * 64},
        "subject": {"kind": "skill", "ref": "tests/fixture.json", "digest": "b" * 64},
        "evaluator": {"kind": "harness", "id": "test", "model": ""},
        "created_at": "2026-11-12T00:00:00Z",
        "body_sha256": "c" * 64,
    }


def test_roundtrip_and_stable_report_id() -> None:
    moment = datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc)
    one = REPORT.build_report(node_id="node-a", peer_fingerprint="f" * 64, records=[_record()], now=moment)
    two = REPORT.build_report(node_id="node-a", peer_fingerprint="f" * 64, records=[_record()], now=moment)
    assert one["report_id"] == two["report_id"]
    assert REPORT.validate_report(one, expected_fingerprint="f" * 64, now=moment) == (True, "")


def test_tampered_record_fails_the_digest() -> None:
    moment = datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc)
    report = REPORT.build_report(node_id="node-a", peer_fingerprint="f" * 64, records=[_record()], now=moment)
    report["records"][0]["verdict"] = "fail"
    assert REPORT.validate_report(report, expected_fingerprint="f" * 64, now=moment) == (False, "digest_mismatch")


def test_wrong_peer_and_replay_are_refused() -> None:
    moment = datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc)
    report = REPORT.build_report(node_id="node-a", peer_fingerprint="f" * 64, records=[_record()], now=moment)
    assert REPORT.validate_report(report, expected_fingerprint="e" * 64, now=moment)[0] is False
    assert REPORT.validate_report(report, expected_fingerprint="f" * 64, now=moment, seen_nonces={report["nonce"]}) == (
        False,
        "replayed",
    )


def test_expired_report_is_stale() -> None:
    moment = datetime(2026, 11, 12, 0, 0, tzinfo=timezone.utc)
    report = REPORT.build_report(node_id="node-a", peer_fingerprint="f" * 64, records=[_record()], now=moment)
    later = moment + timedelta(seconds=301)
    assert REPORT.validate_report(report, expected_fingerprint="f" * 64, now=later) == (False, "stale")


def test_empty_and_oversized_record_lists_are_refused() -> None:
    with pytest.raises(ValueError):
        REPORT.build_report(node_id="node-a", peer_fingerprint="f" * 64, records=[])
    with pytest.raises(ValueError):
        REPORT.build_report(node_id="node-a", peer_fingerprint="f" * 64, records=[_record()] * 101)
