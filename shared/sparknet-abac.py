#!/usr/bin/env python3
"""Attribute-based narrowing for knowledge resources.

ABAC answers one question: may a caller that already holds a signed identity
read this resource? It never verifies a signature, grants a capability or
widens a scope. A decision is evidence, not authority.

Subject attributes come from a verified registry entry or a signed session
grant. Resource attributes come from the ingestion classification record. A
caller-supplied label at query time is not an attribute. Missing or unknown
attributes are denied.

This module is deliberately standalone: it has no key, no network and no
filesystem write path. `sparknet-authz.py` remains the one signature
implementation; this module consumes its verified result.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

SCHEMA_VERSION = "1.0"
SUBJECT_KINDS = ("node", "user")
RESOURCE_CLASSES = ("shared", "fabric", "vault", "authority")
CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")
DECISION_FIELDS = (
    "allowed",
    "reason",
    "subject",
    "subject_kind",
    "resource",
    "vault_id",
    "classification",
    "effective_scope",
)
REFUSAL_CODES = (
    "allowed",
    "unknown-classification",
    "missing-classification",
    "missing-provenance",
    "subject-unverified",
    "subject-expired",
    "subject-kind-unknown",
    "resource-class-unknown",
    "resource-class-mismatch",
    "resource-path-invalid",
    "vault-mismatch",
    "scope-widening",
    "department-mismatch",
    "capability-missing",
    "shared-corpus-forbidden",
    "fabric-corpus-forbidden",
    "personal-page-in-shared",
    "authority-surface",
)
CAPABILITY_MAP = {
    "shared": ("p2p-sync",),
    "fabric": ("cluster-serve",),
    "cross_department": ("cross-department-share",),
}
#: The O1 ingestion defaults. The writer records one classification; a reader
#: never derives a lower one from the path. The path fallback exists only for
#: pages that predate the field and is deliberately conservative.
INGEST_DEFAULTS = {
    "master-node": "internal",
    "peer-node": "internal",
    "email": "confidential",
}
INGEST_MINIMUM = {
    "master-node": "internal",
    "peer-node": "internal",
    "email": "confidential",
}
LEGACY_PATH_CLASSIFICATION = {
    "02_Daily/": "confidential",
    "03_Sources/": "confidential",
    "_raw/": "confidential",
    "_staging/": "confidential",
}
DEFAULT_LEGACY_CLASSIFICATION = "internal"
CLASS_PREFIXES = {
    "shared": ("01_Inbox/share-",),
    "fabric": (
        "contracts/",
        "docs/",
        "AGENTS.md",
        "CONTEXT.md",
        "INTENT.md",
        "MISSION.md",
        "README.md",
    ),
    "authority": ("00_System/", "blockchain/", "manifests/", "keys/", ".state/"),
}
PERSONAL_PREFIXES = (
    "00_System/",
    "02_Daily/",
    "03_Sources/",
    "sessions/",
    "_raw/",
    "_staging/",
    "blockchain/",
    "manifests/",
    "keys/",
    ".state/",
)
PERSONAL_NAMES = ("MEMORY.md", "secrets-index.json", ".env")
SHARED_CLASSIFICATIONS = ("public", "internal")


class AbacError(Exception):
    """A malformed subject or resource, always fail-closed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def normalize_path(path: Any) -> str:
    """A relative POSIX path with no parent escape and no platform ambiguity."""
    if not isinstance(path, str) or not path.strip():
        raise AbacError("resource-path-invalid", "resource path is missing")
    if "\\" in path:
        raise AbacError("resource-path-invalid", "resource path contains a backslash")
    candidate = PurePosixPath(path.strip())
    if candidate.is_absolute() or any(part in ("..", "") for part in candidate.parts):
        raise AbacError("resource-path-invalid", "resource path escapes its vault")
    return candidate.as_posix()


def _matches_prefix(path: str, prefix: str) -> bool:
    if path == prefix or path == prefix.rstrip("/"):
        return True
    if prefix.endswith("/") or prefix.endswith("-"):
        return path.startswith(prefix)
    return path.startswith(prefix + "/")


def _matches_any(path: str, prefixes: Sequence[str]) -> bool:
    return any(_matches_prefix(path, prefix) for prefix in prefixes)


def is_personal(path: str) -> bool:
    normalized = normalize_path(path)
    wrapped = f"/{normalized}/"
    if any(f"/{prefix.rstrip('/')}/" in wrapped for prefix in PERSONAL_PREFIXES):
        return True
    return PurePosixPath(normalized).name in PERSONAL_NAMES


def resource_class_for(path: str) -> str:
    normalized = normalize_path(path)
    if _matches_any(normalized, CLASS_PREFIXES["authority"]):
        return "authority"
    if _matches_any(normalized, CLASS_PREFIXES["shared"]):
        return "shared"
    if _matches_any(normalized, CLASS_PREFIXES["fabric"]):
        return "fabric"
    return "vault"


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _expired(value: Any, now: datetime) -> bool:
    if value in (None, ""):
        return False
    moment = _parse_time(value)
    return moment is None or moment <= now


def _now(value: datetime | None) -> datetime:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _require_verified(record: Any) -> None:
    if not isinstance(record, Mapping) or record.get("verified") is not True:
        raise AbacError("subject-unverified", "subject has not been verified by sparknet-authz")


def subject_from_registry(entry: Mapping[str, Any], vault_id: str, *, verified: bool = False) -> dict[str, Any]:
    """Project a real `registry-schema.json` entry after authz verification.

    The registry entry deliberately carries no vault path, so the local vault id
    is a trusted role-configuration argument, never a field from the request.
    ``verified`` must be set by the caller only after `sparknet-authz.py` has
    verified the entry's signature and evaluated it.
    """
    if verified is not True:
        raise AbacError("subject-unverified", "registry entry has not been verified by sparknet-authz")
    if not isinstance(entry, Mapping):
        raise AbacError("subject-unverified", "registry entry is not an object")
    if not isinstance(vault_id, str) or not vault_id.strip():
        raise AbacError("subject-unverified", "local vault id is missing")
    identity = entry.get("identity")
    identity = identity if isinstance(identity, Mapping) else {}
    node_id = identity.get("node_id")
    role = identity.get("role") or "peer"
    if not isinstance(node_id, str) or not node_id.strip():
        raise AbacError("subject-unverified", "registry entry has no node id")
    capabilities = entry.get("capabilities")
    if capabilities is None:
        capabilities = []
    if not isinstance(capabilities, (list, tuple)) or not all(isinstance(item, str) for item in capabilities):
        raise AbacError("subject-unverified", "registry capabilities are malformed")
    department = entry.get("department")
    if department is not None and not isinstance(department, str):
        raise AbacError("subject-unverified", "registry department is malformed")
    return {
        "verified": True,
        "kind": "node",
        "id": node_id.strip(),
        "vault_id": normalize_path(vault_id),
        "role": str(role),
        "department": department.strip() if isinstance(department, str) and department.strip() else None,
        "capabilities": sorted(set(capabilities)),
        "scope": [],
        "expires_at": entry.get("expires_at"),
    }


def subject_from_grant(grant: Mapping[str, Any], vault_id: str, *, verified: bool = False) -> dict[str, Any]:
    """Project a real signed grant after guard verification.

    The grant's scope is ``vault_scope``; the vault path is local configuration.
    Empty ``vault_scope`` is valid and means node-level configuration only, so
    the subject exists but every knowledge read is denied by the scope check.
    """
    if verified is not True:
        raise AbacError("subject-unverified", "session grant has not been verified by sparknet-authz")
    if not isinstance(grant, Mapping):
        raise AbacError("subject-unverified", "session grant is not an object")
    if not isinstance(vault_id, str) or not vault_id.strip():
        raise AbacError("subject-unverified", "local vault id is missing")
    user_id = grant.get("user_identity")
    if not isinstance(user_id, str) or not user_id.strip():
        raise AbacError("subject-unverified", "session grant has no user identity")
    scope = grant.get("vault_scope")
    if not isinstance(scope, (list, tuple)):
        raise AbacError("subject-unverified", "session grant has no vault scope")
    normalized_scope = []
    for item in scope:
        try:
            normalized_scope.append(normalize_path(item))
        except AbacError as exc:
            raise AbacError("scope-widening", f"session scope is malformed: {item!r}") from exc
    capabilities = grant.get("capabilities") or []
    if not isinstance(capabilities, (list, tuple)) or not all(isinstance(item, str) for item in capabilities):
        raise AbacError("subject-unverified", "session capabilities are malformed")
    return {
        "verified": True,
        "kind": "user",
        "id": user_id.strip(),
        "vault_id": normalize_path(vault_id),
        "role": "user",
        "department": None,
        "capabilities": sorted(set(capabilities)),
        "scope": normalized_scope,
        "expires_at": grant.get("expires_at"),
    }


def resource_from_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one ingestion classification record, fail-closed."""
    if not isinstance(record, Mapping):
        raise AbacError("missing-classification", "resource is not an object")
    classification = record.get("classification")
    if not isinstance(classification, str) or not classification.strip():
        raise AbacError("missing-classification", "resource has no classification")
    if classification not in CLASSIFICATIONS:
        raise AbacError("unknown-classification", f"unknown classification {classification!r}")
    resource_class = record.get("class")
    if not isinstance(resource_class, str) or not resource_class.strip():
        raise AbacError("resource-class-unknown", "resource has no class")
    if resource_class not in RESOURCE_CLASSES:
        raise AbacError("resource-class-unknown", f"unknown resource class {resource_class!r}")
    provenance = record.get("provenance")
    if not isinstance(provenance, Mapping):
        raise AbacError("missing-provenance", "resource has no provenance")
    source = provenance.get("source")
    digest = provenance.get("digest")
    if not isinstance(source, str) or not source.strip():
        raise AbacError("missing-provenance", "resource provenance has no source")
    if not isinstance(digest, str) or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise AbacError("missing-provenance", "resource provenance digest is not 64 lowercase hex")
    vault_id = record.get("vault_id")
    if not isinstance(vault_id, str) or not vault_id.strip():
        raise AbacError("vault-mismatch", "resource has no vault id")
    path = normalize_path(record.get("path"))
    department = record.get("department")
    if department is not None and not isinstance(department, str):
        raise AbacError("missing-classification", "resource department is malformed")
    return {
        "vault_id": normalize_path(vault_id),
        "path": path,
        "class": resource_class,
        "classification": classification,
        "department": department.strip() if isinstance(department, str) and department.strip() else None,
        "provenance": {"source": source.strip(), "digest": digest},
    }


def _decision(
    subject: Mapping[str, Any], resource: Mapping[str, Any], allowed: bool, reason: str, scope: Sequence[str]
) -> dict[str, Any]:
    return {
        "allowed": allowed,
        "reason": reason,
        "subject": str(subject.get("id") or ""),
        "subject_kind": str(subject.get("kind") or ""),
        "resource": str(resource.get("path") or ""),
        "vault_id": str(resource.get("vault_id") or ""),
        "classification": str(resource.get("classification") or ""),
        "effective_scope": list(scope),
    }


def _deny(
    subject: Mapping[str, Any], resource: Mapping[str, Any], reason: str, scope: Sequence[str] = ()
) -> dict[str, Any]:
    return _decision(subject, resource, False, reason, scope)


def _allow(subject: Mapping[str, Any], resource: Mapping[str, Any], scope: Sequence[str]) -> dict[str, Any]:
    return _decision(subject, resource, True, "allowed", scope)


def _scope_is_subset(requested: Sequence[str], effective: Sequence[str]) -> bool:
    if not requested:
        return False
    if "*" in effective:
        return True
    return all(any(_matches_prefix(item, prefix) for prefix in effective) for item in requested)


def _effective_scope(subject: Mapping[str, Any], resource: Mapping[str, Any]) -> list[str]:
    if subject.get("kind") == "user":
        return list(subject.get("scope") or [])
    if resource.get("class") == "vault":
        path = str(resource.get("path") or "")
        parent = PurePosixPath(path).parent
        if parent.as_posix() not in ("", "."):
            return [parent.as_posix() + "/"]
        return [path]
    return list(CLASS_PREFIXES.get(str(resource.get("class")), ()))


def evaluate(
    subject: Mapping[str, Any],
    resource: Mapping[str, Any],
    *,
    requested_scope: Sequence[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a fail-closed decision record. No capability is granted."""
    try:
        _require_verified(subject)
        if subject.get("kind") not in SUBJECT_KINDS:
            raise AbacError("subject-kind-unknown", "subject kind is unknown")
        if _expired(subject.get("expires_at"), _now(now)):
            raise AbacError("subject-expired", "subject has expired")
        resource = resource_from_record(resource)
    except AbacError as exc:
        safe_subject = subject if isinstance(subject, Mapping) else {}
        safe_resource = resource if isinstance(resource, Mapping) else {}
        return _deny(safe_subject, safe_resource, exc.code)

    scope = _effective_scope(subject, resource)
    if requested_scope is not None:
        try:
            normalized = [normalize_path(item) for item in requested_scope]
        except AbacError:
            return _deny(subject, resource, "resource-path-invalid", scope)
        if not _scope_is_subset(normalized, scope):
            return _deny(subject, resource, "scope-widening", scope)
        scope = normalized

    kind = str(subject.get("kind"))
    resource_class = str(resource.get("class"))
    path = str(resource.get("path"))

    if resource_class == "authority" or _matches_any(path, CLASS_PREFIXES["authority"]):
        return _deny(subject, resource, "authority-surface", scope)
    if resource_class_for(path) != resource_class:
        return _deny(subject, resource, "resource-class-mismatch", scope)
    if resource_class == "shared" and kind != "node":
        return _deny(subject, resource, "shared-corpus-forbidden", scope)
    if resource_class == "fabric" and kind != "node":
        return _deny(subject, resource, "fabric-corpus-forbidden", scope)

    if resource.get("vault_id") != subject.get("vault_id") and not (
        kind == "node" and resource_class in ("shared", "fabric")
    ):
        return _deny(subject, resource, "vault-mismatch", scope)

    subject_department = subject.get("department")
    resource_department = resource.get("department")
    if (
        subject_department
        and resource_department
        and subject_department != resource_department
        and not (set(CAPABILITY_MAP["cross_department"]) & set(subject.get("capabilities") or []))
    ):
        return _deny(subject, resource, "department-mismatch", scope)

    if resource_class == "shared":
        if kind != "node":
            return _deny(subject, resource, "shared-corpus-forbidden", scope)
        if resource.get("classification") not in SHARED_CLASSIFICATIONS:
            return _deny(subject, resource, "shared-corpus-forbidden", scope)
        if is_personal(path):
            return _deny(subject, resource, "personal-page-in-shared", scope)
        if not _matches_any(path, CLASS_PREFIXES["shared"]):
            return _deny(subject, resource, "shared-corpus-forbidden", scope)
        if not (set(CAPABILITY_MAP["shared"]) & set(subject.get("capabilities") or [])):
            return _deny(subject, resource, "capability-missing", scope)
        if not _matches_any(path, scope):
            return _deny(subject, resource, "scope-widening", scope)
        return _allow(subject, resource, scope)

    if resource_class == "fabric":
        if kind != "node":
            return _deny(subject, resource, "fabric-corpus-forbidden", scope)
        if resource.get("classification") not in SHARED_CLASSIFICATIONS:
            return _deny(subject, resource, "fabric-corpus-forbidden", scope)
        if is_personal(path):
            return _deny(subject, resource, "personal-page-in-shared", scope)
        if not _matches_any(path, CLASS_PREFIXES["fabric"]):
            return _deny(subject, resource, "fabric-corpus-forbidden", scope)
        if not (set(CAPABILITY_MAP["fabric"]) & set(subject.get("capabilities") or [])):
            return _deny(subject, resource, "capability-missing", scope)
        if not _matches_any(path, scope):
            return _deny(subject, resource, "scope-widening", scope)
        return _allow(subject, resource, scope)

    if not _matches_any(path, scope):
        return _deny(subject, resource, "scope-widening", scope)
    return _allow(subject, resource, scope)


def filter_resources(
    subject: Mapping[str, Any],
    resources: Sequence[Mapping[str, Any]],
    *,
    requested_scope: Sequence[str] | None = None,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Keep only resources the subject may read; never widens a scope."""
    kept = []
    for resource in resources:
        decision = evaluate(subject, resource, requested_scope=requested_scope, now=now)
        if decision["allowed"]:
            kept.append(decision)
    return kept


def decision_json(decision: Mapping[str, Any]) -> str:
    return canonical_json(decision)
