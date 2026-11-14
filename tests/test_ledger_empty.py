"""An empty Master ledger is a valid genesis state, not a broken chain."""

from __future__ import annotations

from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit

LEDGER = Path(__file__).resolve().parent.parent / "master-node" / "services" / "sparknet-ledger.py"


@pytest.fixture(scope="module")
def ledger():
    return load_by_path("sparknet_ledger_empty_test", LEDGER)


def test_empty_ledger_is_genesis_valid(ledger) -> None:
    ok, detail = ledger.verify_chain({"genesis_hash": "0" * 64, "blocks": []}, "A" * 44)
    assert ok is True
    assert "empty ledger" in detail
