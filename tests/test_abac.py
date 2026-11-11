"""ABAC is a narrowing decision, never an authority grant.

These tests pin the three boundaries the module exists for: signed attributes
only, fail-closed classification, and scope that narrows but never widens.
"""

from __future__ import annotations

import base64
import json

import pytest
from contract_helpers import REPO_ROOT, load
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit


ABAC_PATH = REPO_ROOT / "shared" / "sparknet-abac.py"
AUTHZ_PATH = REPO_ROOT / "shared" / "sparknet-authz.py"


def _load_abac():
    return load_by_path("sparknet_abac", ABAC_PATH)


abac = _load_abac()
DIGEST = "a" * 64
FUTURE = "2099-01-01T00:00:00Z"


def node(**overrides):
    subject = {
        "verified": True,
        "kind": "node",
        "id": "sparknet-node-0002",
        "vault_id": "peer-node",
        "role": "peer",
        "department": "blue",
        "capabilities": ["p2p-sync", "cluster-serve"],
        "scope": [],
        "expires_at": FUTURE,
    }
    subject.update(overrides)
    return subject


def user(**overrides):
    subject = {
        "verified": True,
        "kind": "user",
        "id": "user-1",
        "vault_id": "peer-user-1",
        "role": "user",
        "department": None,
        "capabilities": [],
        "scope": ["05_Knowledge/", "06_Projects/"],
        "expires_at": FUTURE,
    }
    subject.update(overrides)
    return subject


def page(**overrides):
    resource = {
        "vault_id": "peer-user-1",
        "path": "05_Knowledge/note.md",
        "class": "vault",
        "classification": "confidential",
        "department": None,
        "provenance": {"source": "01_Inbox/note.md", "digest": DIGEST},
    }
    resource.update(overrides)
    return resource


def test_contract_vocabularies_match_the_module():
    schema = load("abac-schema.json")
    assert tuple(schema["subject_kinds"]) == abac.SUBJECT_KINDS
    assert tuple(schema["resource_classes"]) == abac.RESOURCE_CLASSES
    assert tuple(schema["classifications"]) == abac.CLASSIFICATIONS
    assert tuple(schema["decision_fields"]) == abac.DECISION_FIELDS
    assert set(schema["refusal_codes"]) == set(abac.REFUSAL_CODES)
    assert {key: tuple(value) for key, value in schema["class_prefixes"].items()} == {
        key: tuple(value) for key, value in abac.CLASS_PREFIXES.items()
    }
    assert tuple(schema["personal_prefixes"]) == abac.PERSONAL_PREFIXES
    assert tuple(schema["personal_names"]) == abac.PERSONAL_NAMES
    assert {key: tuple(value) for key, value in schema["capability_map"].items()} == {
        key: tuple(value) for key, value in abac.CAPABILITY_MAP.items()
    }
    assert schema["ingestion"]["defaults_by_source"] == abac.INGEST_DEFAULTS
    assert schema["ingestion"]["minimum_by_source"] == abac.INGEST_MINIMUM
    assert schema["ingestion"]["legacy_path_fallback"] == {
        **abac.LEGACY_PATH_CLASSIFICATION,
        "default": abac.DEFAULT_LEGACY_CLASSIFICATION,
    }
    assert schema["schema_version"] == abac.SCHEMA_VERSION


def test_capability_map_uses_the_closed_vocabulary():
    capabilities = set(load("capabilities.json")["known_capabilities"])
    for names in abac.CAPABILITY_MAP.values():
        assert set(names) <= capabilities


def test_node_shared_public_page_is_allowed():
    # The class is set explicitly because the path alone cannot tell the caller's intent.
    resource = page(vault_id="shared", path="01_Inbox/share-7/a.md", classification="internal")
    resource["class"] = "shared"
    decision = abac.evaluate(node(), resource)
    assert decision["allowed"] is True
    assert decision["reason"] == "allowed"


def test_node_shared_page_without_p2p_sync_is_refused():
    resource = page(vault_id="shared", path="01_Inbox/share-7/a.md", classification="internal")
    resource["class"] = "shared"
    decision = abac.evaluate(node(capabilities=["cluster-serve"]), resource)
    assert decision["allowed"] is False
    assert decision["reason"] == "capability-missing"


def test_node_shared_confidential_page_is_refused():
    resource = page(vault_id="shared", path="01_Inbox/share-7/a.md", classification="confidential")
    resource["class"] = "shared"
    decision = abac.evaluate(node(), resource)
    assert decision["allowed"] is False
    assert decision["reason"] == "shared-corpus-forbidden"


def test_node_shared_personal_page_is_refused():
    resource = page(vault_id="shared", path="01_Inbox/share-7/00_System/secret.md", classification="public")
    resource["class"] = "shared"
    decision = abac.evaluate(node(), resource)
    assert decision["allowed"] is False
    assert decision["reason"] == "personal-page-in-shared"


def test_user_own_vault_page_is_allowed():
    decision = abac.evaluate(user(), page())
    assert decision["allowed"] is True
    assert decision["effective_scope"] == ["05_Knowledge/", "06_Projects/"]


def test_user_scope_widening_is_refused():
    decision = abac.evaluate(user(), page(path="02_Daily/note.md"))
    assert decision["allowed"] is False
    assert decision["reason"] == "scope-widening"


def test_user_cross_vault_page_is_refused():
    decision = abac.evaluate(user(), page(vault_id="peer-user-2"))
    assert decision["allowed"] is False
    assert decision["reason"] == "vault-mismatch"


def test_user_cannot_read_a_shared_corpus():
    resource = page(vault_id="shared", path="01_Inbox/share-7/a.md", classification="internal")
    resource["class"] = "shared"
    decision = abac.evaluate(user(), resource)
    assert decision["allowed"] is False
    assert decision["reason"] == "shared-corpus-forbidden"


def test_authority_surface_is_never_readable():
    resource = page(path="00_System/keys/identity.key", classification="restricted")
    resource["class"] = "authority"
    decision = abac.evaluate(node(), resource)
    assert decision["allowed"] is False
    assert decision["reason"] == "authority-surface"


def test_mislabeled_authority_path_is_refused():
    resource = page(path="00_System/keys/identity.key", classification="confidential", vault_id="peer-node")
    resource["class"] = "vault"
    decision = abac.evaluate(node(), resource)
    assert decision["allowed"] is False
    assert decision["reason"] == "authority-surface"


def test_shared_class_cannot_name_the_source_tree():
    resource = page(vault_id="shared", path="shared/sparknet-abac.py", classification="internal")
    resource["class"] = "shared"
    decision = abac.evaluate(node(), resource)
    assert decision["allowed"] is False
    assert decision["reason"] == "resource-class-mismatch"


def test_a_vault_label_cannot_hide_a_fabric_page():
    resource = page(path="contracts/knowledge-flow.md", classification="public")
    resource["class"] = "vault"
    decision = abac.evaluate(node(vault_id="peer-node"), resource)
    assert decision["allowed"] is False
    assert decision["reason"] == "resource-class-mismatch"


def test_department_boundary_requires_the_capability():
    resource = page(vault_id="shared", path="01_Inbox/share-7/a.md", classification="internal", department="red")
    resource["class"] = "shared"
    refused = abac.evaluate(node(), resource)
    assert refused["allowed"] is False
    assert refused["reason"] == "department-mismatch"
    allowed = abac.evaluate(node(capabilities=["p2p-sync", "cross-department-share"]), resource)
    assert allowed["allowed"] is True


def test_missing_and_unknown_classification_are_refused():
    missing = page()
    missing.pop("classification")
    assert abac.evaluate(user(), missing)["reason"] == "missing-classification"
    assert abac.evaluate(user(), page(classification="secret"))["reason"] == "unknown-classification"


def test_missing_provenance_is_refused():
    resource = page()
    resource.pop("provenance")
    assert abac.evaluate(user(), resource)["reason"] == "missing-provenance"
    resource = page(provenance={"source": "01_Inbox/note.md", "digest": "not-a-digest"})
    assert abac.evaluate(user(), resource)["reason"] == "missing-provenance"


def test_unverified_and_expired_subjects_are_refused():
    assert abac.evaluate(user(verified=False), page())["reason"] == "subject-unverified"
    assert abac.evaluate(user(expires_at="2000-01-01T00:00:00Z"), page())["reason"] == "subject-expired"


def test_requested_scope_must_narrow_never_widen():
    assert abac.evaluate(user(), page(), requested_scope=["05_Knowledge/"])["allowed"] is True
    assert abac.evaluate(user(), page(), requested_scope=["05_Knowledge/", "02_Daily/"])["reason"] == "scope-widening"
    assert abac.evaluate(user(), page(), requested_scope=[])["reason"] == "scope-widening"


def test_requested_scope_excludes_a_resource_outside_it():
    resource = page(path="06_Projects/secret.md")
    decision = abac.evaluate(user(), resource, requested_scope=["05_Knowledge/"])
    assert decision["allowed"] is False
    assert decision["reason"] == "scope-widening"


def test_decision_has_only_the_contract_fields():
    decision = abac.evaluate(user(), page())
    assert tuple(decision) == abac.DECISION_FIELDS
    assert "capabilities" not in decision
    assert "signature" not in decision


def test_decision_json_is_deterministic():
    first = abac.decision_json(abac.evaluate(user(), page()))
    second = abac.decision_json(abac.evaluate(user(), page()))
    assert first == second
    assert json.loads(first)["reason"] == "allowed"


def test_filter_resources_keeps_only_allowed_records():
    allowed = page(path="05_Knowledge/a.md")
    denied = page(path="02_Daily/b.md")
    kept = abac.filter_resources(user(), [allowed, denied])
    assert [row["resource"] for row in kept] == ["05_Knowledge/a.md"]


def test_path_traversal_is_refused():
    decision = abac.evaluate(user(), page(path="../peer-user-2/secret.md"))
    assert decision["allowed"] is False
    assert decision["reason"] == "resource-path-invalid"


def test_malformed_subject_returns_a_denial_not_an_exception():
    assert abac.evaluate(None, page())["reason"] == "subject-unverified"
    assert abac.evaluate(["not", "a", "mapping"], page())["reason"] == "subject-unverified"


def test_personal_names_are_never_shared():
    for path in ("MEMORY.md", ".env", "secrets-index.json", "02_Daily/note.md"):
        assert abac.is_personal(path) is True
    assert abac.is_personal("05_Knowledge/note.md") is False


def test_subject_projection_requires_verification_and_a_local_vault():
    with pytest.raises(abac.AbacError):
        abac.subject_from_registry({}, "peer-node")
    with pytest.raises(abac.AbacError):
        abac.subject_from_registry({"identity": {}}, "peer-node", verified=True)
    subject = abac.subject_from_registry(
        {
            "identity": {"node_id": "n", "role": "peer"},
            "capabilities": ["p2p-sync"],
        },
        "peer-node",
        verified=True,
    )
    assert subject["kind"] == "node"
    assert subject["vault_id"] == "peer-node"
    with pytest.raises(abac.AbacError):
        abac.subject_from_grant({"user_identity": "u", "vault_scope": []}, "peer-u")
    empty_scope = abac.subject_from_grant({"user_identity": "u", "vault_scope": []}, "peer-u", verified=True)
    assert empty_scope["scope"] == []


def test_subject_projection_uses_real_authz_records():
    authz = load_by_path("sparknet_authz_for_abac", AUTHZ_PATH)

    key = Ed25519PrivateKey.generate()
    public_b64 = base64.b64encode(
        key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ).decode("ascii")
    identity = {
        "node_id": "sparknet-node-0002",
        "role": "peer",
        "wireguard_public_key_b64": public_b64,
        "overlay_ipv4": "10.100.0.2",
        "requested_capabilities": ["p2p-sync"],
    }
    entry = authz.sign_authorization(identity, key, ["p2p-sync"], department="blue")
    node_subject = abac.subject_from_registry(entry, "peer-node", verified=True)
    assert node_subject["id"] == "sparknet-node-0002"
    assert node_subject["department"] == "blue"

    grant = authz.mint_grant(
        node_identity=identity,
        grant_id="grant-1",
        user_identity="user-1",
        conversation_key="conversation-1",
        capabilities=["p2p-sync"],
        vault_scope=["05_Knowledge/"],
        ttl_minutes=5,
        nonce="nonce-1",
        master_private_key=key,
    )
    user_subject = abac.subject_from_grant(grant, "peer-user-1", verified=True)
    assert user_subject["id"] == "user-1"
    assert user_subject["scope"] == ["05_Knowledge"]


def test_filter_resources_respects_the_requested_scope():
    kept = abac.filter_resources(
        user(),
        [page(path="05_Knowledge/a.md"), page(path="06_Projects/b.md")],
        requested_scope=["05_Knowledge/"],
    )
    assert [row["resource"] for row in kept] == ["05_Knowledge/a.md"]


def test_shared_requested_scope_narrows():
    resource = page(vault_id="shared", path="01_Inbox/share-7/a.md", classification="internal")
    resource["class"] = "shared"
    assert abac.evaluate(node(), resource, requested_scope=["01_Inbox/share-7/"])["allowed"] is True
    assert abac.evaluate(node(), resource, requested_scope=["01_Inbox/share-8/"])["reason"] == "scope-widening"


def test_fabric_requested_scope_narrows():
    resource = page(vault_id="fabric", path="contracts/knowledge-flow.md", classification="public")
    resource["class"] = "fabric"
    assert abac.evaluate(node(), resource, requested_scope=["contracts/"])["allowed"] is True
    assert abac.evaluate(node(), resource, requested_scope=["docs/"])["reason"] == "scope-widening"


def test_node_vault_folder_scope_is_allowed():
    resource = page(vault_id="peer-node", path="05_Knowledge/a.md")
    decision = abac.evaluate(node(), resource, requested_scope=["05_Knowledge/"])
    assert decision["allowed"] is True


def test_effective_scope_is_never_a_wildcard():
    decision = abac.evaluate(node(), page(vault_id="peer-node", path="05_Knowledge/a.md"))
    assert "*" not in decision["effective_scope"]
