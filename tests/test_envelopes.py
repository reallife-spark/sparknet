"""The one envelope catalog: pinned bytes, wrappers and signature parity."""

# ruff: noqa: E501 - pinned base64 vectors are intentionally unwrapped

from __future__ import annotations

import base64
import copy
from pathlib import Path

import pytest
from contract_helpers import load
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit


ROOT = Path(__file__).resolve().parent.parent
authz = load_by_path("authz_envelopes_test", ROOT / "shared" / "sparknet-authz.py")


FIXTURES = {
    "admin-request": {
        "action": "list_users",
        "chat_id": None,
        "conversation_id": None,
        "expires_at": 1760000600,
        "issued_at": 1760000000,
        "kb_id": None,
        "master_node_id": "master-1",
        "memory_ids": None,
        "memory_query": None,
        "memory_types": None,
        "nonce": "n1",
        "policy": None,
        "project_id": None,
        "reason": None,
        "request_id": "admin-1",
        "role": None,
        "target_fingerprint": "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7",
        "target_node_id": "peer-fixture-01",
        "user_email": None,
        "user_id": None,
    },
    "authorization": {
        "capabilities": ["telemetry"],
        "department": None,
        "expires_at": 1893456000,
        "fingerprint": "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7",
        "identity": {
            "node_id": "peer-fixture-01",
            "overlay_ipv4": "10.77.0.11/32",
            "requested_capabilities": ["dispatch-bridge", "guard-verify"],
            "role": "peer",
            "wireguard_public_key_b64": "ZmFrZS13Z2lwdW5pY21hcHViaWMta2V5LWZvci10ZXN0cw==",
        },
        "issued_at": 1760000000,
        "node_pubkey_b64": None,
        "overlay_ipv4": "10.77.0.11",
        "revoked": False,
        "signature_b64": "z",
    },
    "cluster-job": {
        "budget": None,
        "context": None,
        "conversation_id": "conv-1",
        "created_at": "2026-11-09T12:00:00Z",
        "expires_at": "2026-11-09T12:05:00Z",
        "initiator_node_id": "peer-fixture-01",
        "job_id": "job-1",
        "mode": "decompose",
        "prompt": "do the thing",
        "running_summary": None,
        "subtasks": [{"id": "s1"}],
    },
    "distillation-run": {
        "approved": True,
        "artifact_sha256": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        "dataset_id": "ds-1",
        "decided_at": "2026-11-09T12:00:00Z",
        "decided_by": "master",
        "eval_metrics": {"score": 0.9},
        "hyperparameters": {"lr": 0.1},
        "run_id": "run-1",
        "student_base_model": "student",
        "student_base_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "teacher_model_id": "teacher",
        "teacher_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    },
    "grant": {
        "capabilities": ["telemetry"],
        "conversation_key": "c1",
        "expires_at": "2026-11-09T12:05:00Z",
        "grant_id": "g1",
        "issued_at": "2026-11-09T12:00:00Z",
        "node_fingerprint": "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7",
        "node_id": "peer-fixture-01",
        "nonce": "n1",
        "operator_os": None,
        "overlay_ipv4": "10.77.0.11",
        "parent_grant_id": None,
        "user_identity": "u1",
        "vault_scope": ["concepts"],
    },
    "guard-approval": {
        "content_b64": "aGVsbG8=",
        "content_sha256": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
        "expires_at": "2026-11-09T12:05:00Z",
        "file_path": "/etc/wireguard/wg0.conf",
        "issued_at": "2026-11-09T12:00:00Z",
        "nonce": "n1",
        "operator_os": "",
        "peer_fingerprint": "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7",
        "request_id": "r1",
    },
    "identity": {
        "node_id": "peer-fixture-01",
        "overlay_ipv4": "10.77.0.11/32",
        "requested_capabilities": ["dispatch-bridge", "guard-verify"],
        "role": "peer",
        "wireguard_public_key_b64": "ZmFrZS13Z2lwdW5pY21hcHViaWMta2V5LWZvci10ZXN0cw==",
    },
    "ledger-block": {
        "block_id": "b1",
        "data": {"x": 1},
        "hash": "h",
        "node_pubkey_b64": "k",
        "prev_hash": "",
        "signature": "s",
        "timestamp": "2026-11-09T12:00:00Z",
    },
    "registry-publication": {
        "published_at": "2026-11-09T12:00:00Z",
        "registry": {
            "authorizations": [
                {
                    "capabilities": ["telemetry"],
                    "department": None,
                    "expires_at": 1893456000,
                    "fingerprint": "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7",
                    "identity": {
                        "node_id": "peer-fixture-01",
                        "overlay_ipv4": "10.77.0.11/32",
                        "requested_capabilities": ["dispatch-bridge", "guard-verify"],
                        "role": "peer",
                        "wireguard_public_key_b64": "ZmFrZS13Z2lwdW5pY21hcHViaWMta2V5LWZvci10ZXN0cw==",
                    },
                    "issued_at": 1760000000,
                    "node_pubkey_b64": None,
                    "overlay_ipv4": "10.77.0.11",
                    "revoked": False,
                    "signature_b64": "z",
                }
            ],
            "master_public_key_b64": "x",
            "sequence": 1,
        },
        "registry_sha256": "d9604b5fbbc86307cc9eecdb4064361fa2045a767b74e81796f7c773cc0d4060",
        "sequence": 1,
    },
    "rfi-answer": {
        "answered_at": "2026-11-09T12:00:00Z",
        "content_b64": "YW5zd2Vy",
        "content_sha256": "0db52f4076c082518412afd3dd3576e2cb0c63703fd7fed5e23ade60efef31d9",
        "item_name": "answer.md",
        "peer_fingerprint": "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7",
        "request_id": "req-1",
    },
    "share-ratification": {
        "accepted_at": "2026-11-09T12:00:00Z",
        "deadline": "2026-11-09T13:00:00Z",
        "decision": "ratified",
        "flag_retained": True,
        "grant_id": "g1",
        "node_fingerprint": "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7",
        "node_id": "peer-fixture-01",
        "ratified_at": "2026-11-09T12:01:00Z",
        "reason": "ok",
        "schema_version": "1.0",
        "share_id": "s1",
    },
    "trust-transition": {
        "decided_at": "2026-11-09T12:00:00Z",
        "flag_preserved": True,
        "level": "flagged",
        "node_id": "peer-fixture-01",
        "previous_level": "authenticated",
        "reason": "evidence",
        "reversible": True,
        "schema_version": "1.0",
    },
    "rfi-request": {
        "request_id": "req-1",
        "peer_fingerprint": "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7",
        "question": "why?",
        "scope": ["concepts"],
        "issued_at": "2026-11-09T12:00:00Z",
        "expires_at": "2026-11-09T12:05:00Z",
        "nonce": "n1",
    },
    "sandbox-request": {
        "action": "get",
        "conversation_id": None,
        "expires_at": 1760000600,
        "image": None,
        "issued_at": 1760000000,
        "master_node_id": "master-1",
        "mounts": None,
        "nonce": "n1",
        "policy": None,
        "port": None,
        "reason": None,
        "request_id": "sandbox-1",
        "sandbox_name": "peer-fixture-01-chat",
        "service_name": None,
        "target_fingerprint": "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7",
        "target_node_id": "peer-fixture-01",
    },
    "telemetry-report": {
        "kind": "status",
        "peer_fingerprint": "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7",
        "payload": {"node_id": "x"},
        "issued_at": "2026-11-09T12:00:00Z",
        "expires_at": "2026-11-09T12:02:00Z",
        "nonce": "n1",
    },
    "issue-report": {
        "schema": "sparknet-issue/1",
        "issue_id": "issue-1",
        "node_id": "peer-fixture-01",
        "peer_fingerprint": "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7",
        "title": "t",
        "body": "b",
        "status": "open",
        "labels": [],
        "links": [],
        "source": "",
        "content_sha256": "3e23e8160039594a33894f6564e1b1348bbd7a0088d42c4acb73eeaed59c009d",
        "nonce": "n1",
        "issued_at": "2026-11-09T12:00:00Z",
        "expires_at": "2026-11-09T12:05:00Z",
        "updated_at": "2026-11-09T12:00:00Z",
    },
}

EXPECTED = {
    "admin-request": "eyJhY3Rpb24iOiJsaXN0X3VzZXJzIiwiY2hhdF9pZCI6bnVsbCwiY29udmVyc2F0aW9uX2lkIjpudWxsLCJleHBpcmVzX2F0IjoxNzYwMDAwNjAwLCJpc3N1ZWRfYXQiOjE3NjAwMDAwMDAsImtiX2lkIjpudWxsLCJtYXN0ZXJfbm9kZV9pZCI6Im1hc3Rlci0xIiwibWVtb3J5X2lkcyI6bnVsbCwibWVtb3J5X3F1ZXJ5IjpudWxsLCJtZW1vcnlfdHlwZXMiOm51bGwsIm5vbmNlIjoibjEiLCJwb2xpY3kiOm51bGwsInByb2plY3RfaWQiOm51bGwsInJlYXNvbiI6bnVsbCwicmVxdWVzdF9pZCI6ImFkbWluLTEiLCJyb2xlIjpudWxsLCJ0YXJnZXRfZmluZ2VycHJpbnQiOiIxNDBlMGRjNTU0ZTE4Yjg4MzkyMmJkNTE2NGY1NzZlZWUwYzFkNmQwOGViZjVmN2QzYzA1Mjk0ODI1N2MzNmM3IiwidGFyZ2V0X25vZGVfaWQiOiJwZWVyLWZpeHR1cmUtMDEiLCJ1c2VyX2VtYWlsIjpudWxsLCJ1c2VyX2lkIjpudWxsfQ==",
    "authorization": "eyJjYXBhYmlsaXRpZXMiOlsidGVsZW1ldHJ5Il0sImRlcGFydG1lbnQiOm51bGwsImV4cGlyZXNfYXQiOjE4OTM0NTYwMDAsImZpbmdlcnByaW50IjoiMTQwZTBkYzU1NGUxOGI4ODM5MjJiZDUxNjRmNTc2ZWVlMGMxZDZkMDhlYmY1ZjdkM2MwNTI5NDgyNTdjMzZjNyIsImlkZW50aXR5Ijp7Im5vZGVfaWQiOiJwZWVyLWZpeHR1cmUtMDEiLCJvdmVybGF5X2lwdjQiOiIxMC43Ny4wLjExLzMyIiwicmVxdWVzdGVkX2NhcGFiaWxpdGllcyI6WyJkaXNwYXRjaC1icmlkZ2UiLCJndWFyZC12ZXJpZnkiXSwicm9sZSI6InBlZXIiLCJ3aXJlZ3VhcmRfcHVibGljX2tleV9iNjQiOiJabUZyWlMxM1oybHdkVzVwWTIxaGNIVmlhV010YTJWNUxXWnZjaTEwWlhOMGN3PT0ifSwiaXNzdWVkX2F0IjoxNzYwMDAwMDAwLCJub2RlX3B1YmtleV9iNjQiOm51bGwsIm92ZXJsYXlfaXB2NCI6IjEwLjc3LjAuMTEiLCJyZXZva2VkIjpmYWxzZX0=",
    "cluster-job": "eyJidWRnZXQiOm51bGwsImNvbnRleHQiOm51bGwsImNvbnZlcnNhdGlvbl9pZCI6ImNvbnYtMSIsImNyZWF0ZWRfYXQiOiIyMDI2LTExLTA5VDEyOjAwOjAwWiIsImV4cGlyZXNfYXQiOiIyMDI2LTExLTA5VDEyOjA1OjAwWiIsImluaXRpYXRvcl9ub2RlX2lkIjoicGVlci1maXh0dXJlLTAxIiwiam9iX2lkIjoiam9iLTEiLCJtb2RlIjoiZGVjb21wb3NlIiwicHJvbXB0IjoiZG8gdGhlIHRoaW5nIiwicnVubmluZ19zdW1tYXJ5IjpudWxsLCJzdWJ0YXNrcyI6W3siaWQiOiJzMSJ9XX0=",
    "distillation-run": "c3BhcmtuZXQtZGlzdGlsbGF0aW9uLXJ1bi8xCnsiYXBwcm92ZWQiOnRydWUsImFydGlmYWN0X3NoYTI1NiI6ImNjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2MiLCJkYXRhc2V0X2lkIjoiZHMtMSIsImRlY2lkZWRfYXQiOiIyMDI2LTExLTA5VDEyOjAwOjAwWiIsImRlY2lkZWRfYnkiOiJtYXN0ZXIiLCJldmFsX21ldHJpY3MiOnsic2NvcmUiOjAuOX0sImh5cGVycGFyYW1ldGVycyI6eyJsciI6MC4xfSwicnVuX2lkIjoicnVuLTEiLCJzdHVkZW50X2Jhc2VfbW9kZWwiOiJzdHVkZW50Iiwic3R1ZGVudF9iYXNlX3NoYTI1NiI6ImJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmIiLCJ0ZWFjaGVyX21vZGVsX2lkIjoidGVhY2hlciIsInRlYWNoZXJfc2hhMjU2IjoiYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYSJ9",
    "grant": "eyJjYXBhYmlsaXRpZXMiOlsidGVsZW1ldHJ5Il0sImNvbnZlcnNhdGlvbl9rZXkiOiJjMSIsImV4cGlyZXNfYXQiOiIyMDI2LTExLTA5VDEyOjA1OjAwWiIsImdyYW50X2lkIjoiZzEiLCJpc3N1ZWRfYXQiOiIyMDI2LTExLTA5VDEyOjAwOjAwWiIsIm5vZGVfZmluZ2VycHJpbnQiOiIxNDBlMGRjNTU0ZTE4Yjg4MzkyMmJkNTE2NGY1NzZlZWUwYzFkNmQwOGViZjVmN2QzYzA1Mjk0ODI1N2MzNmM3Iiwibm9kZV9pZCI6InBlZXItZml4dHVyZS0wMSIsIm5vbmNlIjoibjEiLCJvcGVyYXRvcl9vcyI6bnVsbCwib3ZlcmxheV9pcHY0IjoiMTAuNzcuMC4xMSIsInBhcmVudF9ncmFudF9pZCI6bnVsbCwidXNlcl9pZGVudGl0eSI6InUxIiwidmF1bHRfc2NvcGUiOlsiY29uY2VwdHMiXX0=",
    "guard-approval": "eyJjb250ZW50X2I2NCI6ImFHVnNiRzg9IiwiY29udGVudF9zaGEyNTYiOiIyY2YyNGRiYTVmYjBhMzBlMjZlODNiMmFjNWI5ZTI5ZTFiMTYxZTVjMWZhNzQyNWU3MzA0MzM2MjkzOGI5ODI0IiwiZXhwaXJlc19hdCI6IjIwMjYtMTEtMDlUMTI6MDU6MDBaIiwiZmlsZV9wYXRoIjoiL2V0Yy93aXJlZ3VhcmQvd2cwLmNvbmYiLCJpc3N1ZWRfYXQiOiIyMDI2LTExLTA5VDEyOjAwOjAwWiIsIm5vbmNlIjoibjEiLCJvcGVyYXRvcl9vcyI6IiIsInBlZXJfZmluZ2VycHJpbnQiOiIxNDBlMGRjNTU0ZTE4Yjg4MzkyMmJkNTE2NGY1NzZlZWUwYzFkNmQwOGViZjVmN2QzYzA1Mjk0ODI1N2MzNmM3IiwicmVxdWVzdF9pZCI6InIxIn0=",
    "identity": "eyJub2RlX2lkIjoicGVlci1maXh0dXJlLTAxIiwib3ZlcmxheV9pcHY0IjoiMTAuNzcuMC4xMS8zMiIsInJlcXVlc3RlZF9jYXBhYmlsaXRpZXMiOlsiZGlzcGF0Y2gtYnJpZGdlIiwiZ3VhcmQtdmVyaWZ5Il0sInJvbGUiOiJwZWVyIiwid2lyZWd1YXJkX3B1YmxpY19rZXlfYjY0IjoiWm1GclpTMTNaMmx3ZFc1cFkyMWhjSFZpYVdNdGEyVjVMV1p2Y2kxMFpYTjBjdz09In0=",
    "issue-report": "eyJib2R5IjoiYiIsImNvbnRlbnRfc2hhMjU2IjoiM2UyM2U4MTYwMDM5NTk0YTMzODk0ZjY1NjRlMWIxMzQ4YmJkN2EwMDg4ZDQyYzRhY2I3M2VlYWVkNTljMDA5ZCIsImV4cGlyZXNfYXQiOiIyMDI2LTExLTA5VDEyOjA1OjAwWiIsImlzc3VlX2lkIjoiaXNzdWUtMSIsImlzc3VlZF9hdCI6IjIwMjYtMTEtMDlUMTI6MDA6MDBaIiwibGFiZWxzIjpbXSwibGlua3MiOltdLCJub2RlX2lkIjoicGVlci1maXh0dXJlLTAxIiwibm9uY2UiOiJuMSIsInBlZXJfZmluZ2VycHJpbnQiOiIxNDBlMGRjNTU0ZTE4Yjg4MzkyMmJkNTE2NGY1NzZlZWUwYzFkNmQwOGViZjVmN2QzYzA1Mjk0ODI1N2MzNmM3Iiwic2NoZW1hIjoic3BhcmtuZXQtaXNzdWUvMSIsInNvdXJjZSI6IiIsInN0YXR1cyI6Im9wZW4iLCJ0aXRsZSI6InQiLCJ1cGRhdGVkX2F0IjoiMjAyNi0xMS0wOVQxMjowMDowMFoifQ==",
    "ledger-block": "eyJibG9ja19pZCI6ImIxIiwiZGF0YSI6eyJ4IjoxfSwibm9kZV9wdWJrZXlfYjY0IjoiayIsInByZXZfaGFzaCI6IiIsInRpbWVzdGFtcCI6IjIwMjYtMTEtMDlUMTI6MDA6MDBaIn0=",
    "registry-publication": "eyJwdWJsaXNoZWRfYXQiOiIyMDI2LTExLTA5VDEyOjAwOjAwWiIsInJlZ2lzdHJ5X3NoYTI1NiI6ImQ5NjA0YjVmYmJjODYzMDdjYzllZWNkYjQwNjQzNjFmYTIwNDVhNzY3Yjc0ZTgxNzk2ZjdjNzczY2MwZDQwNjAiLCJzZXF1ZW5jZSI6MX0=",
    "rfi-answer": "eyJhbnN3ZXJlZF9hdCI6IjIwMjYtMTEtMDlUMTI6MDA6MDBaIiwiY29udGVudF9zaGEyNTYiOiIwZGI1MmY0MDc2YzA4MjUxODQxMmFmZDNkZDM1NzZlMmNiMGM2MzcwM2ZkN2ZlZDVlMjNhZGU2MGVmZWYzMWQ5IiwiaXRlbV9uYW1lIjoiYW5zd2VyLm1kIiwicGVlcl9maW5nZXJwcmludCI6IjE0MGUwZGM1NTRlMThiODgzOTIyYmQ1MTY0ZjU3NmVlZTBjMWQ2ZDA4ZWJmNWY3ZDNjMDUyOTQ4MjU3YzM2YzciLCJyZXF1ZXN0X2lkIjoicmVxLTEifQ==",
    "rfi-request": "eyJleHBpcmVzX2F0IjoiMjAyNi0xMS0wOVQxMjowNTowMFoiLCJpc3N1ZWRfYXQiOiIyMDI2LTExLTA5VDEyOjAwOjAwWiIsIm5vbmNlIjoibjEiLCJwZWVyX2ZpbmdlcnByaW50IjoiMTQwZTBkYzU1NGUxOGI4ODM5MjJiZDUxNjRmNTc2ZWVlMGMxZDZkMDhlYmY1ZjdkM2MwNTI5NDgyNTdjMzZjNyIsInF1ZXN0aW9uIjoid2h5PyIsInJlcXVlc3RfaWQiOiJyZXEtMSIsInNjb3BlIjpbImNvbmNlcHRzIl19",
    "sandbox-request": "eyJhY3Rpb24iOiJnZXQiLCJjb252ZXJzYXRpb25faWQiOm51bGwsImV4cGlyZXNfYXQiOjE3NjAwMDA2MDAsImltYWdlIjpudWxsLCJpc3N1ZWRfYXQiOjE3NjAwMDAwMDAsIm1hc3Rlcl9ub2RlX2lkIjoibWFzdGVyLTEiLCJtb3VudHMiOm51bGwsIm5vbmNlIjoibjEiLCJwb2xpY3kiOm51bGwsInBvcnQiOm51bGwsInJlYXNvbiI6bnVsbCwicmVxdWVzdF9pZCI6InNhbmRib3gtMSIsInNhbmRib3hfbmFtZSI6InBlZXItZml4dHVyZS0wMS1jaGF0Iiwic2VydmljZV9uYW1lIjpudWxsLCJ0YXJnZXRfZmluZ2VycHJpbnQiOiIxNDBlMGRjNTU0ZTE4Yjg4MzkyMmJkNTE2NGY1NzZlZWUwYzFkNmQwOGViZjVmN2QzYzA1Mjk0ODI1N2MzNmM3IiwidGFyZ2V0X25vZGVfaWQiOiJwZWVyLWZpeHR1cmUtMDEifQ==",
    "share-ratification": "eyJhY2NlcHRlZF9hdCI6IjIwMjYtMTEtMDlUMTI6MDA6MDBaIiwiZGVhZGxpbmUiOiIyMDI2LTExLTA5VDEzOjAwOjAwWiIsImRlY2lzaW9uIjoicmF0aWZpZWQiLCJmbGFnX3JldGFpbmVkIjp0cnVlLCJncmFudF9pZCI6ImcxIiwibm9kZV9maW5nZXJwcmludCI6IjE0MGUwZGM1NTRlMThiODgzOTIyYmQ1MTY0ZjU3NmVlZTBjMWQ2ZDA4ZWJmNWY3ZDNjMDUyOTQ4MjU3YzM2YzciLCJub2RlX2lkIjoicGVlci1maXh0dXJlLTAxIiwicmF0aWZpZWRfYXQiOiIyMDI2LTExLTA5VDEyOjAxOjAwWiIsInJlYXNvbiI6Im9rIiwic2NoZW1hX3ZlcnNpb24iOiIxLjAiLCJzaGFyZV9pZCI6InMxIn0=",
    "telemetry-report": "eyJleHBpcmVzX2F0IjoiMjAyNi0xMS0wOVQxMjowMjowMFoiLCJpc3N1ZWRfYXQiOiIyMDI2LTExLTA5VDEyOjAwOjAwWiIsImtpbmQiOiJzdGF0dXMiLCJub25jZSI6Im4xIiwicGF5bG9hZCI6eyJub2RlX2lkIjoieCJ9LCJwZWVyX2ZpbmdlcnByaW50IjoiMTQwZTBkYzU1NGUxOGI4ODM5MjJiZDUxNjRmNTc2ZWVlMGMxZDZkMDhlYmY1ZjdkM2MwNTI5NDgyNTdjMzZjNyJ9",
    "trust-transition": "eyJkZWNpZGVkX2F0IjoiMjAyNi0xMS0wOVQxMjowMDowMFoiLCJmbGFnX3ByZXNlcnZlZCI6dHJ1ZSwibGV2ZWwiOiJmbGFnZ2VkIiwibm9kZV9pZCI6InBlZXItZml4dHVyZS0wMSIsInByZXZpb3VzX2xldmVsIjoiYXV0aGVudGljYXRlZCIsInJlYXNvbiI6ImV2aWRlbmNlIiwicmV2ZXJzaWJsZSI6dHJ1ZSwic2NoZW1hX3ZlcnNpb24iOiIxLjAifQ==",
}


WRAPPERS = {
    "identity": authz.canonical_bytes,
    "authorization": authz.authorization_message,
    "registry-publication": authz.registry_publication_message,
    "guard-approval": authz.guard_approval_message,
    "cluster-job": authz.cluster_job_message,
    "admin-request": authz.admin_request_message,
    "sandbox-request": authz.sandbox_request_message,
    "distillation-run": authz.distillation_run_message,
    "grant": authz.grant_message,
    "share-ratification": authz.share_ratification_message,
    "trust-transition": authz.trust_transition_message,
    "rfi-answer": authz.rfi_answer_message,
    "ledger-block": authz.ledger_block_signable,
}

SIGNED = {
    "authorization",
    "registry-publication",
    "guard-approval",
    "cluster-job",
    "admin-request",
    "sandbox-request",
    "distillation-run",
    "grant",
    "share-ratification",
    "trust-transition",
    "rfi-answer",
    "ledger-block",
}

VALIDATION_ONLY = {"identity", "rfi-request", "telemetry-report", "issue-report"}


def test_catalog_covers_every_pinned_kind() -> None:
    assert set(authz.ENVELOPE_KINDS) == set(EXPECTED)


def test_every_message_matches_the_pinned_bytes() -> None:
    for kind, fixture in FIXTURES.items():
        actual = authz.envelope_message(kind, copy.deepcopy(fixture))
        assert base64.b64encode(actual).decode() == EXPECTED[kind], kind


def test_named_wrappers_match_the_catalog() -> None:
    for kind, wrapper in WRAPPERS.items():
        actual = wrapper(copy.deepcopy(FIXTURES[kind]))
        expected = authz.envelope_message(kind, copy.deepcopy(FIXTURES[kind]))
        assert actual == expected, kind


def test_signed_kinds_round_trip_and_refuse_a_tamper() -> None:
    private_b64, _public = authz.generate_keypair()
    key = authz.private_key_from_b64(private_b64)
    for kind in SIGNED:
        signed = authz.sign_envelope(kind, copy.deepcopy(FIXTURES[kind]), key)
        assert authz.verify_envelope(kind, signed, key.public_key()) is True, kind
        tampered = copy.deepcopy(signed)
        if kind == "ledger-block":
            tampered["data"] = {"tampered": True}
        else:
            tampered[authz.SPECS[kind].signed_fields[0]] = "tampered"
        assert authz.verify_envelope(kind, tampered, key.public_key()) is False, kind


def test_validation_only_kinds_are_not_signed() -> None:
    private_b64, _public = authz.generate_keypair()
    key = authz.private_key_from_b64(private_b64)
    for kind in VALIDATION_ONLY:
        with pytest.raises(authz.AuthzError):
            authz.sign_envelope(kind, copy.deepcopy(FIXTURES[kind]), key)
        assert authz.verify_envelope(kind, copy.deepcopy(FIXTURES[kind]), key.public_key()) is False


def test_unknown_kind_is_refused() -> None:
    with pytest.raises(authz.AuthzError, match="unknown envelope kind"):
        authz.envelope_message("not-a-kind", {})


def test_identity_spec_matches_the_contract() -> None:
    schema = load("identity-schema.json")
    assert tuple(authz.SPECS["identity"].fields) == tuple(schema["identity_fields"])
