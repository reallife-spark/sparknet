"""registry"""

from __future__ import annotations

import pytest
from contract_helpers import (
    MASTER,
    PEER,
    REPO_ROOT,
    load,
)

pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def registry_publication() -> dict:
    return load("registry-publication.json")


def test_the_publication_contract_matches_the_implementation(registry_publication: dict, authz) -> None:
    """The signed projection is a rule, so the contract and the code must agree."""
    publication = registry_publication["publication"]
    assert tuple(publication["fields"]) == authz.REGISTRY_PUBLICATION_FIELDS
    assert tuple(publication["signed_fields"]) == authz.REGISTRY_PUBLICATION_SIGNED_FIELDS
    assert publication["signature_field"] == "signature_b64"
    assert publication["extra_fields"] == "refused"


def test_guard_and_offline_client_share_one_install_rule() -> None:
    """Two receive paths, one rule. A second copy would let them disagree."""
    install = (REPO_ROOT / "shared" / "sparknet-registry-install.py").read_text()
    assert "def accept_publication" in install
    assert "def verify_publication" in install
    for surface in ("sparknet-guard-d.py", "sparknet-registry-client.py"):
        text = (PEER / "services" / surface).read_text()
        assert "accept_publication" in text, f"{surface} does not install through the shared rule"
        assert "REGISTRY_PUBLICATION_FIELDS =" not in text, f"{surface} carries its own field list"


def test_the_registry_route_is_the_guard_route_the_contract_names(registry_publication: dict, ports: dict) -> None:
    transport = registry_publication["transport"]
    guard = (PEER / "services" / "sparknet-guard-d.py").read_text()
    assert transport["path"] in guard, "the guard does not serve the registry route the contract names"
    assert transport["port"] == 9090
    guard_ports = [(int(port), spec) for port, spec in ports["ports"].items() if spec["service"] == "guard"]
    assert [port for port, _ in guard_ports] == [9090], f"the guard port moved: {guard_ports}"


def test_every_documented_refusal_is_a_code_the_peer_can_send(registry_publication: dict) -> None:
    """A refusal nobody can raise is documentation, not a behaviour."""
    peer_code = (REPO_ROOT / "shared" / "sparknet-registry-install.py").read_text()
    guard = (PEER / "services" / "sparknet-guard-d.py").read_text()
    for code in registry_publication["acceptance"]["refusals"]:
        assert code in peer_code or code in guard, f"the contract documents {code!r}, which no peer path raises"
    # The pin is the guard's to check: it owns the key file the rule is given.
    assert "no_master_key" in guard


def test_the_documented_window_is_an_interval_a_reader_can_check(registry_publication: dict) -> None:
    window = registry_publication["distribution"]
    assert int(window["delivery_interval_seconds"]) > 0
    timer = (MASTER / "systemd" / "sparknet-registry-deliver.timer").read_text()
    assert "OnUnitActiveSec=" in timer, "the documented window has no unit that enforces it"
    assert f"OnUnitActiveSec={window['delivery_interval_seconds']}s" in timer
