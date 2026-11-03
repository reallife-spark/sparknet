"""The signed distillation-run record: canonical bytes and verification."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


authz = _load("distill_authz", ROOT / "shared" / "sparknet-authz.py")


def _run(**over):
    base = {
        "run_id": "run-1",
        "dataset_id": "dataset-1",
        "teacher_model_id": "teacher",
        "teacher_sha256": "a" * 64,
        "student_base_model": "student",
        "student_base_sha256": "b" * 64,
        "hyperparameters": {"epochs": 1},
        "eval_metrics": {"agreement": 0.8},
        "artifact_sha256": "c" * 64,
        "decided_by": "operator",
        "decided_at": "2026-11-01T00:00:00Z",
        "approved": True,
    }
    base.update(over)
    return base


def test_a_run_record_signs_and_verifies():
    private_b64, _public_b64 = authz.generate_keypair()
    private = authz.private_key_from_b64(private_b64)
    signed = authz.sign_distillation_run(_run(), private)
    assert authz.verify_signature(
        private.public_key(),
        signed["signature_b64"],
        authz.distillation_run_message(_run()),
    )


def test_a_changed_field_invalidates_the_signature():
    private_b64, _public_b64 = authz.generate_keypair()
    private = authz.private_key_from_b64(private_b64)
    signed = authz.sign_distillation_run(_run(), private)
    assert not authz.verify_signature(
        private.public_key(),
        signed["signature_b64"],
        authz.distillation_run_message(_run(approved=False)),
    )


def test_a_missing_required_field_is_refused():
    with pytest.raises(authz.AuthzError):
        authz.distillation_run_message(_run(run_id=""))
