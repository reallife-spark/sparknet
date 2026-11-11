"""consensus"""

from __future__ import annotations

import re

from contract_helpers import (
    CONTRACTS,
    load,
    share_policy,
)


def test_guard_protocol_no_longer_claims_a_peer_can_never_sign_as_a_fact(ports: dict):
    """A peer contains the signing code; what denies it is state, not structure.

    The old sentence was true when the two roles were different programs. It is
    false now that a master is a peer that won an election, and a reader trusting
    it would look for the guarantee in the wrong place.
    """
    text = (CONTRACTS / "guard-protocol.md").read_text()
    assert not re.search(r"A peer can \*\*verify\*\* an approval but never \*\*produce\*\* one", text), (
        "guard-protocol.md still states the asymmetry as a structural fact; it is a role state under the election model"
    )
    assert re.search(r"role state, not a structure", text), "guard-protocol.md must say where the asymmetry now lives"
    assert "consensus-protocol.md" in text, "guard-protocol.md must point at the protocol that now decides who may sign"


def test_consensus_protocol_states_the_whole_agreement(ports: dict):
    text = (CONTRACTS / "consensus-protocol.md").read_text().lower()
    for element in ("membership", "election", "unanim", "trust root", "re-formation", "cluster key"):
        assert element in text, f"consensus-protocol.md never covers {element!r}"


def test_the_trust_root_replaces_the_single_key_model(ports: dict):
    schema = load("identity-schema.json")
    root = schema["cluster_trust_root"]
    assert "replaces" in root and "master_public_key" in root["replaces"], (
        "the root must state what it supersedes, or the old single-key model stays readable as though it were current"
    )
    assert root["members"]["min"] == 2, "a pair is the smallest cluster that still refuses self-elevation"
    assert root["members"]["max"] == 3
    assert root["members"]["boundary"], (
        "the count range is a protocol decision, not a tunable; a fourth member "
        "changes the threshold and needs its own design"
    )
    assert root["unanimity"]["threshold"].startswith("n of n")
    assert root["not_threshold_crypto"], (
        "state plainly that this is ordinary per-member signatures, not threshold "
        "cryptography, so nobody designs a quorum scheme expecting MPC semantics"
    )


def test_two_key_separation_is_recorded(ports: dict):
    """A member present in the cluster must not thereby be able to sign."""
    keys = load("identity-schema.json")["cluster_trust_root"]["two_keys"]
    assert "root" in keys["cluster_key"] and "never" in keys["cluster_key"]
    assert "registry" in keys["operational_key"]
    assert keys["cluster_key"] != keys["operational_key"]


def test_root_acceptance_requires_distinct_signers_that_the_root_names(ports: dict):
    """The first two acceptance rules are decorative without the last two."""
    rules = " ".join(load("identity-schema.json")["cluster_trust_root"]["acceptance_rules"]).lower()
    assert "distinct" in rules, "a member voting three times must count as one vote"
    assert "names" in rules or "names it" in rules, (
        "a root must be signed only by members the root itself names, or it could "
        "name members and be signed by strangers"
    )
    assert "master_pubkey" in rules, "the registry must be checked against the operational key the root names"


def test_replace_requires_unanimity_but_revoke_does_not(ports: dict):
    table = load("identity-schema.json")["cluster_trust_root"]["threshold_table"]
    assert table["replace_master"].startswith("n of n"), "changing who holds authority must not be unilateral"
    assert table["revoke_node"].startswith("1"), (
        "revocation is a safe denial and must stay unilateral, or a dead master would brick the fabric"
    )


def test_reformation_is_not_a_bypass(ports: dict):
    reformation = load("identity-schema.json")["cluster_trust_root"]["reformation"]
    assert reformation.get("not_a_bypass"), (
        "re-formation must state it cannot install a master without unanimity "
        "among the members it names, or it is a back door around the election"
    )
    assert "new root" in reformation["on_master_change"], (
        "a master change must be a new root with a different nonce, so the old operational key stops being recognised"
    )


def test_election_vote_is_a_say_not_a_grant(ports: dict):
    caps = share_policy()
    assert "cluster-vote" in caps["known_capabilities"]
    vote = caps["definitions"]["cluster-vote"]
    assert vote["holder"] == "peer", "every member holds a vote, because election is what makes a master at all"
    assert vote["sensitive"] is False
    assert "confer nothing" in vote["note"] or "not a grant" in vote["note"]
    # The Master's authority must remain key possession, not a granted capability.
    assert "possession" in caps["master_capabilities"]["note"]


def test_the_election_port_is_declared_and_carries_no_authority(ports: dict):
    declared = {s["service"]: int(n) for n, s in ports["ports"].items()}
    assert "cluster-election" in declared, "the election port is used but undeclared"
    election = ports["ports"][str(declared["cluster-election"])]
    assert election["implementation_state"] == "implemented", (
        "shared/sparknet-election.py serve is the exchange listener; ports.json "
        "claiming spec-only would understate a built authority-adjacent surface"
    )
    assert election["runtime"] == "not-listening", (
        "implemented but not running is the honest pair on this host: the code exists, nothing here binds 4210"
    )
    assert election["overlay_only"] is True
    assert "never a registry entry" in election["note"], (
        "the election port must be explicit that it does not carry authority, since it decides who holds the key"
    )
    assert declared["cluster-election"] != declared["share-ratification"], (
        "electing a master and confirming a share must stay separately gated"
    )


def test_the_operational_key_is_isolated_by_contract(ports: dict):
    """The prose must state the isolation, because Step 17 implements it."""
    text = (CONTRACTS / "consensus-protocol.md").read_text().lower()
    assert "signer" in text, (
        "consensus-protocol.md must say where the operational key lives, or a "
        "reader will assume it sits beside the web UI"
    )
    assert "structural" in text, (
        "isolation must be called structural and not a permission rule, since a "
        "deny rule is a policy the governed LLM surface may later ignore"
    )
