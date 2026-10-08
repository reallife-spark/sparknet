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
    assert guard["implementation_state"] == "implemented"
    assert "own overlay address" in guard["binds_to"], (
        "the guard must bind its own overlay address, never a wildcard"
    )


PORT_STATES = {"implemented", "provisioned", "spec-only"}
PORT_RUNTIME = {"running", "not-listening", "not-verifiable-here"}


def test_every_port_declares_both_axes_with_known_values(ports: dict):
    """implementation_state and runtime answer different questions.

    Collapsing them into one boolean is what let a 110-line CLI be described as
    implemented, so both axes are now mandatory and enumerated.
    """
    for number, spec in ports["ports"].items():
        assert spec.get("implementation_state") in PORT_STATES, (
            f"port {number} ({spec['service']}) has an unknown or missing "
            f"implementation_state: {spec.get('implementation_state')!r}"
        )
        assert spec.get("runtime") in PORT_RUNTIME, (
            f"port {number} ({spec['service']}) has an unknown or missing "
            f"runtime: {spec.get('runtime')!r}"
        )


def test_the_conflated_boolean_is_gone(ports: dict):
    """`implemented: true` is exactly the claim that was false. Do not restore it."""
    for number, spec in ports["ports"].items():
        assert "implemented" not in spec, (
            f"port {number} still uses the boolean 'implemented'; use "
            f"implementation_state plus runtime"
        )


def test_running_requires_an_observed_listener(ports: dict):
    """A port may only claim `running` if it actually accepts a connection here.

    This is the test that would have caught 4096, 4097, 4098 and 4100 being
    called implemented while nothing was listening. It is deliberately narrow:
    overlay services whose interface is absent here are `not-verifiable-here`
    and are exempt, because their absence is not evidence of a fault.
    """
    import socket

    for number, spec in ports["ports"].items():
        if spec.get("runtime") != "running":
            continue
        sock = socket.socket()
        sock.settimeout(1.0)
        try:
            sock.connect(("127.0.0.1", int(number)))
        except OSError as exc:
            pytest.fail(
                f"port {number} ({spec['service']}) claims runtime=running but "
                f"nothing accepted a loopback connection: {exc}"
            )
        finally:
            sock.close()


def test_a_service_marked_implemented_must_name_a_bind_path(ports: dict):
    """`implemented` is a claim about a bind, so the evidence must be on record.

    The inverse is the part that bit us: `implemented: true` on a file with no
    bind code anywhere. Any port asserting `implemented` must therefore either
    carry runtime evidence or say in runtime_why why it could not be observed.
    """
    for number, spec in ports["ports"].items():
        if spec.get("implementation_state") != "implemented":
            continue
        assert spec.get("runtime_why") or spec.get("runtime") == "running", (
            f"port {number} ({spec['service']}) claims implementation_state="
            f"implemented with neither a running listener nor a recorded reason "
            f"it could not be observed"
        )


def test_ports_that_are_not_implemented_say_so_and_point_at_a_real_plan(ports: dict):
    """An unimplemented port must be flagged, not merely absent from code."""
    for number, spec in ports["ports"].items():
        if spec["implementation_state"] == "implemented":
            continue
        status = spec.get("status", "")
        assert re.search(r"SPEC ONLY|provisioned|PROVISIONED|no listener", status, re.I), (
            f"port {number} ({spec['service']}) is {spec['implementation_state']} "
            f"but its status does not say so: {status!r}"
        )
        referenced = re.findall(
            r"((?:\.\./)?peer-node/PLAN\.md|master-node/plans/MASTER_BUILD_PLAN\.md|master-node/plans/MASTER_ADMIN_PLAN\.md)",
            status,
        )
        assert referenced, (
            f"port {number} must point at the plan step that will build it"
        )
        for ref in referenced:
            resolved = (REPO_ROOT / ref).resolve()
            assert resolved.is_file(), (
                f"port {number} points at {ref}, which does not resolve to a file "
                f"from the repo root: {resolved}"
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


@pytest.mark.parametrize("role_dir", [PEER, MASTER], ids=["peer-node", "master-node"])
def test_a_node_declares_itself_peer_until_it_is_elected(role_dir: Path):
    """No deployment site may assert `role: master`.

    This replaced an assertion that `master-node/` must declare `role: master`,
    which encoded the pre-election model where the Master was a separate species
    with its own identity. Under the elected model a Master *is* a peer that won a
    unanimous election, so the honest manifest for a master-capable node says
    `peer` and carries no claim to authority.

    The direction matters: a node that claimed `master` because of where it was
    installed would be a node asserting authority it has not been granted, and
    the trust root is what grants it. Prose cannot confer it, and neither can the
    directory a bundle was extracted into.
    """
    manifests = role_dir / "manifests"
    if not manifests.is_dir():
        pytest.skip(f"{role_dir.name}/manifests does not exist")
    checked = 0
    for path in sorted(manifests.glob("*.json")):
        data = json.loads(path.read_text())
        if "role" in data:
            assert data["role"] == "peer", (
                f"{role_dir.name}/{path.name} claims {data['role']!r}. Authority "
                f"comes from a signed cluster trust root, not from deployment."
            )
            checked += 1
    assert checked, f"{role_dir.name}/manifests holds no role declaration to check"


def test_a_master_capable_node_is_eligible_and_claims_no_key():
    """The pre-election state must be explicit, not merely implied by the role.

    Fail-closed is the whole property: until a unanimous cluster trust root has
    been signed (every member of the pair or trio), this node must be recorded
    as eligible but unkeyed. A manifest
    that quietly carried an operational key, or omitted the election block, would
    let a freshly provisioned node be treated as if it already had authority.
    """
    path = MASTER / "manifests" / "node-identity.json"
    assert path.is_file(), "master-node/manifests/node-identity.json is missing"
    data = json.loads(path.read_text())

    election = data.get("election")
    assert isinstance(election, dict), "node-identity.json must state its election state"
    assert election.get("eligible") is True, (
        "a node deployed from master-node/ is master-eligible by definition"
    )
    assert election.get("elects_itself") is False, (
        "a node may vote for itself but must not be able to install itself"
    )

    operational = data.get("operational_key")
    assert isinstance(operational, dict), "node-identity.json must state its key state"
    assert operational.get("held") is False, (
        "the template must not claim the operational key; only a signed trust "
        "root confers it"
    )

    assert "cluster_pubkey_b64" in data, (
        "the node's cluster public key is what goes into the trust root and must "
        "have a slot here, even if unset"
    )


def test_no_role_manifest_asserts_current_master_state():
    """Nothing in a *template* may claim the node is already Master.

    Master state is runtime — it lives in the registry the operational key signs,
    not in a file shipped with a bundle.
    """
    for role_dir in (PEER, MASTER):
        manifests = role_dir / "manifests"
        if not manifests.is_dir():
            continue
        for path in sorted(manifests.glob("*.json")):
            text = path.read_text().lower()
            assert '"master": true' not in text, (
                f"{role_dir.name}/{path.name} asserts it is master; that state is "
                f"runtime and must come from a signed registry entry"
            )
            assert '"elected": true' not in text, (
                f"{role_dir.name}/{path.name} asserts an election it has not run"
            )


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
            # Plans are provenance: they may record what things were called at
            # the time (see the VOCABULARY_SURFACES comment above).
            if "plans" in set(path.parts):
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
                 "ports.json", "guard-protocol.md", "share-protocol.md",
                 "consensus-protocol.md", "tracking-schema.json",
                 "provenance-protocol.md"):
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


# --- share protocol ------------------------------------------------------------


def share_policy() -> dict:
    return load("capabilities.json")


def test_share_protocol_says_nothing_there_is_built(ports: dict):
    """Same honesty guard as guard-protocol.md: no built side is implied."""
    text = (CONTRACTS / "share-protocol.md").read_text()
    assert re.search(r"not built|Nothing here is built|does not exist", text, re.I), (
        "share-protocol.md must say plainly that no side is implemented yet"
    )


def test_share_protocol_states_every_element_the_regime_needs(ports: dict):
    text = (CONTRACTS / "share-protocol.md").read_text().lower()
    for element in ("invite", "accept", "share type", "clock", "trust level",
                    "isolat", "evidence"):
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
            f"{name} is {duration!r} in capabilities.json, which is neither "
            f"spelling share-protocol.md is checked for"
        )
        assert any(s in text for s in spellings), (
            f"share-protocol.md never states the {name} duration {duration!r}"
        )


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
    assert set(types["types"]["full"]["includes"]) == {
        n for n in types["types"] if n != "full"
    }, "full must be exactly the union of the other share types"


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
        assert overlay["governance_mode"]["modes"][name].get("rule"), (
            f"governance mode {name} has no rule"
        )


def test_ratified_shares_retain_their_flag(ports: dict):
    """Approval must not erase the fact that unapproved data crossed nodes."""
    trust = share_policy()["trust_levels"]
    assert trust["retained_after_ratification"] is True
    assert "retained_rationale" in trust
    text = (CONTRACTS / "share-protocol.md").read_text().lower()
    assert "retain" in text, (
        "share-protocol.md must state that the flag survives ratification"
    )
    assert "never a permission" in trust["never_a_grant"] or \
        "never grants authority" in trust["never_a_grant"]


def test_a_trust_level_can_never_be_a_grant(ports: dict):
    trust = share_policy()["trust_levels"]
    for level, spec in trust["levels"].items():
        assert spec.get("means"), f"trust level {level} does not define itself"
        assert "shares_allowed" in spec, (
            f"trust level {level} does not say whether shares are permitted"
        )
    assert trust["never_a_grant"], "trust levels must be declared belief, not permission"
    assert "registry" in trust["who_moves_them"], (
        "only the Master may move trust levels, via the signed registry"
    )


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
    assert grant["fields"]["nonce"]["retention"], (
        "a nonce needs a stated retention or the replay window opens silently"
    )
    assert grant["fields"]["parent_grant_id"], (
        "delegation must be representable, since subagents inherit grants"
    )


def test_share_endpoints_are_declared_and_separate(ports: dict):
    """Passing and sharing need independent grants, so they cannot share a port."""
    declared = {spec["service"]: int(n) for n, spec in ports["ports"].items()}
    for service in ("share-intake", "session-transfer", "share-ratification",
                    "opencode-serve"):
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
    """Anything unbuilt must say so, in both the schema and the prose."""
    for number, spec in ports["ports"].items():
        if spec["service"] in ("share-intake", "session-transfer",
                               "share-ratification", "opencode-serve"):
            assert spec["implementation_state"] == "spec-only", (
                f"port {number} ({spec['service']}) must stay spec-only until built"
            )
            assert spec["runtime"] == "not-listening"
            assert spec.get("status"), f"port {number} must say what is there"


# --- consensus protocol --------------------------------------------------------


def test_guard_protocol_no_longer_claims_a_peer_can_never_sign_as_a_fact(ports: dict):
    """A peer contains the signing code; what denies it is state, not structure.

    The old sentence was true when the two roles were different programs. It is
    false now that a master is a peer that won an election, and a reader trusting
    it would look for the guarantee in the wrong place.
    """
    text = (CONTRACTS / "guard-protocol.md").read_text()
    assert not re.search(
        r"A peer can \*\*verify\*\* an approval but never \*\*produce\*\* one", text
    ), (
        "guard-protocol.md still states the asymmetry as a structural fact; it is "
        "a role state under the election model"
    )
    assert re.search(r"role state, not a structure", text), (
        "guard-protocol.md must say where the asymmetry now lives"
    )
    assert "consensus-protocol.md" in text, (
        "guard-protocol.md must point at the protocol that now decides who may sign"
    )


def test_consensus_protocol_states_the_whole_agreement(ports: dict):
    text = (CONTRACTS / "consensus-protocol.md").read_text().lower()
    for element in ("membership", "election", "unanim", "trust root", "re-formation",
                    "cluster key"):
        assert element in text, f"consensus-protocol.md never covers {element!r}"


def test_the_trust_root_replaces_the_single_key_model(ports: dict):
    schema = load("identity-schema.json")
    root = schema["cluster_trust_root"]
    assert "replaces" in root and "master_public_key" in root["replaces"], (
        "the root must state what it supersedes, or the old single-key model "
        "stays readable as though it were current"
    )
    assert root["members"]["min"] == 2, (
        "a pair is the smallest cluster that still refuses self-elevation"
    )
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
    assert "master_pubkey" in rules, (
        "the registry must be checked against the operational key the root names"
    )


def test_replace_requires_unanimity_but_revoke_does_not(ports: dict):
    table = load("identity-schema.json")["cluster_trust_root"]["threshold_table"]
    assert table["replace_master"].startswith("n of n"), (
        "changing who holds authority must not be unilateral"
    )
    assert table["revoke_node"].startswith("1"), (
        "revocation is a safe denial and must stay unilateral, or a dead master "
        "would brick the fabric"
    )


def test_reformation_is_not_a_bypass(ports: dict):
    reformation = load("identity-schema.json")["cluster_trust_root"]["reformation"]
    assert reformation.get("not_a_bypass"), (
        "re-formation must state it cannot install a master without unanimity "
        "among the members it names, or it is a back door around the election"
    )
    assert "new root" in reformation["on_master_change"], (
        "a master change must be a new root with a different nonce, so the old "
        "operational key stops being recognised"
    )


def test_election_vote_is_a_say_not_a_grant(ports: dict):
    caps = share_policy()
    assert "cluster-vote" in caps["known_capabilities"]
    vote = caps["definitions"]["cluster-vote"]
    assert vote["holder"] == "peer", (
        "every member holds a vote, because election is what makes a master at all"
    )
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
        "implemented but not running is the honest pair on this host: the code "
        "exists, nothing here binds 4210"
    )
    assert election["overlay_only"] is True
    assert "never a registry entry" in election["note"], (
        "the election port must be explicit that it does not carry authority, "
        "since it decides who holds the key"
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


# --- provenance: the accountability contract and its one implementation -------


@pytest.fixture(scope="module")
def tracking() -> dict:
    return load("tracking-schema.json")


@pytest.fixture(scope="module")
def provenance() -> ModuleType:
    """shared/sparknet-provenance.py, loaded by path for the reason authz is.

    Loading by path is what proves the tool reads `contracts/` rather than
    carrying a private copy of its rules; an import would let a stale
    installed copy satisfy the assertions below.
    """
    spec = importlib.util.spec_from_file_location(
        "sparknet_provenance", REPO_ROOT / "shared" / "sparknet-provenance.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.fixture(scope="module")
def master_ledger() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "sparknet_ledger_master", MASTER / "services" / "sparknet-ledger.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


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
    assert list(master_ledger.REQUIRED_FIELDS) == required, (
        "master-node's REQUIRED_FIELDS drifted from contracts/"
    )
    assert provenance.contract()["ledger_block"]["required"] == required, (
        "shared/sparknet-provenance.py read a different contract"
    )


def test_the_event_vocabularies_are_disjoint(tracking: dict, master_ledger: ModuleType):
    """A peer must not be able to record what only the Master can observe."""
    peer = set(tracking["approval"]["event_vocabulary"]["peer"])
    master = set(tracking["approval"]["event_vocabulary"]["master"])
    assert peer and master, "both vocabularies must be non-empty"
    assert not (peer & master), f"an event appears in both vocabularies: {sorted(peer & master)}"
    assert set(master_ledger.MASTER_EVENTS) == master, (
        "master-node's MASTER_EVENTS drifted from contracts/"
    )
    assert "approval" in peer and "share" in peer and "share_ratified" in master


def test_the_note_message_is_built_the_way_the_contract_spells_it(tracking: dict, provenance: ModuleType):
    hashes = {"body": "ab" * 32, "meta": "cd" * 32, "tracking": "ef" * 32}
    expected = (
        b"sparknet-note/1\n"
        + hashes["body"].encode("ascii") + b"\n"
        + hashes["meta"].encode("ascii") + b"\n"
        + hashes["tracking"].encode("ascii")
    )
    assert provenance.note_message(hashes) == expected
    message = tracking["signature"]["message"]
    assert "sparknet-note/1" in message
    for part in ("body_sha256_hex", "meta_sha256_hex", "tracking_sha256_hex"):
        assert part in message, f"the contract no longer describes {part} in the signed message"


def test_the_compiled_rules_are_read_from_the_contract_at_runtime(provenance: ModuleType, tracking: dict):
    """The allowlist must not be restated in code — a restated rule goes stale."""
    source = (REPO_ROOT / "shared" / "sparknet-provenance.py").read_text()
    for lookup in (
        'contract()["signature"]["compiler_allowlist"]',
        'contract()["ledger_block"]["required"]',
        'contract()["approval"]["event_vocabulary"]["peer"]',
    ):
        assert lookup in source, f"shared/sparknet-provenance.py no longer reads {lookup}"
    assert tracking["signature"]["compiler_allowlist"], "the allowlist may not be empty"
    assert "updated" in tracking["signature"]["compiler_allowlist"]


def test_the_phase_boundary_says_the_transport_does_not_exist(tracking: dict):
    """Nothing here may imply delivery works; ports.json is what says otherwise."""
    boundary = tracking["phase_boundary"]
    assert boundary["state"] == "specified, not built"
    built = " ".join(boundary["built_here"])
    not_built = " ".join(boundary["not_built"])
    assert "email" in not_built and "transport" not in built
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


def test_the_user_record_allowlist_is_the_contract_fields(
    tracking: dict, provenance: ModuleType
):
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
        assert not pattern.search(shipped.decode("utf-8", "replace")), (
            f"shipped user record: {label}"
        )


def test_the_system_files_point_at_the_contract_instead_of_restating_it(
    tracking: dict, provenance: ModuleType
):
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
