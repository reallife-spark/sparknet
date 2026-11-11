"""shared implementation"""

from __future__ import annotations

from types import ModuleType

from contract_helpers import (
    MASTER,
    PEER,
    REPO_ROOT,
    SHARED_PATH,
    load,
)

SUBMODULE_DIRS = {"gospark", "peer-node", "master-node", "goagx"}


def test_only_one_authz_implementation_exists():
    """A second copy would let the two roles diverge while both still pass."""
    copies = [
        p
        for p in REPO_ROOT.rglob("sparknet-authz.py")
        if not {"__pycache__", "dist", ".venv", ".git"} & set(p.parts) and not SUBMODULE_DIRS & set(p.parts)
    ]
    assert copies == [SHARED_PATH], f"expected one authz implementation, found: {copies}"


def test_only_one_shared_loader_exists():
    """The by-path loader is the same failure class as the authz copy.

    A second loader would not break crypto, but it is the same drift: seven
    modules each carrying their own resolve-and-cache loop drift apart, and a
    fix to one (a search path, a sys.modules guard) silently misses the rest.
    There is exactly one ``shared/sparknet_loader.py``, and no other shared
    module reimplements it with ``spec_from_file_location``.
    """
    loaders = [
        p
        for p in REPO_ROOT.rglob("sparknet_loader.py")
        if not {"__pycache__", "dist", ".venv", ".git"} & set(p.parts) and not SUBMODULE_DIRS & set(p.parts)
    ]
    loader_path = REPO_ROOT / "shared" / "sparknet_loader.py"
    assert loaders == [loader_path], f"expected one shared loader, found: {loaders}"

    offenders = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in (REPO_ROOT / "shared").glob("sparknet-*.py")
        if "spec_from_file_location" in p.read_text()
    ]
    assert offenders == [], f"shared modules reimplement the loader: {offenders}"


def test_shared_modules_share_one_loader_bootstrap():
    """Every shared module loads the loader through the same two-line idiom.

    ``shared/`` is not on ``sys.path``, so a by-path module cannot simply
    ``import sparknet_loader``; it adds its own directory first. That bootstrap
    cannot itself be delegated, so instead of a second copy it is pinned
    identical everywhere — a module that wired it differently would be a
    silent divergence in how the one implementation is found.
    """
    bootstrap = "sys.path.insert(0, str(Path(__file__).resolve().parent))\nfrom sparknet_loader import"
    modules = [
        p
        for p in sorted((REPO_ROOT / "shared").glob("sparknet-*.py"))
        if "from sparknet_loader import" in p.read_text()
    ]
    assert modules, "no shared module imports the one loader"
    missing = [p.name for p in modules if bootstrap not in p.read_text()]
    assert missing == [], f"shared modules without the shared-loader bootstrap: {missing}"


def test_shared_constants_match_the_contract(authz: ModuleType, capabilities: dict, identity_schema: dict):
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
    assert identity_schema["schema_version"] == authz.SCHEMA_VERSION


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


def test_admin_supervise_is_adopted_cross_role(authz: ModuleType, capabilities: dict):
    """Admin supervision is a Master capability and inert until granted.

    `admin-supervise` is what the signed `/admin/*` route checks for. Its
    holder is the Master — a peer can never sign an admin request — and a node
    only honours one once its own registry entry carries the capability, which
    in practice means a signed grant from the Master. Until then the route must
    answer `capability_missing`, not execute.
    """
    assert "admin-supervise" in authz.KNOWN_CAPABILITIES, "the shared signing grammar no longer knows admin-supervise"
    assert "admin-supervise" in capabilities["known_capabilities"], (
        "contracts/capabilities.json no longer lists admin-supervise"
    )
    definition = capabilities["definitions"]["admin-supervise"]
    assert definition["holder"] == "master", "admin-supervise must be a Master-held capability; peers never sign it"
    assert definition["sensitive"] is True
    assert set(authz.ADMIN_REQUEST_ACTIONS), "the admin action vocabulary may not be empty"
    assert "set_user_role" in authz.ADMIN_REQUEST_ACTIONS
    assert "list_events" in authz.ADMIN_REQUEST_ACTIONS, (
        "the console's event feed reads a node's spool through the signed route, "
        "so list_events must be in the closed action vocabulary"
    )
    assert set(authz.ADMIN_REQUEST_REQUIRED) <= set(authz.ADMIN_REQUEST_FIELDS), (
        "an admin-request field is required but not projected"
    )


def test_sandbox_supervise_is_adopted_cross_role(authz: ModuleType, capabilities: dict):
    """Execution-sandbox supervision is a Master capability and inert until granted.

    `sandbox-supervise` is reserved for the `/sandbox/*` route. Its holder is
    the Master — a peer never signs a sandbox request — and the action
    vocabulary, signed projection and required fields must agree between the
    shared grammar and `contracts/sandbox-schema.json`.
    """
    assert "sandbox-supervise" in authz.KNOWN_CAPABILITIES
    assert "sandbox-supervise" in capabilities["known_capabilities"]
    definition = capabilities["definitions"]["sandbox-supervise"]
    assert definition["holder"] == "master", "sandbox-supervise must be Master-held; peers never sign it"
    assert definition["sensitive"] is True
    schema = load("sandbox-schema.json")
    assert tuple(authz.SANDBOX_REQUEST_ACTIONS) == tuple(schema["request"]["actions"])
    assert set(authz.SANDBOX_REQUEST_FIELDS) == set(schema["request"]["fields"])
    assert set(authz.SANDBOX_REQUEST_FIELDS) == set(schema["request"]["signed_fields"])
    assert set(authz.SANDBOX_REQUEST_REQUIRED) <= set(authz.SANDBOX_REQUEST_FIELDS), (
        "a sandbox-request field is required but not projected"
    )
    assert set(schema["refusal_codes"]) >= {"bad-signature", "capability_missing", "mount-refused", "uid-zero"}


def test_sandbox_contract_is_driver_neutral_and_the_route_is_not_claimed(capabilities: dict, ports: dict) -> None:
    schema = load("sandbox-schema.json")
    assert set(schema["identity"]["drivers"]) == {"docker-rootful", "vm"}
    assert "vm" not in schema["identity"]["excluded_drivers"]
    assert schema["identity"]["uid_min"] == 1
    assert schema["identity"]["uid_max"] == 4294967294
    assert "not implemented" in schema["implementation"].lower()
    note = capabilities["definitions"]["sandbox-supervise"]["note"].lower()
    assert "no `/sandbox/*` route" in note or "no /sandbox/*" in note
    bridge = (PEER / "services" / "sparknet-dispatch-bridge.py").read_text()
    assert "/sandbox/" not in bridge, (
        "the bridge grew a /sandbox/ handler; the contract truth test must be updated with 20E"
    )
    assert "17670" in ports["ports"]
    assert ports["ports"]["17670"]["service"] == "openshell-gateway"
    assert "11501" in ports["ports"] and "14201" in ports["ports"]
    route_note = ports["ports"]["4096"]["note"].lower()
    assert "no handler" in route_note and "not overlay-reachable" in route_note


def test_signed_envelope_covers_everything_that_grants_power(identity_schema: dict):
    """`capabilities` and `revoked` must be inside the signature.

    Signing only the identity would leave `capabilities` editable by anyone who
    can write the registry file — escalating a peer to guard-apply without the
    Master approving it. `revoked` is inside for the converse reason: an attacker
    with registry write access may deny service, never reinstate it.
    """
    signed = set(identity_schema["signed_envelope_fields"])
    for required in ("fingerprint", "identity", "capabilities", "overlay_ipv4", "issued_at", "expires_at", "revoked"):
        assert required in signed, (
            f"{required} is outside the signed envelope, so it is mutable by anyone who can edit the registry"
        )


def test_registry_entry_acceptance_has_one_seam():
    """The five remote-entry surfaces must call the shared acceptance rule.

    A second copy is how the intake, scheduler, RFI responder, uplift intake and
    liveness roster drifted on check order, clock skew and identity. This source
    scan is deliberately narrow: it looks for the shared call and for the old
    direct signature-over-entry idiom, not for every use of authz.
    """
    surfaces = [
        PEER / "services" / "sparknet-liveness-monitor.py",
        MASTER / "services" / "sparknet-peer-intake.py",
        MASTER / "services" / "sparknet-scheduler.py",
        MASTER / "services" / "sparknet-rfi-responder.py",
        MASTER / "services" / "sparknet-uplift-intake.py",
    ]
    for path in surfaces:
        text = path.read_text(encoding="utf-8")
        assert "accept_entry(" in text, f"{path.relative_to(REPO_ROOT)} does not call the shared acceptance seam"
        assert "authorization_message(entry)" not in text, (
            f"{path.relative_to(REPO_ROOT)} still verifies a registry entry directly"
        )
