"""The channel map is present, navigable and agrees with the port contract."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract


REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT = REPO_ROOT / "contracts" / "knowledge-flow.md"


def test_the_map_names_every_channel_and_the_separation_rule() -> None:
    text = CONTRACT.read_text(encoding="utf-8")
    for phrase in (
        "Registry publication",
        "Guard approval",
        "RFI answer",
        "RFI request",
        "Telemetry",
        "Admin request",
        "Share / proposal",
        "Shared file share",
        "Shared vector DB",
        "Local vault / KB",
        "Context pack",
    ):
        assert phrase in text, f"knowledge-flow.md does not name {phrase}"
    assert re.search(r"authority and knowledge", text, re.I)
    assert "must never carry" in text


def test_the_map_is_named_by_the_navigation_and_both_roles() -> None:
    for rel in ("contracts/README.md", "index.md", "llms.txt", "AGENTS.md", "INTENT.md"):
        assert "knowledge-flow.md" in (REPO_ROOT / rel).read_text(encoding="utf-8"), rel
    for rel in ("peer-node/MISSION.md", "peer-node/INTENT.md", "peer-node/AGENTS.md"):
        assert "knowledge-flow.md" in (REPO_ROOT / rel).read_text(encoding="utf-8"), rel
    for rel in ("master-node/MISSION.md", "master-node/INTENT.md", "master-node/AGENTS.md"):
        assert "knowledge-flow.md" in (REPO_ROOT / rel).read_text(encoding="utf-8"), rel


def test_the_map_agrees_with_the_port_states() -> None:
    ports = json.loads((REPO_ROOT / "contracts" / "ports.json").read_text(encoding="utf-8"))["ports"]
    text = CONTRACT.read_text(encoding="utf-8")
    assert ports["8090"]["implementation_state"] == "implemented"
    assert ports["9090"]["implementation_state"] == "implemented"
    assert ports["4221"]["implementation_state"] == "implemented"
    assert ports["4223"]["implementation_state"] == "implemented"
    for port in ("8090", "9090", "4221", "4223"):
        assert port in text, f"knowledge-flow.md does not name port {port}"
