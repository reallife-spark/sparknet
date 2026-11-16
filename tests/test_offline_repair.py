"""Offline-repair records: node-signed evidence, never authority."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
peer_cli = load_by_path(
    "sparknet_offline_repair_peer_test", ROOT / "peer-node" / "services" / "sparknet-offline-repair.py"
)
master_cli = load_by_path(
    "sparknet_offline_repair_master_test", ROOT / "master-node" / "services" / "sparknet-offline-repair.py"
)
authz = load_by_path("authz_offline_repair_test", ROOT / "shared" / "sparknet-authz.py")
sso = load_by_path("sso_offline_repair_test", ROOT / "shared" / "sparknet-sso.py")

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
FINGERPRINT = "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7"


def _keypair(tmp_path: Path) -> tuple[Path, str]:
    private_b64, public_b64 = authz.generate_keypair()
    key = tmp_path / "keys" / "ed25519-node.key.b64"
    key.parent.mkdir(parents=True)
    key.write_text(private_b64 + "\n", encoding="utf-8")
    key.chmod(0o600)
    return key, public_b64


def _registry(tmp_path: Path, public_b64: str) -> Path:
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "authorizations": [
                    {
                        "identity": {"node_id": "sparknet-node-0002", "role": "peer"},
                        "fingerprint": FINGERPRINT,
                        "node_pubkey_b64": public_b64,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return path


def test_record_and_review_are_signed_evidence_only(tmp_path: Path) -> None:
    key, public_b64 = _keypair(tmp_path)
    state = tmp_path / "state"
    signed = peer_cli.record(
        state=state,
        key_path=key,
        node_id="sparknet-node-0002",
        node_fingerprint=FINGERPRINT,
        action="user-role",
        target={"user": "user@example.test"},
        change={"role": "user"},
        now=NOW,
    )
    spool = peer_cli.spool_path(state)
    assert spool.is_file() and spool.stat().st_mode & 0o777 == 0o600
    assert peer_cli.load_spool(state) == [signed]

    review_out = tmp_path / "review.jsonl"
    reviewed = master_cli.review(
        registry=_registry(tmp_path, public_b64),
        spool=spool,
        node_id="sparknet-node-0002",
        node_pubkey_b64=None,
        output=review_out,
        now=NOW,
    )
    assert reviewed[0]["ok"] is True
    assert reviewed[0]["applied"] is False
    assert review_out.read_text(encoding="utf-8").strip()
    assert review_out.stat().st_mode & 0o777 == 0o600


def test_a_tampered_record_is_refused(tmp_path: Path) -> None:
    key, public_b64 = _keypair(tmp_path)
    state = tmp_path / "state"
    signed = peer_cli.record(
        state=state,
        key_path=key,
        node_id="sparknet-node-0002",
        node_fingerprint=FINGERPRINT,
        action="setting-change",
        target={"setting": "theme"},
        change={"value": "dark"},
        now=NOW,
    )
    tampered = {**signed, "change": {"value": "attacker"}}
    peer_cli.spool_path(state).write_text(json.dumps(tampered) + "\n", encoding="utf-8")
    reviewed = master_cli.review(
        registry=_registry(tmp_path, public_b64),
        spool=peer_cli.spool_path(state),
        node_id="sparknet-node-0002",
        node_pubkey_b64=None,
        output=tmp_path / "review.jsonl",
        now=NOW,
    )
    assert reviewed[0]["ok"] is False
    assert reviewed[0]["reason"] == sso.REASON_REPAIR_BAD_SIGNATURE


def test_a_record_cannot_carry_authority(tmp_path: Path) -> None:
    key, _public = _keypair(tmp_path)
    with pytest.raises(Exception, match="authority field"):
        peer_cli.record(
            state=tmp_path / "state",
            key_path=key,
            node_id="sparknet-node-0002",
            node_fingerprint=FINGERPRINT,
            action="local-repair",
            target={"user": "user@example.test"},
            change={"capabilities": ["guard-apply"]},
            now=NOW,
        )


def test_review_requires_a_registry_attested_key(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "authorizations": [
                    {
                        "identity": {"node_id": "sparknet-node-0002", "role": "peer"},
                        "fingerprint": FINGERPRINT,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no node_pubkey_b64"):
        master_cli.review(
            registry=registry,
            spool=tmp_path / "spool.jsonl",
            node_id="sparknet-node-0002",
            node_pubkey_b64=None,
            output=tmp_path / "review.jsonl",
            now=NOW,
        )
