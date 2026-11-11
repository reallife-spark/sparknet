"""guard"""

from __future__ import annotations

import json
import re

import pytest
from contract_helpers import (
    CONTRACTS,
    MASTER,
    PEER,
    REPO_ROOT,
    load,
)

pytestmark = pytest.mark.contract


@pytest.fixture(scope="module")
def guard_approval() -> dict:
    return load("guard-approval.json")


def test_the_contract_names_the_canonical_approval_fields(guard_approval: dict) -> None:
    """The contract states the envelope; the code must match it byte for byte."""
    fields = guard_approval["approval"]["fields"]
    assert fields == sorted(fields), "the field list is a projection and must be sorted"
    assert "peer_fingerprint" in fields, "an approval that names no peer can be applied by any peer"
    assert "content_b64" in fields, "the content must be inside the signature, not beside it"
    assert "nonce" in fields and "request_id" in fields, "replay protection needs both"


def test_the_shared_implementation_is_the_rule_the_contract_states(guard_approval: dict, authz) -> None:
    """One rule, in one place. The contract and the implementation must agree."""
    assert tuple(guard_approval["approval"]["fields"]) == authz.GUARD_APPROVAL_FIELDS
    assert tuple(guard_approval["approval"]["required_non_empty"]) == authz.GUARD_APPROVAL_REQUIRED


def test_neither_role_carries_a_second_copy_of_the_approval_rule() -> None:
    """A second copy of the field list is how the signer and the guard drifted
    apart: each signed and verified a different shape, and both kept working."""
    peer = (PEER / "services" / "sparknet-guard-d.py").read_text()
    assert "APPROVAL_FIELDS =" not in peer, "the peer guard carries its own copy of the approval field list"
    assert "guard_approval_message" in peer, "the peer guard must canonicalise through the shared rule"
    signer = (MASTER / "services" / "sparknet-signer.py").read_text()
    assert "APPROVAL_FIELDS =" not in signer, "the signer carries its own copy of the approval field list"
    assert "guard_approval_message" in signer, "the signer must canonicalise through the shared rule"


def test_the_guard_route_and_port_match_the_contract(guard_approval: dict, ports: dict) -> None:
    transport = guard_approval["transport"]
    source = (PEER / "services" / "sparknet-guard-d.py").read_text()
    assert transport["path"] in source, "the peer guard does not serve the route the contract names"
    matches = [(int(p), s) for p, s in ports["ports"].items() if s["service"] == "guard"]
    assert len(matches) == 1, f"expected exactly one guard port, found {matches}"
    assert matches[0][0] == int(transport["port"]), "the contract's approval port is not the guard's port"


def test_the_contract_says_where_the_capability_comes_from(guard_approval: dict) -> None:
    """The envelope must not carry the capability it is checked against."""
    source = guard_approval["capability_source"]
    assert "capabilities" not in guard_approval["approval"]["fields"], (
        "an approval that carries its own capabilities is a privilege-escalation channel"
    )
    assert source["where"], "the contract must say where guard-apply is granted"


def test_master_identity_manifest_flags_the_placeholder_key(identity_schema: dict):
    """The shipped public key cannot sign. Say so where a reader will look."""
    status = identity_schema["master_public_key"]["shipped_value_status"]
    assert re.search(r"BOOTSTRAP ONLY|placeholder|not a real", status, re.I), (
        f"master_public_key.shipped_value_status must flag the placeholder key, got: {status!r}"
    )


def test_registry_ships_empty_so_a_fresh_deployment_is_fail_closed(identity_schema: dict):
    assert identity_schema["registry"]["empty_by_default"] is True
    registry = PEER / "manifests" / "node-authorizations.json"
    if registry.is_file():
        data = json.loads(registry.read_text())
        lists = {k: v for k, v in data.items() if isinstance(v, list)}
        assert lists, f"{registry.name} has no list of authorizations — shape changed?"
        for key, entries in lists.items():
            assert not entries, (
                f"the shipped registry must be empty, but {key} holds {len(entries)} "
                f"entries — a committed entry grants capabilities to whoever holds "
                f"the matching identity"
            )


def test_contracts_readme_names_every_contract_file():
    readme = (CONTRACTS / "README.md").read_text()
    for name in (
        "overlay.json",
        "capabilities.json",
        "identity-schema.json",
        "ports.json",
        "guard-protocol.md",
        "guard-approval.json",
        "share-protocol.md",
        "consensus-protocol.md",
        "tracking-schema.json",
        "provenance-protocol.md",
    ):
        assert name in readme, f"contracts/README.md does not mention {name}"


def test_shared_readme_says_never_copy_the_implementation():
    """Copying it is the exact failure the parent tests guard against."""
    text = (REPO_ROOT / "shared" / "README.md").read_text()
    assert re.search(r"never copy|do not copy|must not be copied|single implementation|only copy", text, re.I), (
        "shared/README.md must tell a reader not to copy sparknet-authz.py into a role"
    )


# Golden vectors now live in tests/test_authz_golden.py.
