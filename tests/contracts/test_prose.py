"""prose"""

from __future__ import annotations

import re

import pytest
from contract_helpers import (
    CONTRACTS,
)

pytestmark = pytest.mark.contract


def test_guard_protocol_states_the_master_side_is_built():
    """The Master side exists (build plan Step 5); a protocol that still calls it
    unbuilt sends a reader looking for something that is already there."""
    text = (CONTRACTS / "guard-protocol.md").read_text()
    assert not re.search(r"does not exist yet|not yet built|unbuilt|not built", text, re.I), (
        "guard-protocol.md must not describe the Master side as unbuilt"
    )
    for name in ("approval-issue", "approval-deliver"):
        assert name in text, f"guard-protocol.md does not name the {name} command"
