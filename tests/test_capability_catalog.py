"""The Go capability catalog is a projection of ``contracts/capabilities.json``.

The contract is the closed vocabulary; goSpark is one consumer. A hand-written
Go snapshot that drifts from the contract fails closed at the wrong layer: a
Master-signed entry is valid in Python and unknown in Go. This test compares the
three facts that decide authority: known capabilities, sensitive capabilities
and the Master-implied names.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GO_CAPABILITIES = REPO_ROOT / "gospark" / "internal" / "authz" / "capabilities.go"


def _go_source() -> str:
    return GO_CAPABILITIES.read_text(encoding="utf-8")


def _go_constants(source: str) -> dict[str, str]:
    return dict(re.findall(r'^\s*(Cap[A-Za-z0-9]+)\s+Capability\s*=\s*"([^"]+)"', source, re.MULTILINE))


def _identifiers(block: str) -> list[str]:
    return re.findall(r"\bCap[A-Za-z0-9]+\b", block)


def _go_known(source: str) -> set[str]:
    match = re.search(r"var KnownCapabilities = \[\]Capability\{(.*?)\n\}", source, re.DOTALL)
    assert match, "cannot find KnownCapabilities in the Go catalog"
    constants = _go_constants(source)
    return {constants[name] for name in _identifiers(match.group(1))}


def _go_sensitive(source: str) -> set[str]:
    match = re.search(r"var sensitive = map\[Capability\]bool\{(.*?)\n\}", source, re.DOTALL)
    assert match, "cannot find the sensitive map in the Go catalog"
    constants = _go_constants(source)
    rows = re.findall(r"(Cap[A-Za-z0-9]+)\s*:\s*true", match.group(1))
    return {constants[name] for name in rows}


def _go_master_implied(source: str) -> set[str]:
    match = re.search(r"var MasterImpliedCapabilities = \[\]string\{(.*?)\n\}", source, re.DOTALL)
    assert match, "cannot find MasterImpliedCapabilities in the Go catalog"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_go_known_vocabulary_matches_the_contract(capabilities: dict) -> None:
    source = _go_source()
    assert _go_known(source) == set(capabilities["known_capabilities"])


def test_go_sensitive_set_matches_the_contract(capabilities: dict) -> None:
    expected = {name for name, definition in capabilities["definitions"].items() if definition.get("sensitive") is True}
    assert _go_sensitive(_go_source()) == expected


def test_go_master_implied_set_matches_the_contract(capabilities: dict) -> None:
    expected = set(capabilities["master_capabilities"]["implied_by_private_key"])
    assert _go_master_implied(_go_source()) == expected


def test_every_go_constant_is_reachable_from_the_known_list() -> None:
    source = _go_source()
    constants = set(_go_constants(source).values())
    known = _go_known(source)
    assert constants == known, "a capability constant is declared but not listed in KnownCapabilities"
