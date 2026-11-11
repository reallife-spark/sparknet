"""provenance contract"""

from __future__ import annotations

import json
import re
from types import ModuleType

import pytest
from contract_helpers import (
    CONTRACTS,
    MASTER,
    PEER,
    REPO_ROOT,
    guard_port,
)
from sparknet_loader import load_by_path


@pytest.fixture(scope="module")
def provenance() -> ModuleType:
    """shared/sparknet-provenance.py, loaded by path for the reason authz is.

    Loading by path is what proves the tool reads `contracts/` rather than
    carrying a private copy of its rules; an import would let a stale
    installed copy satisfy the assertions below.
    """
    return load_by_path("sparknet_provenance", REPO_ROOT / "shared" / "sparknet-provenance.py")


@pytest.fixture(scope="module")
def master_ledger() -> ModuleType:
    return load_by_path("sparknet_ledger_master", MASTER / "services" / "sparknet-ledger.py")


def test_every_contract_file_is_named_in_the_readme():
    """A contract no reader can find is a contract nobody checks."""
    readme = (CONTRACTS / "README.md").read_text()
    for path in sorted(CONTRACTS.iterdir()):
        if path.is_file() and path.name != "README.md":
            assert path.name in readme, f"contracts/README.md does not mention {path.name}"


def test_ledger_required_fields_are_pinned_in_both_roles(
    tracking: dict, provenance: ModuleType, master_ledger: ModuleType
):
    """Three copies of the block shape, one source: the contract.

    The shapes already diverged once, which is why the append path exists in
    shared/ at all. Pinning all three here means the next divergence fails a
    test instead of a verifier on another node.
    """
    required = tracking["ledger_block"]["required"]
    peer_schema = json.loads((PEER / "blockchain" / "ledger.schema.json").read_text())
    assert peer_schema["required"] == required, "peer ledger.schema.json drifted from contracts/"
    assert list(master_ledger.REQUIRED_FIELDS) == required, "master-node's REQUIRED_FIELDS drifted from contracts/"
    assert provenance.contract()["ledger_block"]["required"] == required, (
        "shared/sparknet-provenance.py read a different contract"
    )


def test_the_event_vocabularies_are_disjoint(tracking: dict, master_ledger: ModuleType):
    """A peer must not be able to record what only the Master can observe."""
    peer = set(tracking["approval"]["event_vocabulary"]["peer"])
    master = set(tracking["approval"]["event_vocabulary"]["master"])
    assert peer and master, "both vocabularies must be non-empty"
    assert not (peer & master), f"an event appears in both vocabularies: {sorted(peer & master)}"
    assert set(master_ledger.MASTER_EVENTS) == master, "master-node's MASTER_EVENTS drifted from contracts/"
    assert "approval" in peer and "share" in peer and "share_ratified" in master


def test_the_note_message_is_built_the_way_the_contract_spells_it(tracking: dict, provenance: ModuleType):
    hashes = {
        "body": "ab" * 32,
        "meta": "cd" * 32,
        "tracking": "ef" * 32,
        "conversation": "01" * 32,
    }
    expected = (
        b"sparknet-note/2\n"
        + hashes["body"].encode("ascii")
        + b"\n"
        + hashes["meta"].encode("ascii")
        + b"\n"
        + hashes["tracking"].encode("ascii")
        + b"\n"
        + hashes["conversation"].encode("ascii")
    )
    assert provenance.note_message(hashes) == expected
    message = tracking["signature"]["message"]
    assert "sparknet-note/2" in message
    for part in ("body_sha256_hex", "meta_sha256_hex", "tracking_sha256_hex", "conversation_root"):
        assert part in message, f"the contract no longer describes {part} in the signed message"


def test_the_co_signature_shape_is_pinned_to_the_contract(tracking: dict, provenance: ModuleType):
    """A second user's attestation must be described in the contract, not the code."""
    co = tracking["co_signature"]
    assert "co_signatures" in tracking["signature"], "the note signature section no longer names co_signatures[]"
    assert tuple(co["entry_fields"]) == tuple(provenance.CO_SIGNATURE_FIELDS), (
        "the tool writes co-signature fields the contract does not describe"
    )
    rule = co["trust_rule"]
    assert "Master-signed registry" in rule, "the online resolver is not stated"
    assert "user.md" in rule and "snapshot" in rule, "the offline fallback is not stated"
    assert "untrusted" in rule, "the contract must distinguish a stranger from a forgery"
    text = (CONTRACTS / "provenance-protocol.md").read_text()
    assert "Co-signatures" in text and "untrusted" in text, (
        "provenance-protocol.md no longer narrates the co-signature trust rule"
    )


def test_the_compiled_rules_are_read_from_the_contract_at_runtime(provenance: ModuleType, tracking: dict):
    """The allowlist must not be restated in code — a restated rule goes stale."""
    source = "\n".join(
        (REPO_ROOT / "shared" / name).read_text()
        for name in (
            "sparknet-provenance.py",
            "sparknet-provenance-note.py",
            "sparknet-provenance-ledger.py",
        )
    )
    for lookup in (
        'contract()["signature"]["compiler_allowlist"]',
        'contract()["ledger_block"]["required"]',
        'contract()["approval"]["event_vocabulary"]["peer"]',
    ):
        assert lookup in source, f"shared/sparknet-provenance*.py no longer reads {lookup}"
    assert tracking["signature"]["compiler_allowlist"], "the allowlist may not be empty"
    assert "updated" in tracking["signature"]["compiler_allowlist"]


def test_the_phase_boundary_names_what_is_and_is_not_built(tracking: dict, ports: dict):
    """The inbox transport is *partly* built, and the boundary must say which part.

    Before fabric Step 67D nothing arrived over a wire; now the RFI **answer** leg
    does (POST /api/v1/rfi on the guard). The load-bearing part is the rule: a
    transport claim is honest only once a listener exists AND ports.json names it,
    so this checks both rather than trusting the prose — and keeps the still-unbuilt
    legs (email, the request channel, the dispatch bridge as a server) named.
    """
    boundary = tracking["phase_boundary"]
    built = " ".join(boundary["built_here"])
    not_built = " ".join(boundary["not_built"])
    # The RFI answer leg is built, and ports.json is what makes the claim honest.
    assert "/api/v1/rfi" in built, "the boundary no longer names the built RFI answer transport"
    _, guard = guard_port(ports)
    assert "/api/v1/rfi" in guard["note"], "ports.json must name the route before transport may be claimed"
    # The legs that are still specified-only stay named as not built.
    assert "email" in not_built
    assert "request channel" in not_built
    assert "dispatch bridge as a server" in not_built
    assert "sign" in built or "layout" in built


def test_provenance_protocol_agrees_with_the_schema(tracking: dict):
    text = (CONTRACTS / "provenance-protocol.md").read_text()
    for outcome in tracking["signature"]["verify_outcomes"]:
        assert f"`{outcome}`" in text, f"provenance-protocol.md never states {outcome}"
    assert "allowlist-based, never percentage-based" in text
    assert "signed_meta" in text, (
        "the narrative must mention the metadata half of the envelope, or a reader "
        "will think only two hashes are signed"
    )
    assert "there is no `approvals.md`" in text or "There is no `approvals.md`" in text


def test_the_secret_index_has_no_field_a_value_could_hide_in(tracking: dict, provenance: ModuleType):
    entry_keys = set(tracking["secret_index"]["entry_fields"])
    forbidden = set(tracking["secret_index"]["forbidden_keys"])
    assert not (entry_keys & forbidden), "a forbidden key is in the entry schema"
    assert entry_keys == set(provenance.SECRET_INDEX_ENTRY_KEYS), (
        "shared/sparknet-provenance.py's entry-key allowlist drifted from contracts/"
    )
    assert forbidden == set(provenance.SECRET_INDEX_FORBIDDEN)


def test_the_user_record_allowlist_is_the_contract_fields(tracking: dict, provenance: ModuleType):
    """A key that is not in the contract must not be acceptable, and vice versa.

    The allowlist is what answers "is a secret hiding in user.md?"; if the two
    copies can drift, one of them is answering a different question.
    """
    assert set(tracking["user_record"]["fields"]) == set(provenance.USER_RECORD_KEYS)
    assert set(tracking["user_record"]["fields"]["key"]) == set(provenance.USER_KEY_FIELDS)


def test_the_shipped_user_record_is_clean_and_conforming(provenance: ModuleType):
    """The tracked record is the template until a node fills itself in.

    Step 11 ran `make user-init` on this node, so the shipped record may be
    either. What must be true on a fresh clone either way: no foreign signed
    senders, no private material, and a record `check_user_record` is happy
    with. A filled record additionally has to match the lock written by
    user-init and carry exactly an ed25519 public key — the private half stays
    in `.state/keys/` (mode 0600, `keys-check`) and is never shipped.
    """
    vault = REPO_ROOT / "peer-node"
    record = provenance.parse_user_record(vault)
    assert record["status"] in ("unfilled", "filled")
    assert record["authorised_senders"] == []
    assert provenance.check_user_record(vault) == []

    if not provenance.user_is_filled(record):
        assert record["key"]["public_key_b64"] == ""
        return

    assert re.fullmatch(r"U-[0-9]{5}", record["owner_id"])
    assert record["key"]["alg"] == "ed25519"
    assert record["key"]["public_key_b64"]
    lock = json.loads((vault / "00_System" / ".user.lock").read_text())
    assert lock["owner_id"] == record["owner_id"]
    shipped = (vault / "00_System" / "user.md").read_bytes()
    assert lock["sha256"] == provenance.sha256_hex(shipped)
    for label, pattern in provenance._PATTERNS:
        assert not pattern.search(shipped.decode("utf-8", "replace")), f"shipped user record: {label}"


def test_the_system_files_point_at_the_contract_instead_of_restating_it(tracking: dict, provenance: ModuleType):
    """`00_System/` holds governance, not a second copy of the schema."""
    system = REPO_ROOT / "peer-node" / "00_System"
    schema = provenance.parse_yaml_subset((system / "schema.yaml").read_text())
    assert schema["source"]["tracking"] == "contracts/tracking-schema.json"
    assert (REPO_ROOT / schema["source"]["tracking"]).is_file()
    assert schema["schema_version"] == tracking["schema_version"], (
        "schema.yaml's version drifted from the contract it defers to"
    )
    assert "tracking_block" not in schema, "schema.yaml must not restate field lists"

    index = json.loads((system / "secrets-index.json").read_text())
    assert index["secrets"] == [], "the shipped index must start with no secrets"
    for entry in index["secrets"]:
        assert set(entry) <= set(provenance.SECRET_INDEX_ENTRY_KEYS)


def test_the_system_files_carry_no_key_shaped_literals(provenance: ModuleType):
    """The scan covers tracked files; these ship before the first commit."""
    system = REPO_ROOT / "peer-node" / "00_System"
    for path in sorted(system.iterdir()):
        if not path.is_file():
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for label, pattern in provenance._PATTERNS:
            assert not pattern.search(text), f"{path.name}: {label}"


def test_the_operator_ceiling_authorises_from_the_attestation(authz: ModuleType):
    """The signed attestation is the authority, not the serving process's uid.

    Operator decision, 2026-10-24: the attestation is allowed to authorise a
    privileged mutation. A minter is trusted — minting is master-side or an
    offline operator act and `operator_os` is inside the signature — so a session
    driven by root may do what root may do even when the daemon answering it runs
    as somebody else. What must never happen is the reverse reading, where the
    daemon's uid sets the ceiling: then how the node was started would decide what
    every session may do.
    """
    root = {"uid": 0, "euid": 0, "username": "root", "groups": ["root"], "is_root": True}
    user = {"uid": 1000, "euid": 1000, "username": "operator", "groups": ["users"], "is_root": False}

    assert authz.operator_os_authorises({"operator_os": root}, requires_root=True) == (True, "")
    allowed, reason = authz.operator_os_authorises({"operator_os": user}, requires_root=True)
    assert not allowed and reason == authz.REASON_OPERATOR_INSUFFICIENT


def test_an_unattested_operator_fails_closed(authz: ModuleType):
    """Null means nobody vouched for this session, not "assume the best case"."""
    for grant in ({"operator_os": None}, {}, {"operator_os": "root"}, {"operator_os": []}):
        allowed, reason = authz.operator_os_authorises(grant, requires_root=True)
        assert not allowed, grant
        assert reason == authz.REASON_OPERATOR_UNATTESTED, grant


def test_root_is_read_not_inferred(authz: ModuleType):
    """uid 0 with is_root false is refused: the two can disagree, and the check must not guess."""
    lying = {"uid": 0, "euid": 0, "username": "root", "groups": ["root"], "is_root": False}
    allowed, reason = authz.operator_os_authorises({"operator_os": lying}, requires_root=True)
    assert not allowed and reason == authz.REASON_OPERATOR_INSUFFICIENT


def test_an_unprivileged_operation_needs_no_attestation(authz: ModuleType):
    """The ceiling binds privilege, not ordinary use of the node."""
    for grant in ({"operator_os": None}, {}, {"operator_os": {"is_root": False}}):
        assert authz.operator_os_authorises(grant, requires_root=False) == (True, "")


def test_the_ceiling_never_raises(authz: ModuleType):
    """A malformed grant must refuse, not blow up — an exception here is a fail-open path."""
    for grant in (None, "not-a-grant", 42, [], object()):
        allowed, reason = authz.operator_os_authorises(grant, requires_root=True)
        assert not allowed
        assert reason in (authz.REASON_GRANT_MALFORMED, authz.REASON_OPERATOR_UNATTESTED)


def test_the_ceiling_reads_a_real_minted_grant(authz: ModuleType):
    """End to end: what mint_grant signs is what the ceiling reads."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    master_key = Ed25519PrivateKey.generate()
    identity = {
        "node_id": "peer-fixture-01",
        "role": "peer",
        "wireguard_public_key_b64": "ZmFrZS13Z2lwdW5pY21hcHViaWMta2V5LWZvci10ZXN0cw==",
        "overlay_ipv4": "10.100.0.7",
        "requested_capabilities": ["telemetry"],
    }
    common = {
        "node_identity": identity,
        "user_identity": "U-20161",
        "conversation_key": "key-1",
        "capabilities": ["telemetry"],
        "vault_scope": [],
        "ttl_minutes": 60,
        "master_private_key": master_key,
    }
    root = authz.mint_grant(
        grant_id="G-ROOT",
        nonce="n-root",
        operator_os={"uid": 0, "euid": 0, "username": "root", "groups": ["root"], "is_root": True},
        **common,
    )
    plain = authz.mint_grant(grant_id="G-PLAIN", nonce="n-plain", **common)
    assert authz.operator_os_authorises(root, requires_root=True)[0] is True
    allowed, reason = authz.operator_os_authorises(plain, requires_root=True)
    assert not allowed and reason == authz.REASON_OPERATOR_UNATTESTED


def _approval_envelope(authz: ModuleType, operator_os: str) -> dict:
    return {
        "peer_fingerprint": "f" * 64,
        "file_path": "/etc/wireguard/wg1.conf",
        "content_b64": "",
        "content_sha256": "0" * 64,
        "issued_at": "2026-10-24T00:00:00Z",
        "expires_at": "2026-10-24T00:01:00Z",
        "nonce": "n-op-1",
        "request_id": "r-op-1",
        "operator_os": operator_os,
    }


def test_one_attestation_has_exactly_one_canonical_encoding(authz: ModuleType) -> None:
    """The envelope field is a string, so the string has to be canonical.

    A nested object would have been canonicalised by the envelope's own
    sort_keys; encoded as a string it is opaque to that, so two orderings of one
    attestation would otherwise produce two signatures over one fact.
    """
    one = {"uid": 1000, "euid": 1000, "username": "op", "groups": ["users", "docker"], "is_root": False}
    other = {"is_root": False, "groups": ["docker", "users", "users"], "username": "op", "euid": 1000, "uid": 1000}
    assert authz.encode_operator_os(one) == authz.encode_operator_os(other)
    assert authz.decode_operator_os(authz.encode_operator_os(one)) == authz.normalise_operator_os(one)
    # Empty is the encoding of "unattested", and it round-trips to None.
    assert authz.encode_operator_os(None) == ""
    assert authz.decode_operator_os("") is None


def test_the_operator_attestation_is_inside_the_approval_signature(authz: ModuleType) -> None:
    """Flipping the attestation must break the signature, or the ceiling is advisory.

    This is the whole reason the field joined the envelope rather than riding
    beside it: an unsigned ceiling could be raised by whoever delivers the
    approval, which is the one party the envelope exists to constrain.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    user = authz.encode_operator_os(
        {"uid": 1000, "euid": 1000, "username": "operator", "groups": ["users"], "is_root": False}
    )
    root = authz.encode_operator_os({"uid": 0, "euid": 0, "username": "root", "groups": ["root"], "is_root": True})

    approval = _approval_envelope(authz, user)
    message = authz.guard_approval_message(approval)
    signature = authz.sign_bytes(key, message)
    assert authz.verify_signature(key.public_key(), signature, message)

    escalated = _approval_envelope(authz, root)
    assert authz.guard_approval_message(escalated) != message
    assert not authz.verify_signature(key.public_key(), signature, authz.guard_approval_message(escalated)), (
        "a non-root attestation was re-signed as root with the same signature"
    )


def test_the_ceiling_reads_the_envelope(authz: ModuleType) -> None:
    """The guard's one call, against encoded envelope values rather than dicts."""
    root = authz.encode_operator_os({"uid": 0, "euid": 0, "username": "root", "groups": ["root"], "is_root": True})
    user = authz.encode_operator_os(
        {"uid": 1000, "euid": 1000, "username": "operator", "groups": ["users"], "is_root": False}
    )
    allows = authz.guard_approval_operator_allows
    assert allows({"operator_os": root}, requires_root=True) == (True, "")
    assert allows({"operator_os": user}, requires_root=True)[1] == authz.REASON_OPERATOR_INSUFFICIENT
    assert allows({"operator_os": ""}, requires_root=True)[1] == authz.REASON_OPERATOR_UNATTESTED
    assert allows({}, requires_root=True)[1] == authz.REASON_OPERATOR_UNATTESTED
    assert allows({"operator_os": "{not json"}, requires_root=True)[1] == authz.REASON_OPERATOR_MALFORMED
    assert allows(None, requires_root=True)[1] == authz.REASON_OPERATOR_MALFORMED
    # An unprivileged operation needs no attestation: the ceiling binds privilege.
    assert allows({"operator_os": ""}, requires_root=False) == (True, "")
