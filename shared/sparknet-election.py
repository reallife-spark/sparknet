#!/usr/bin/env python3
"""Election request types and helpers (scaffold)."""

from dataclasses import dataclass
from typing import Any


@dataclass
class ElectionRequest:
    node_id: str
    operational_pubkey_b64: str
    nonce: str
    ts: str

def make_request(node_id: str, op_pub: str, nonce: str, ts: str) -> dict[str, Any]:
    return {
        "type": "election_request",
        "node_id": node_id,
        "operational_pubkey_b64": op_pub,
        "nonce": nonce,
        "ts": ts,
    }
