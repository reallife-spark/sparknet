"""The Master's sanitized distillation snapshot.

The console must not read `/srv/sparknet/distill` directly: it is root-only and
contains datasets/traces. This test proves the snapshot contains only run
metadata and digests, and is written for the operator to read.
"""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT = ROOT / "master-node" / "services" / "sparknet-distill-status.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("sparknet_distill_status_test", SNAPSHOT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


status = _load()


def test_snapshot_exposes_metadata_not_dataset_content(tmp_path: Path) -> None:
    config = tmp_path / "distill.json"
    config.write_text(json.dumps({"teacher_model_id": "teacher", "student_base_model": "student"}))
    run = tmp_path / "distill" / "runs" / "run-1"
    run.mkdir(parents=True)
    (run / "plan.json").write_text(json.dumps({"state": "planned"}))
    (run / "run.json").write_text(
        json.dumps({"approved": True, "artifact_sha256": "abc", "signature_b64": "sig", "prompt": "SECRET"})
    )
    (run / "eval.json").write_text(json.dumps({"metrics": {"agreement": 0.5}}))
    (run / "model-card.json").write_text(json.dumps({"model_id": "distilled-run-1"}))

    snapshot = status.snapshot(config, tmp_path / "distill")
    assert snapshot["runs"][0]["run_id"] == "run-1"
    assert snapshot["runs"][0]["eval"] == {"agreement": 0.5}
    assert snapshot["runs"][0]["signed"] is True
    assert "SECRET" not in json.dumps(snapshot)

    out = tmp_path / "state" / "distill-status.json"
    status.write(out, snapshot)
    assert out.is_file()
    assert stat.S_IMODE(out.stat().st_mode) == 0o644
    assert json.loads(out.read_text())["read_only"] is True
