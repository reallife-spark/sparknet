"""Shared constants and helpers for the cross-role contract tests.

`tests/contracts/` is split by contract boundary, and the golden-vector section
lives in `tests/test_authz_golden.py`. All three locate the fabric root and read
the contract JSON files the same way; those helpers live here once so a split
cannot let two copies drift apart. The fixtures themselves are in
``tests/conftest.py`` and ``tests/contracts/conftest.py``, which pytest
discovers without an import.

This module is deliberately **not** named `test_*.py`, so pytest does not
collect it as a test module.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = REPO_ROOT / "contracts"
SHARED_PATH = REPO_ROOT / "shared" / "sparknet-authz.py"
PEER = REPO_ROOT / "peer-node"
MASTER = REPO_ROOT / "master-node"

MASTER_HOST = 1
BROADCAST_HOST = 255


def load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text())


def guard_port(ports: dict) -> tuple[int, dict]:
    """The one guard port, shared by the ports, registry and RFI sections."""
    matches = [(int(port), spec) for port, spec in ports["ports"].items() if spec["service"] == "guard"]
    assert len(matches) == 1, f"expected exactly one guard port, found {matches}"
    return matches[0]


def share_policy() -> dict:
    """The capability contract, named for the share rules that read it."""
    return load("capabilities.json")
