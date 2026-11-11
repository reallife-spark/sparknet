"""The data lake stores consented metadata, never an answer corpus."""

from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit


ROOT = Path(__file__).resolve().parent.parent


def _load(name, filename):
    return load_by_path(name, ROOT / "shared" / filename)


lake = _load("data_lake_test", "sparknet-data-lake.py")


def _record():
    return {
        "schema_version": "sparknet-data-lake/1",
        "record_id": "dl-1",
        "node_id": "sparknet-node-0002",
        "user_id": "U-1",
        "consent": True,
        "kind": "teacher-trace",
        "classification": "confidential",
        "department": "blue",
        "digest": "a" * 64,
        "size": 10,
        "retention_days": 30,
        "created_at": "2099-01-01T00:00:00Z",
    }


def test_data_lake_record_signature_and_consent():
    key = Ed25519PrivateKey.generate()
    signed = lake.sign_record(_record(), key)
    assert lake.verify_record(signed, key.public_key()) is True
    unsigned = dict(signed)
    unsigned["consent"] = False
    try:
        lake.validate_record(unsigned)
    except lake.DataLakeError as exc:
        assert exc.code == "consent-missing"
    else:
        raise AssertionError("consent=false accepted")


def test_data_lake_refuses_unknown_kind_and_retention():
    for field, value, code in (
        ("kind", "answer-corpus", "unknown-kind"),
        ("retention_days", 3651, "retention-too-long"),
    ):
        record = _record()
        record[field] = value
        try:
            lake.validate_record(record)
        except lake.DataLakeError as exc:
            assert exc.code == code
        else:
            raise AssertionError(f"{field} accepted")
