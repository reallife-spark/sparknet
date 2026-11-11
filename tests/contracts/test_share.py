"""share"""

from __future__ import annotations

import json
import re
from types import ModuleType

import pytest
from contract_helpers import (
    CONTRACTS,
    MASTER,
    PEER,
    load,
    share_policy,
)

pytestmark = pytest.mark.contract


def test_share_protocol_states_its_own_build_boundary(ports: dict):
    """Same honesty guard as guard-protocol.md, aimed at the real boundary.

    This used to require the literal phrase "nothing here is built", which was
    true while the regime was only specced and became false the moment peer Steps
    6 and 8 and Master Steps 10-12 closed. A guard that pins a *sentence* keeps
    that sentence alive past its truth — it made the contract page lie, and the
    test then failed anyone who tried to correct it. So this pins the fact
    instead: the code exists, the deployment does not, and the page must say
    which is which and cite something checkable.
    """
    text = (CONTRACTS / "share-protocol.md").read_text()
    assert re.search(r"not built|not deployed", text, re.I), (
        "share-protocol.md must state plainly what is still unbuilt"
    )
    for source in ("share-regime.json", "ports.json"):
        assert source in text, f"share-protocol.md must cite {source} for its build state"

    # Neither direction may drift: the manifest's status and ports.json's
    # code-vs-runtime split are what the page's claim rests on.
    regime = json.loads((PEER / "manifests" / "share-regime.json").read_text())
    assert regime["status"] in (
        "wired, not deployed",
        "listener built, not deployed",
        "live on the peer_pair; 4203 not bound",
    ), "share-regime.json's status moved; re-check share-protocol.md's build boundary against it"
    if regime["status"] != "wired, not deployed":
        assert (PEER / "services" / "sparknet-share-serve.py").is_file(), (
            "the manifest claims a listener; the listener service must exist"
        )
        assert (MASTER / "services" / "sparknet-share-ratify.py").is_file(), (
            "the manifest claims 4203; the ratification service must exist"
        )
    for port in ("4201", "4202"):
        assert ports["ports"][port]["implementation_state"] == "implemented", port
        assert ports["ports"][port]["runtime"] == "not-listening", f"{port} is not bound on this development host"
        assert "2026-10-31" in ports["ports"][port]["runtime_why"], (
            f"{port} must record the dated live-pair observation beside the local runtime axis"
        )
    assert ports["ports"]["4203"]["implementation_state"] in ("implemented", "provisioned"), (
        "4203 should be implemented/provisioned for the ratification side"
    )
    assert ports["ports"]["4203"]["runtime"] == "not-listening", (
        "the 4203 listener is built but no unit is enabled; runtime must still say not-listening"
    )


def test_share_protocol_states_every_element_the_regime_needs(ports: dict):
    text = (CONTRACTS / "share-protocol.md").read_text().lower()
    for element in ("invite", "accept", "share type", "clock", "trust level", "isolat", "evidence"):
        assert element in text, f"share-protocol.md never covers {element!r}"


def test_share_protocol_durations_match_the_machine_readable_clocks(ports: dict):
    """Prose cannot drift from the policy it describes.

    The four deadlines govern expiry, so a change to one in the JSON without a
    matching edit here — or the reverse — would make the document describe a
    regime the code does not implement.
    """
    text = (CONTRACTS / "share-protocol.md").read_text()
    clocks = share_policy()["share_clocks"]["clocks"]
    expected = {
        "invite_acceptance": ("1 h", "1h"),
        "idle_close": ("20 min", "20m"),
        "ratification": ("2 h", "2h"),
        "share_absolute": ("10 h", "10h"),
    }
    for name, spellings in expected.items():
        duration = clocks[name]["duration"]
        assert duration in spellings, (
            f"{name} is {duration!r} in capabilities.json, which is neither spelling share-protocol.md is checked for"
        )
        assert any(s in text for s in spellings), f"share-protocol.md never states the {name} duration {duration!r}"


def test_every_clock_states_what_silence_does(ports: dict):
    """A deadline with no specified expiry behaviour is not a deadline."""
    for name, spec in share_policy()["share_clocks"]["clocks"].items():
        assert spec.get("on_expiry"), f"clock {name} does not say what expiry does"
        assert spec.get("binds"), f"clock {name} does not say whose clock binds it"
        assert spec.get("duration"), f"clock {name} has no duration"


def test_share_types_are_a_closed_set_and_narrowing_only(ports: dict):
    types = share_policy()["share_types"]
    assert types["closed_vocabulary"] is True
    assert "narrowing_only" in types, (
        "a receiver must be able to accept less than was offered; that rule is "
        "the reason share types are safe to hand to a human"
    )
    for name, spec in types["types"].items():
        assert spec.get("conveys"), f"share type {name} does not say what it conveys"
        assert "copies" in spec, f"share type {name} does not say whether it copies"
        if name != "full":
            assert "includes" not in spec, (
                f"{name} must not include other types; 'full' is the only union, "
                f"so a future type cannot silently join a broad grant"
            )
    assert set(types["types"]["full"]["includes"]) == {n for n in types["types"] if n != "full"}, (
        "full must be exactly the union of the other share types"
    )


def test_isolation_keeps_the_evidence_channel_and_the_choice_is_recorded(ports: dict):
    """The reading is deliberate, so the contract must carry the alternative.

    A severed Master link would leave the required review unsatisfiable. If that
    reading is ever replaced, the alternative has to still be findable here.
    """
    overlay = load("overlay.json")
    assert overlay["data_plane_stanza"]["is_authority_plane"] is False
    assert overlay["data_plane_stanza"]["time_boxed"] is True
    text = (CONTRACTS / "share-protocol.md").read_text().lower()
    assert "data plane" in text and "evidence" in text
    assert re.search(r"alternative reading", text), (
        "share-protocol.md must record the alternative isolation reading so the "
        "choice stays visible if the chosen one proves wrong"
    )


def test_authority_plane_invariant_survives_the_governance_modes(ports: dict):
    """Adding governance_mode must not have widened anything it can reach."""
    overlay = load("overlay.json")
    rule = overlay["peer_allowed_ips_rule"]
    assert "exactly one address" in rule, (
        "the single-address AllowedIPs rule is the authority-plane boundary; a "
        "governance mode that needed more would be a design change, not a doc edit"
    )
    assert overlay["governance_mode"]["authority_consequence"], (
        "governance_mode must state that it never widens the authority plane"
    )
    for name in overlay["governance_mode"]["modes"]:
        assert overlay["governance_mode"]["modes"][name].get("rule"), f"governance mode {name} has no rule"


def test_ratified_shares_retain_their_flag(ports: dict):
    """Approval must not erase the fact that unapproved data crossed nodes."""
    trust = share_policy()["trust_levels"]
    assert trust["retained_after_ratification"] is True
    assert "retained_rationale" in trust
    text = (CONTRACTS / "share-protocol.md").read_text().lower()
    assert "retain" in text, "share-protocol.md must state that the flag survives ratification"
    assert "never a permission" in trust["never_a_grant"] or "never grants authority" in trust["never_a_grant"]


def test_a_trust_level_can_never_be_a_grant(ports: dict):
    trust = share_policy()["trust_levels"]
    for level, spec in trust["levels"].items():
        assert spec.get("means"), f"trust level {level} does not define itself"
        assert "shares_allowed" in spec, f"trust level {level} does not say whether shares are permitted"
    assert trust["never_a_grant"], "trust levels must be declared belief, not permission"
    assert "registry" in trust["who_moves_them"], "only the Master may move trust levels, via the signed registry"


def test_grant_checks_reuse_the_guard_check_order(ports: dict):
    """One verification implementation, or two trust boundaries to get wrong."""
    grant = load("identity-schema.json")["grant"]
    assert len(grant["verification_order"]) >= 5
    assert "guard-protocol" in grant["verification_order_note"], (
        "grant verification must state that it reuses the guard's check order"
    )
    assert grant["fields"]["expires_at"]["local_enforcement"], (
        "an expired grant must be refused locally, not merely by its issuer"
    )
    assert grant["fields"]["nonce"]["retention"], "a nonce needs a stated retention or the replay window opens silently"
    assert grant["fields"]["parent_grant_id"], "delegation must be representable, since subagents inherit grants"


def test_grant_projection_matches_the_contract(authz: ModuleType):
    """The signed grant projection is one field list stated in two places, so pin both.

    The registry side already does this for `SIGNED_FIELDS`; the grant side did
    not, which let `grant.fields` in the contract and `GRANT_FIELDS` in the
    implementation drift with nothing red. That is not a documentation problem: a
    grant whose signer projects one field set and whose verifier projects another
    is a grant that verifies here and fails on a node, or the reverse.

    Compared as sets, not tuples — `grant_message` serialises with `sort_keys`, so
    the order fields are listed in cannot change the bytes, and pinning an order
    would fail a harmless reorder while still missing a real one.
    """
    grant = load("identity-schema.json")["grant"]
    declared = set(grant["fields"])
    assert declared == set(authz.GRANT_FIELDS), (
        f"grant projection drifted: contract-only {sorted(declared - set(authz.GRANT_FIELDS))}, "
        f"code-only {sorted(set(authz.GRANT_FIELDS) - declared)}"
    )
    # Every required field must exist in the projection, or a grant could be
    # canonicalised without a field the contract says it must carry.
    assert set(authz.GRANT_REQUIRED) <= set(authz.GRANT_FIELDS)
    # The optional ones are optional on purpose: null is a meaning, not a gap.
    for optional in ("overlay_ipv4", "vault_scope", "parent_grant_id", "operator_os"):
        assert optional in authz.GRANT_FIELDS
        assert optional not in authz.GRANT_REQUIRED, (
            f"{optional} is required, so a grant cannot express 'none attested' — "
            f"and for operator_os that would force a mint to invent an OS identity"
        )


def test_operator_os_is_a_closed_normalised_shape(authz: ModuleType):
    """The attested OS identity must not be coercible into a second canonical form.

    It caps what an agent may do, so two spellings of one identity producing two
    signatures — or a wrong type being quietly converted — would make the ceiling
    depend on how a caller shaped its input.
    """
    attested = {"uid": 1000, "euid": 1000, "username": "operator", "groups": ["users", "docker"], "is_root": False}
    normalised = authz.normalise_operator_os(attested)
    assert normalised["groups"] == ["docker", "users"], "groups are sorted and deduplicated"
    # Group order must not change the canonical bytes.
    reordered = authz.normalise_operator_os({**attested, "groups": ["docker", "users", "users"]})
    assert reordered == normalised
    assert authz.normalise_operator_os(None) is None

    for bad in (
        {**attested, "uid": "1000"},  # wrong type, must not be coerced
        {**attested, "is_root": 0},  # bool required, and 0 is not False here
        {**attested, "uid": True},  # bool is an int subclass; uid 1 is a lie
        {**attested, "uid": -1},
        {**attested, "username": ""},
        {**attested, "groups": "docker"},
        {**attested, "groups": [1000]},
        {k: v for k, v in attested.items() if k != "username"},  # missing
        {**attested, "sudo": True},  # undeclared field
        "not-an-object",
    ):
        with pytest.raises(authz.AuthzError):
            authz.normalise_operator_os(bad)


def test_a_grant_carries_its_operator_os_inside_the_signature(authz: ModuleType):
    """Signed, so the ceiling travels with the grant and cannot be raised in transit."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    master_key = Ed25519PrivateKey.generate()
    identity = {
        "node_id": "peer-fixture-01",
        "role": "peer",
        "wireguard_public_key_b64": "ZmFrZS13Z2lwdW5pY21hcHViaWMta2V5LWZvci10ZXN0cw==",
        "overlay_ipv4": "10.100.0.7",
        "requested_capabilities": ["telemetry"],
    }
    attested = {"uid": 1000, "euid": 1000, "username": "operator", "groups": ["users"], "is_root": False}
    grant = authz.mint_grant(
        node_identity=identity,
        grant_id="GRANT-OS-1",
        user_identity="U-20161",
        conversation_key="key-1",
        capabilities=["telemetry"],
        vault_scope=["05_Knowledge"],
        ttl_minutes=60,
        nonce="nonce-os-1",
        master_private_key=master_key,
        operator_os=attested,
    )
    assert grant["operator_os"] == authz.normalise_operator_os(attested)
    assert "operator_os" in authz.grant_message(grant).decode()

    # Widening the ceiling invalidates the signature: it is inside the envelope.
    escalated = {**grant, "operator_os": {**grant["operator_os"], "is_root": True}}
    assert authz.grant_message(escalated) != authz.grant_message(grant)
    assert not authz.verify_signature(
        master_key.public_key(), escalated["signature_b64"], authz.grant_message(escalated)
    )

    # And a grant minted with no attestation says so rather than implying one.
    bare = authz.mint_grant(
        node_identity=identity,
        grant_id="GRANT-OS-2",
        user_identity="U-20161",
        conversation_key="key-1",
        capabilities=["telemetry"],
        vault_scope=[],
        ttl_minutes=60,
        nonce="nonce-os-2",
        master_private_key=master_key,
    )
    assert bare["operator_os"] is None


def test_share_endpoints_are_declared_and_separate(ports: dict):
    """Passing and sharing need independent grants, so they cannot share a port."""
    declared = {spec["service"]: int(n) for n, spec in ports["ports"].items()}
    for service in ("share-intake", "session-transfer", "share-ratification", "opencode-serve"):
        assert service in declared, f"{service} is used but not declared in ports.json"
    assert declared["share-intake"] != declared["session-transfer"], (
        "share-intake and session-transfer must be distinct ports so granting "
        "conversation passing does not implicitly grant knowledge sharing"
    )
    for service in ("share-intake", "session-transfer"):
        assert ports["ports"][str(declared[service])]["overlay_only"] is True
    ratification = ports["ports"][str(declared["share-ratification"])]
    assert ratification["bound_by"] == "master" and ratification["overlay_only"] is True


def test_the_share_plane_grants_no_authority(ports: dict):
    """The share ports carry offers and proposals, never authority.

    A share and a proposal are both statements, not grants: neither edits a note
    nor hands out a capability (share-protocol.md "What a share is";
    proposal-schema.json verify_proposal_chain.not_authority). Step 36 changes
    only the *state*: the share engine (sparknet-share-regime.py) and the
    proposal route (sparknet-proposal-exchange.py) now exist; on 2026-10-31 the
    share listeners were bound on the live pair, so share-intake and
    session-transfer are `implemented` + `not-listening` locally, live on the pair. The Master's side of the share plane
    (share-ratification) — implemented for Step 10 — must be declared and not
    grant authority; opencode-serve stays as specified.
    """
    for number, spec in ports["ports"].items():
        if spec["service"] not in ("share-intake", "session-transfer", "share-ratification", "opencode-serve"):
            continue
        assert spec.get("status"), f"port {number} must say what is there"
        if spec["service"] in ("share-intake", "session-transfer"):
            assert spec["implementation_state"] == "implemented", (
                f"port {number} ({spec['service']}) has a built engine "
                f"(sparknet-share-regime.py / sparknet-proposal-exchange.py) and "
                f"must say so"
            )
            assert spec["runtime"] == "not-listening", (
                f"port {number} ({spec['service']}) is not bound on this development host"
            )
            assert spec.get("runtime_why"), (
                f"port {number} ({spec['service']}) is implemented with no running listener; it must record why"
            )
        elif spec["service"] == "share-ratification":
            assert spec["implementation_state"] in ("implemented", "provisioned")
            assert spec["runtime"] == "not-listening"
        else:
            assert spec["implementation_state"] == "spec-only", (
                f"port {number} ({spec['service']}) must stay spec-only until built"
            )
            assert spec["runtime"] == "not-listening"
