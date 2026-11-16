#!/usr/bin/env python3
"""Federated human identity policy for node administration.

This module is the policy half of `contracts/sso-identity.md`. It does not run
an OIDC provider and it does not proxy HTTP; it decides the facts both sides
must agree on:

- which IdP group maps to which Open WebUI role;
- which caller-supplied identity headers a gateway must strip before injecting
  its own;
- how a per-node signed override interacts with the IdP baseline;
- how a Master→node assertion is verified (signature, target, freshness,
  replay);
- how a node-signed offline-repair record is verified and why it can never
  carry authority.

The one signed-envelope implementation stays in `shared/sparknet-authz.py`; this
module loads it by path and never re-implements Ed25519 or a second canonical
JSON rule.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

SHARED_DIR = Path(__file__).resolve().parent

ADMIN_GROUP = "sparknet-admins"
USER_GROUP = "sparknet-users"
ROLES = ("admin", "user")
ROLE_PENDING = "pending"

TRUSTED_EMAIL_HEADER = "X-User-Email"
TRUSTED_ROLE_HEADER = "X-User-Role"
TRUSTED_GROUPS_HEADER = "X-User-Groups"
IDENTITY_HEADER_PREFIX = "x-user-"

OVERRIDE_FILENAME = "admin-role-overrides.json"
DEFAULT_ASSERTION_MAX_SKEW_SECONDS = 300
DEFAULT_REPAIR_MAX_AGE_SECONDS = 30 * 24 * 3600

#: Refusals named by `contracts/sso-identity.md`. They are policy outcomes, not
#: signature failures; a caller surfaces the string and fails closed.
REASON_ASSERTION_MALFORMED = "malformed-assertion"
REASON_ASSERTION_BAD_SIGNATURE = "bad-signature"
REASON_ASSERTION_STALE = "assertion-stale"
REASON_ASSERTION_WRONG_NODE = "assertion-wrong-node"
REASON_ASSERTION_REPLAYED = "assertion-replayed"
REASON_ASSERTION_ROLE_MISMATCH = "role-group-mismatch"
REASON_REPAIR_MALFORMED = "malformed-repair"
REASON_REPAIR_BAD_SIGNATURE = "bad-signature"
REASON_REPAIR_WRONG_NODE = "repair-wrong-node"
REASON_REPAIR_STALE = "repair-stale"


class SSOError(ValueError):
    """Malformed identity policy input; the caller fails closed."""


def _authz() -> Any:
    return load_shared(
        "sparknet-authz.py",
        "sparknet_sso_authz",
        dirs=[SHARED_DIR],
        error=SSOError,
        message=f"cannot load the one authorization implementation from {SHARED_DIR / 'sparknet-authz.py'}",
    )


def _groups(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [part.strip() for part in value.split(",") if part.strip()]
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise SSOError("groups must be a list or comma-separated string")
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SSOError("group names must be non-empty strings")
        cleaned.append(item.strip())
    return cleaned


def role_for_groups(groups: Any) -> str | None:
    """Return the Open WebUI role an IdP group set grants, or None.

    Admin wins when a human is in both groups. A human in neither group has no
    online role: the contract refuses the login rather than promoting a
    `pending` account implicitly.
    """
    names = set(_groups(groups))
    if ADMIN_GROUP in names:
        return "admin"
    if USER_GROUP in names:
        return "user"
    return None


def strip_identity_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Remove every caller-supplied `X-User-*` header, case-insensitively.

    The gateway must call this before injecting its own identity. A proxy that
    forgets it turns a header into a password (`contracts/sso-identity.md`).
    """
    if not isinstance(headers, Mapping):
        raise SSOError("headers must be a mapping")
    return {name: value for name, value in headers.items() if not str(name).lower().startswith(IDENTITY_HEADER_PREFIX)}


def injected_headers(email: Any, role: Any, groups: Any = ()) -> dict[str, str]:
    """Build the trusted headers a gateway may inject into Open WebUI.

    The caller has already applied the override/precedence rule, so a per-node
    override may legitimately set a role that differs from the IdP groups. The
    assertion verifier is where online role/group agreement is enforced; this
    builder only refuses an unknown role or a malformed email.
    """
    if not isinstance(email, str) or "@" not in email:
        raise SSOError("email must be a non-empty address")
    if role not in ROLES:
        raise SSOError(f"role must be one of {', '.join(ROLES)}")
    names = _groups(groups)
    return {
        TRUSTED_EMAIL_HEADER: email,
        TRUSTED_ROLE_HEADER: role,
        TRUSTED_GROUPS_HEADER: ",".join(names),
    }


# --- per-node role overrides --------------------------------------------------


def validate_override(entry: Any) -> dict[str, Any]:
    """Validate one per-node role override record."""
    if not isinstance(entry, dict):
        raise SSOError("override must be an object")
    role = entry.get("role")
    if role not in ROLES:
        raise SSOError(f"override role must be one of {', '.join(ROLES)}")
    for field in ("set_by", "request_id", "set_at"):
        value = entry.get(field)
        if not isinstance(value, str) or not value.strip():
            raise SSOError(f"override {field} must be a non-empty string")
    reason = entry.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise SSOError("override reason must be a string when present")
    return {
        "role": role,
        "set_by": entry["set_by"].strip(),
        "request_id": entry["request_id"].strip(),
        "set_at": entry["set_at"].strip(),
        "reason": reason.strip() if isinstance(reason, str) else None,
    }


def load_overrides(path: str | Path) -> dict[str, dict[str, Any]]:
    """Read the 0600 override file; a missing file means no overrides."""
    target = Path(path)
    if not target.exists():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SSOError(f"cannot read role overrides from {target}: {exc}") from exc
    if not isinstance(data, dict):
        raise SSOError("role override file must map a user key to an override object")
    return {str(user): validate_override(entry) for user, entry in data.items()}


def effective_role(idp_role: str | None, override: Any = None) -> tuple[str | None, bool]:
    """Return ``(effective_role, conflict)`` for the precedence rule.

    A valid override wins on its node. A conflict is reported only when both a
    baseline and an override exist and disagree; the caller records it and holds
    it for a human rather than silently rewriting either side.
    """
    if idp_role is not None and idp_role not in ROLES:
        raise SSOError(f"IdP role must be one of {', '.join(ROLES)} or None")
    if override is None:
        return idp_role, False
    checked = validate_override(override)
    conflict = idp_role is not None and checked["role"] != idp_role
    return checked["role"], conflict


# --- Master→node assertion ----------------------------------------------------


def _now(now: datetime | None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise SSOError("now must be timezone-aware")
    return value


def _epoch(value: datetime) -> int:
    return int(value.timestamp())


def sign_assertion(assertion: dict[str, Any], private_key: Any) -> dict[str, Any]:
    """Sign one assertion with the shared envelope catalog."""
    return _authz().sign_envelope("sso-assertion", assertion, private_key)


def verify_assertion(
    assertion: Any,
    public_key: Any,
    *,
    expected_node_id: str,
    expected_fingerprint: str,
    now: datetime | None = None,
    seen_nonces: Iterable[str] = (),
    max_skew_seconds: int = DEFAULT_ASSERTION_MAX_SKEW_SECONDS,
) -> tuple[bool, str]:
    """Validate one Master→node assertion; returns ``(ok, reason)``, never raises.

    Order: shape, signature, target, role/group agreement, freshness, replay.
    A caller that cannot supply the expected node fails closed rather than
    accepting a wildcard target.
    """
    authz = _authz()
    if not isinstance(expected_node_id, str) or not expected_node_id:
        raise SSOError("expected_node_id is required")
    if not isinstance(expected_fingerprint, str) or not expected_fingerprint:
        raise SSOError("expected_fingerprint is required")
    try:
        authz.envelope_message("sso-assertion", assertion)
    except Exception:
        return False, REASON_ASSERTION_MALFORMED
    if not authz.verify_envelope("sso-assertion", assertion, public_key):
        return False, REASON_ASSERTION_BAD_SIGNATURE
    if assertion["target_node_id"] != expected_node_id or assertion["target_fingerprint"] != expected_fingerprint:
        return False, REASON_ASSERTION_WRONG_NODE
    if role_for_groups(assertion["groups"]) != assertion["role"]:
        return False, REASON_ASSERTION_ROLE_MISMATCH
    instant = _now(now)
    if assertion["issued_at"] > _epoch(instant) + max_skew_seconds:
        return False, REASON_ASSERTION_STALE
    if assertion["expires_at"] < _epoch(instant) - max_skew_seconds:
        return False, REASON_ASSERTION_STALE
    if assertion["expires_at"] <= assertion["issued_at"]:
        return False, REASON_ASSERTION_STALE
    if assertion["nonce"] in set(seen_nonces or ()):
        return False, REASON_ASSERTION_REPLAYED
    return True, ""


# --- offline-repair record ----------------------------------------------------


def _parse_iso8601(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def sign_offline_repair(record: dict[str, Any], private_key: Any) -> dict[str, Any]:
    """Sign one repair record with the node's own identity key."""
    return _authz().sign_envelope("offline-repair", record, private_key)


def verify_offline_repair(
    record: Any,
    public_key: Any,
    *,
    expected_node_id: str,
    expected_fingerprint: str,
    now: datetime | None = None,
    max_age_seconds: int = DEFAULT_REPAIR_MAX_AGE_SECONDS,
) -> tuple[bool, str]:
    """Validate one node-signed offline-repair record; returns ``(ok, reason)``."""
    authz = _authz()
    if not isinstance(expected_node_id, str) or not expected_node_id:
        raise SSOError("expected_node_id is required")
    if not isinstance(expected_fingerprint, str) or not expected_fingerprint:
        raise SSOError("expected_fingerprint is required")
    try:
        authz.envelope_message("offline-repair", record)
    except Exception:
        return False, REASON_REPAIR_MALFORMED
    if not authz.verify_envelope("offline-repair", record, public_key):
        return False, REASON_REPAIR_BAD_SIGNATURE
    if record["node_id"] != expected_node_id or record["node_fingerprint"] != expected_fingerprint:
        return False, REASON_REPAIR_WRONG_NODE
    created = _parse_iso8601(record["created_at"])
    if created is None:
        return False, REASON_REPAIR_MALFORMED
    instant = _now(now)
    if created > instant or (instant - created).total_seconds() > max_age_seconds:
        return False, REASON_REPAIR_STALE
    return True, ""


def load_public_key(path: str | Path):
    """Load an Ed25519 public key through the one authorization implementation."""
    return _authz().load_public_key(Path(path))


def load_private_key(path: str | Path):
    """Load an Ed25519 private key through the one authorization implementation."""
    return _authz().load_private_key(Path(path))


def public_key_from_b64(text: str):
    """Decode a base64 Ed25519 public key through the one implementation."""
    return _authz().public_key_from_b64(text)
