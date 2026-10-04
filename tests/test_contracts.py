"""Cross-role contract conformance.

`contracts/` is the single source of truth for what a peer and a master agree
on. The risk is not that the contract is wrong; it is that one role's copy of it
drifts while the other keeps working against its own stale assumption. Nothing
in either role would notice — a peer reading the wrong capability list still
verifies signatures happily, and a peer that hard-codes a stale overlay address
still brings its tunnel up.

So these tests pin the contract against the things that consume it: the shared
signing implementation, both roles' manifests, the configuration templates and
the role vocabulary itself. Run via `make contract-test`.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = REPO_ROOT / "contracts"
SHARED_PATH = REPO_ROOT / "shared" / "sparknet-authz.py"
PEER = REPO_ROOT / "peer-node"
MASTER = REPO_ROOT / "master-node"

MASTER_HOST = 1
BROADCAST_HOST = 255


def load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text())


@pytest.fixture(scope="module")
def overlay() -> dict:
    return load("overlay.json")


@pytest.fixture(scope="module")
def capabilities() -> dict:
    return load("capabilities.json")


@pytest.fixture(scope="module")
def identity_schema() -> dict:
    return load("identity-schema.json")


@pytest.fixture(scope="module")
def ports() -> dict:
    return load("ports.json")


@pytest.fixture(scope="module")
def authz() -> ModuleType:
    """Load the one shared implementation by path, not by import.

    It lives outside the package so that neither role can accidentally import a
    private copy; importing by path is what proves there is only one of them.
    """
    spec = importlib.util.spec_from_file_location("sparknet_authz", SHARED_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves its own module via sys.modules, so it must be
    # registered before exec_module or @dataclass blows up with a confusing
    # AttributeError about __dict__.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


# --- there is exactly one implementation, and it agrees with the contract ------


def test_only_one_authz_implementation_exists():
    """A second copy would let the two roles diverge while both still pass."""
    copies = [
        p
        for p in REPO_ROOT.rglob("sparknet-authz.py")
        if not {"__pycache__", "dist", ".venv", ".git"} & set(p.parts)
    ]
    assert copies == [SHARED_PATH], f"expected one authz implementation, found: {copies}"


def test_shared_constants_match_the_contract(
    authz: ModuleType, capabilities: dict, identity_schema: dict
):
    """Every list the code and the contract both declare must be identical.

    These are the fields that decide who may do what. A one-entry difference
    here is a silent authorisation bug in whichever direction it points, so it is
    compared as a set rather than by sampling a few members.
    """
    assert set(authz.KNOWN_CAPABILITIES) == set(capabilities["known_capabilities"]), (
        "capability vocabulary differs between contracts and the implementation"
    )
    assert tuple(authz.IDENTITY_FIELDS) == tuple(identity_schema["identity_fields"]), (
        "identity fields differ — the fingerprint would differ between the roles"
    )
    assert tuple(authz.SIGNED_FIELDS) == tuple(identity_schema["signed_envelope_fields"]), (
        "signed envelope fields differ — one role would verify what the other signed"
    )
    assert authz.SCHEMA_VERSION == identity_schema["schema_version"]


def test_guard_apply_is_present_and_marked_sensitive(capabilities: dict):
    """It is the only capability that turns a signature into a filesystem write.

    If it ever fell out of the vocabulary the guard would still verify and audit
    while being structurally unable to apply — decorative, and quietly so.
    """
    assert "guard-apply" in capabilities["known_capabilities"]
    assert capabilities["definitions"]["guard-apply"]["sensitive"] is True
    # And the vocabulary is closed: a definition without a vocabulary entry would
    # be silently rejected at verification time.
    assert set(capabilities["definitions"]) == set(capabilities["known_capabilities"])


def test_signed_envelope_covers_everything_that_grants_power(identity_schema: dict):
    """`capabilities` and `revoked` must be inside the signature.

    Signing only the identity would leave `capabilities` editable by anyone who
    can write the registry file — escalating a peer to guard-apply without the
    Master approving it. `revoked` is inside for the converse reason: an attacker
    with registry write access may deny service, never reinstate it.
    """
    signed = set(identity_schema["signed_envelope_fields"])
    for required in ("fingerprint", "identity", "capabilities", "overlay_ipv4",
                     "issued_at", "expires_at", "revoked"):
        assert required in signed, (
            f"{required} is outside the signed envelope, so it is mutable by "
            f"anyone who can edit the registry"
        )


# --- overlay addressing --------------------------------------------------------


def test_master_is_the_anchor_and_the_peer_prefix_agrees(overlay: dict):
    prefix = overlay["master_anchor_ipv4"]
    assert prefix.startswith(overlay["peer_prefix"]), (
        f"the Master address {prefix} does not share the peer prefix "
        f"{overlay['peer_prefix']} — the two roles would compute different networks"
    )
    assert int(prefix.rsplit(".", 1)[1]) == MASTER_HOST
    assert prefix in overlay["reserved_peer_addresses"], (
        "the Master address must be reserved against peer assignment"
    )


def test_peer_range_excludes_the_master_and_the_broadcast(overlay: dict):
    low, high = overlay["peer_host_range"]
    assert low > MASTER_HOST, "the peer range must start above the Master address"
    assert high < BROADCAST_HOST, "the peer range must stop below the broadcast address"
    assert low <= high
    for reserved in overlay["reserved_peer_addresses"]:
        host = int(reserved.rsplit(".", 1)[1])
        assert not (low <= host <= high), (
            f"{reserved} is reserved but sits inside the assignable peer range"
        )


def test_peer_identity_is_a_single_host_inside_the_range(overlay: dict):
    identity = json.loads((PEER / "manifests" / "node-identity.json").read_text())
    address = identity["overlay_ipv4"]
    assert address.endswith(overlay["peer_mask"]), (
        f"a peer must be a {overlay['peer_mask']} host route, got {address} — a wider "
        f"mask would let it route for a sibling"
    )
    host = int(address.split("/")[0].rsplit(".", 1)[1])
    low, high = overlay["peer_host_range"]
    assert low <= host <= high, f"peer host {host} outside the contract range [{low}, {high}]"
    assert host != MASTER_HOST, "a peer must never claim the Master address"


def test_both_templates_use_the_contract_mtu_and_keepalive(overlay: dict):
    """A mismatch is invisible in review and shows up only as odd throughput."""
    mtu, keepalive = str(overlay["mtu"]), str(overlay["persistent_keepalive"])
    for path in (
        PEER / "configs" / "wireguard" / "wg0-node.conf.template",
        MASTER / "configs" / "wireguard" / "master-peer.template",
    ):
        text = path.read_text()
        assert f"MTU = {mtu}" in text, (
            f"{path.name} does not use the contract MTU {mtu} "
            f"(contracts/overlay.json carries the rationale)"
        )
    peer_text = (PEER / "configs" / "wireguard" / "wg0-node.conf.template").read_text()
    assert f"PersistentKeepalive = {keepalive}" in peer_text, (
        "the peer template must keep the NAT mapping open, as the contract says"
    )


def test_master_template_offers_only_single_host_routes():
    """A wide master-side AllowedIPs would let a peer source-spoof a sibling.

    The placeholder form (`${NODE_ADDRESS}`) is correct — it defers to the
    signed entry. What must not appear is a *literal* that is wider than one
    host, because that is what someone would copy into production.
    """
    text = (MASTER / "configs" / "wireguard" / "master-peer.template").read_text()
    literals = re.findall(r"AllowedIPs\s*=\s*(\S+)", text)
    assert literals, "the template should show at least the AllowedIPs form to render"
    for value in literals:
        if "$" in value:
            continue  # a placeholder is rendered from the signed entry
        for part in value.split(","):
            part = part.strip()
            assert part.endswith("/32"), (
                f"master-side AllowedIPs offers {part!r}, wider than a single host — "
                f"that peer could then source-spoof a sibling "
                f"(contracts/overlay.json `peer_allowed_ips_rule`)"
            )
    assert overlay_rule_reference(text), "the master template must state the single-host rule"


def overlay_rule_reference(text: str) -> bool:
    return bool(re.search(r"only its own overlay address|source-spoof", text, re.I))


def test_templates_document_the_immutable_pin_and_config_mode(overlay: dict):
    """A peer config that is writable is a peer config a compromised peer owns."""
    assert overlay["pinned_immutable"] is True
    assert overlay["config_mode"] == "0600"
    text = (PEER / "configs" / "wireguard" / "wg0-node.conf.template").read_text()
    assert "chattr" in text, "the peer template must document the +i pin"
    assert "0600" in text, "the peer template must state the config mode from the contract"


def test_peer_template_anchors_on_the_master_address(overlay: dict):
    text = (PEER / "configs" / "wireguard" / "wg0-node.conf.template").read_text()
    assert f"{overlay['master_anchor_ipv4']}{overlay['peer_mask']}" in text, (
        "the peer's master-side AllowedIPs must be exactly the Master /32"
    )


# --- ports ---------------------------------------------------------------------


def guard_port(ports: dict) -> tuple[int, dict]:
    matches = [(int(p), s) for p, s in ports["ports"].items() if s["service"] == "guard"]
    assert len(matches) == 1, f"expected exactly one guard port, found {matches}"
    return matches[0]


def test_the_two_significant_ports_are_not_transposed(ports: dict):
    """9090 is the peer's guard; 8090 is the master's instant-push.

    Transposing them is invisible until an approval is POSTed to a listener that
    either does not exist or does the wrong thing.
    """
    guard_number, guard = guard_port(ports)
    assert guard["bound_by"] == "peer" and guard_number == 9090

    push = [(int(p), s) for p, s in ports["ports"].items()
            if s["service"] == "master-instant-push"]
    assert len(push) == 1, f"expected exactly one instant-push port, found {push}"
    push_number, push_spec = push[0]
    assert push_spec["bound_by"] == "master" and push_number == 8090


def test_guard_port_is_overlay_only_and_implemented(ports: dict):
    _, guard = guard_port(ports)
    assert guard["overlay_only"] is True, (
        "the guard must be unreachable from the WAN by design"
    )
    assert guard["implemented"] is True
    assert "own overlay address" in guard["binds_to"], (
        "the guard must bind its own overlay address, never a wildcard"
    )


def test_unimplemented_ports_say_so_instead_of_pretending(ports: dict):
    """An unimplemented port must be flagged, not merely absent from code."""
    for number, spec in ports["ports"].items():
        if spec.get("implemented") is False:
            assert re.search(r"SPEC ONLY|not implemented|no listener", spec.get("status", ""), re.I), (
                f"port {number} ({spec['service']}) is not implemented but its "
                f"status does not say so: {spec.get('status')!r}"
            )
            assert "MASTER_BUILD_PLAN" in spec.get("status", ""), (
                f"port {number} must point at the plan step that will build it"
            )


def test_no_service_claims_two_ports(ports: dict):
    seen: dict[str, int] = {}
    for number, spec in ports["ports"].items():
        assert spec["service"] not in seen, (
            f"{spec['service']} claims both {seen[spec['service']]} and {number}"
        )
        seen[spec["service"]] = int(number)


def test_guard_daemon_uses_the_contract_port_and_binds_narrow(ports: dict):
    number, _ = guard_port(ports)
    source = (PEER / "services" / "sparknet-guard-d.py").read_text()
    assert str(number) in source, (
        "the guard daemon does not use the port named in contracts/ports.json"
    )
    assert "0.0.0.0" not in source, (
        "the guard must not bind a wildcard address — that would expose the "
        "approval endpoint on every interface"
    )


# --- the role vocabulary -------------------------------------------------------


def test_contract_declares_exactly_two_roles(identity_schema: dict):
    assert set(identity_schema["roles"]) == {"master", "peer"}, (
        f"role vocabulary is {sorted(identity_schema['roles'])} — adding a role is a "
        f"contract change both roles must adopt in the same commit"
    )


@pytest.mark.parametrize(
    "role_dir,expected_role",
    [(PEER, "peer"), (MASTER, "master")],
    ids=["peer-node", "master-node"],
)
def test_each_role_declares_its_own_role_value(role_dir: Path, expected_role: str):
    """The pre-split vocabulary was `worker`, which is what the peer role is not."""
    manifests = role_dir / "manifests"
    if not manifests.is_dir():
        pytest.skip(f"{role_dir.name}/manifests does not exist yet")
    checked = 0
    for path in sorted((role_dir / "manifests").glob("*.json")):
        data = json.loads(path.read_text())
        if "role" in data:
            assert data["role"] == expected_role, f"{path.name}: {data['role']!r}"
            checked += 1
        if "roles" in data:
            assert expected_role in data["roles"], f"{path.name}: {data['roles']}"
            checked += 1
    assert checked, f"{role_dir.name}/manifests holds no role declaration to check"


# Where the role vocabulary must be current. Provenance is deliberately excluded:
# `references/` holds captured external material and `plans/` holds superseded
# design documents, and both may legitimately record what things were called at
# the time. They are history, not specification.
VOCABULARY_SURFACES = (
    "contracts", "shared", "scripts", "tests", "master-node",
    "peer-node/manifests", "peer-node/configs", "peer-node/services",
    "peer-node/scripts", "peer-node/tests", "peer-node/docs", "peer-node/skills",
)
SCAN_SUFFIXES = {".json", ".md", ".py", ".sh", ".template", ".conf", ""}


def test_nothing_in_the_repo_still_says_worker():
    """`worker` was the pre-split name for the peer role.

    It must survive nowhere that a reader treats as current. A stale reference
    is how someone concludes there is a third role, or greps for a role the
    contract does not define.
    """
    offenders = []
    for surface in VOCABULARY_SURFACES:
        root = REPO_ROOT / surface
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            if {"__pycache__", ".pytest_cache", ".ruff_cache"} & set(path.parts):
                continue
            # This file names the old vocabulary on purpose, to search for it.
            if path.resolve() == Path(__file__).resolve():
                continue
            try:
                text = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            for match in re.finditer(r"\bworkers?\b", text, re.I):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}")
    assert not offenders, f"the pre-split 'worker' vocabulary survives at: {offenders}"


def test_master_documents_the_manifest_gap_instead_of_hiding_it():
    """No master identity manifest exists yet, and that is deliberate.

    A Master manifest needs a real signing key. Shipping one with a placeholder
    key would look authoritative and authorise nothing, so the directory is
    absent until build plan Step 1 — and the charter must say so rather than
    listing a `manifests/` row as though it were there.
    """
    manifests = MASTER / "manifests"
    if manifests.exists():
        pytest.skip("master-node/manifests exists — Step 1 may have landed")
    charter = (MASTER / "AGENTS.md").read_text()
    row = next((ln for ln in charter.splitlines() if "`manifests/`" in ln), None)
    assert row is not None, "the charter no longer mentions manifests/ at all"
    assert re.search(r"not present yet|does not exist|arrives with", row, re.I), (
        f"the charter lists `manifests/` as if it exists, but the directory is "
        f"absent: {row!r}"
    )


# --- prose cannot drift into claiming things work ------------------------------


def test_guard_protocol_states_the_master_side_is_unbuilt():
    """Otherwise the document reads as though approvals are issuable today."""
    text = (CONTRACTS / "guard-protocol.md").read_text()
    assert re.search(
        r"does not exist yet|not yet built|unbuilt|not built", text, re.I
    ), "guard-protocol.md must say the Master side does not exist yet"


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
    for name in ("overlay.json", "capabilities.json", "identity-schema.json",
                 "ports.json", "guard-protocol.md"):
        assert name in readme, f"contracts/README.md does not mention {name}"


def test_shared_readme_says_never_copy_the_implementation():
    """Copying it is the exact failure the parent tests guard against."""
    text = (REPO_ROOT / "shared" / "README.md").read_text()
    assert re.search(r"never copy|do not copy|must not be copied|single implementation|only copy",
                     text, re.I), (
        "shared/README.md must tell a reader not to copy sparknet-authz.py into a role"
    )

# --- golden vectors -----------------------------------------------------------
#
# Everything above checks that the contract and the code agree on *which fields*
# participate. That still passes if both are changed together: someone could add
# a field to identity_fields, serialise it the same careless way in both places,
# and ship a change that alters every node's fingerprint with nothing red. Only a
# pinned expected value catches that, so the exact bytes are fixed here.
#
# These cover the keyless deterministic outputs. Signing itself needs a keypair,
# and pinning a private key in a repo is the one thing this file must never do.

#: An identity with deliberate operational noise mixed in.
GOLDEN_IDENTITY = {
    "node_id": "peer-fixture-01",
    "role": "peer",
    "wireguard_public_key_b64": "ZmFrZS13Z2lwdW5pY21hcHViaWMta2V5LWZvci10ZXN0cw==",
    "overlay_ipv4": "10.77.0.11/32",
    "requested_capabilities": ["dispatch-bridge", "guard-verify"],
    # Metadata a node's operator might set. None of it may reach the fingerprint,
    # or two otherwise-identical nodes would stop matching.
    "agent_endpoint": "https://peer-fixture-01.invalid:8443",
    "last_seen": "2026-10-04T00:00:00Z",
}

GOLDEN_CANONICAL_BYTES = (
    b'{"node_id":"peer-fixture-01","overlay_ipv4":"10.77.0.11/32",'
    b'"requested_capabilities":["dispatch-bridge","guard-verify"],"role":"peer",'
    b'"wireguard_public_key_b64":"ZmFrZS13Z2lwdW5pY21hcHViaWMta2V5LWZvci10ZXN0cw=="}'
)

GOLDEN_FINGERPRINT = "140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7"

GOLDEN_AUTHORIZATION_MESSAGE = (
    b'{"capabilities":["dispatch-bridge","guard-verify"],'
    b'"expires_at":1893456000,'
    b'"fingerprint":"140e0dc554e18b883922bd5164f576eee0c1d6d08ebf5f7d3c052948257c36c7",'
    b'"identity":{"node_id":"peer-fixture-01","overlay_ipv4":"10.77.0.11/32",'
    b'"requested_capabilities":["dispatch-bridge","guard-verify"],"role":"peer",'
    b'"wireguard_public_key_b64":"ZmFrZS13Z2lwdW5pY21hcHViaWMta2V5LWZvci10ZXN0cw=="},'
    b'"issued_at":1760000000,"overlay_ipv4":"10.77.0.11","revoked":false}'
)


def test_golden_canonical_bytes(authz: ModuleType):
    """Fields sorted, tight separators, UTF-8 — exactly as the schema declares."""
    assert authz.canonical_bytes(GOLDEN_IDENTITY) == GOLDEN_CANONICAL_BYTES, (
        "canonical identity bytes changed. Every node fingerprint changes with "
        "them. If this is intentional it is a contract break, not a refactor: "
        "bump identity-schema.json's schema_version and re-issue the registry."
    )


def test_golden_fingerprint(authz: ModuleType):
    assert authz.fingerprint(GOLDEN_IDENTITY) == GOLDEN_FINGERPRINT, (
        "fingerprint of the golden identity changed — see the canonical-bytes "
        "vector for why this is not a small change"
    )


def test_golden_authorization_message(authz: ModuleType):
    """The signature scope, pinned.

    This is what the Master actually signs, so a field added or dropped here
    changes what an existing signature covers. Silently reordering the envelope
    would be a break even though every signature still verifies locally.
    """
    entry = {
        "fingerprint": GOLDEN_FINGERPRINT,
        "identity": GOLDEN_IDENTITY,
        "capabilities": ["guard-verify", "dispatch-bridge"],
        "overlay_ipv4": "10.77.0.11",
        "issued_at": 1760000000,
        "expires_at": 1893456000,
        "revoked": False,
    }
    assert authz.authorization_message(entry) == GOLDEN_AUTHORIZATION_MESSAGE, (
        "the bytes the Master signs changed shape — see above"
    )


def test_projection_drops_operational_metadata(authz: ModuleType):
    projected = authz.canonical_identity(GOLDEN_IDENTITY)
    for noise in ("agent_endpoint", "last_seen"):
        assert noise not in projected, (
            f"{noise} leaked into the identity projection, so an operator could "
            f"change a node's fingerprint by editing metadata"
        )
    assert set(projected) == set(load("identity-schema.json")["identity_fields"])


def test_capability_order_asymmetry_is_intentional(authz: ModuleType):
    """Two orderings that behave differently, on purpose.

    `requested_capabilities` (inside the identity) is NOT sorted, so reordering
    it yields a different fingerprint. Granted `capabilities` (inside the signed
    envelope) IS sorted, so reordering it does not. That looks like an oversight
    and is not:

    - the fingerprint must cover what the node *asked for*, or a node could
      re-order its own request to change its identity;
    - the granted set is a set, so the signature should not depend on the order
      the registry happened to be written in.

    The failure mode if someone "tidies" the unsorted list: every existing node
    fingerprint changes, every registry entry stops matching, and no local test
    fails. This test is the guard for that edit.
    """
    reordered = dict(GOLDEN_IDENTITY,
                     requested_capabilities=["guard-verify", "dispatch-bridge"])
    assert authz.fingerprint(reordered) != GOLDEN_FINGERPRINT, (
        "requested_capabilities became order-insensitive. If that was intended, "
        "it invalidates every issued fingerprint and is a contract break."
    )

    base = {"fingerprint": GOLDEN_FINGERPRINT, "identity": GOLDEN_IDENTITY,
            "issued_at": 1760000000, "expires_at": 1893456000}
    a = dict(base, capabilities=["dispatch-bridge", "guard-verify"])
    b = dict(base, capabilities=["guard-verify", "dispatch-bridge"])
    assert authz.authorization_message(a) == authz.authorization_message(b), (
        "granted capabilities became order-sensitive, so rewriting the registry "
        "with the same set in a different order invalidates the Master's signature"
    )
