#!/usr/bin/env python3
"""Sparknet provenance grants: scope containment, nonce retention and grant-scoped vault writes.

This lifecycle module loads base, note and ledger. It owns the grant-scope
containment rule, the ledger-as-nonce-store, the ``grant_use`` envelope and the
write/promote/patch paths that are checked against a signed session grant.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any

# --- the one by-path loader (D10) --------------------------------------------
# `shared/` is not on sys.path, so this module's own directory is added before
# importing the fabric's single loader. These two lines are deliberately
# identical in every shared module; tests/test_contracts.py pins them.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

_base = load_shared(
    "sparknet-provenance-base.py",
    "sparknet_provenance_base",
    error=ImportError,
    message=(
        "cannot find shared/sparknet-provenance-base.py; the provenance "
        "grant lifecycle does not carry a fallback. Set SPARKNET_SHARED_DIR."
    ),
)
_note = load_shared(
    "sparknet-provenance-note.py",
    "sparknet_provenance_note",
    error=_base.ProvenanceError,
    message=(
        "cannot find shared/sparknet-provenance-note.py; the provenance "
        "grant lifecycle does not carry a fallback. Set SPARKNET_SHARED_DIR."
    ),
)
_ledger = load_shared(
    "sparknet-provenance-ledger.py",
    "sparknet_provenance_ledger",
    error=_base.ProvenanceError,
    message=(
        "cannot find shared/sparknet-provenance-ledger.py; the provenance "
        "grant lifecycle does not carry a fallback. Set SPARKNET_SHARED_DIR."
    ),
)
ProvenanceError = _base.ProvenanceError
FrontmatterError = _base.FrontmatterError
USER_RECORD_REF = _base.USER_RECORD_REF
_now = _base._now
_iso = _base._iso
_load_authz = _base._load_authz
contract = _base.contract
_node_id = _base._node_id
parse_user_record = _note.parse_user_record
user_is_filled = _note.user_is_filled
sign_note = _note.sign_note
split_note = _note.split_note
emit_note = _note.emit_note
tracking_of = _note.tracking_of
_dual_sign = _ledger._dual_sign
_node_public_b64 = _ledger._node_public_b64
append_block = _ledger.append_block
load_ledger = _ledger.load_ledger


def _safe_rel(raw: str) -> PurePosixPath:
    """Normalise a vault-relative path, refusing anything that climbs out."""
    path = PurePosixPath(str(raw).strip())
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise ProvenanceError(f"not a vault-relative path: {raw!r}")
    return path


def safe_vault_target(vault: Path, rel: str) -> Path:
    """Resolve a vault-relative target without following a symlink component."""
    root = Path(vault).resolve()
    target_rel = _safe_rel(rel)
    target = (root / target_rel).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ProvenanceError(f"target escapes the vault: {rel!r}") from exc
    cursor = root
    for part in target_rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ProvenanceError(f"target path contains a symlink: {rel!r}")
    return target


def grant_scope_allows(scope: list[str], target_rel: str) -> bool:
    """Is this vault-relative write inside the grant's scope?

    Containment is a prefix of *path parts*, not a string prefix, so
    `05_Knowledge/con` does not cover `05_Knowledge/configs`. An empty scope
    allows nothing: contracts/identity-schema.json `vault_scope` says empty
    means node-level config only, no knowledge access — so a scope-less grant
    cannot reach any note.
    """
    target = _safe_rel(target_rel)
    for raw in scope:
        if not str(raw).strip():
            continue
        prefix = _safe_rel(str(raw))
        if target.parts[: len(prefix.parts)] == prefix.parts:
            return True
    return False


def quarantine_rel(vault: Path, grant_id: str, name: str) -> str:
    """Where an out-of-scope write lands: under `_raw/`, never at its target.

    The numbered path is derived from the contract's own legacy map, so this
    writes `03_Sources/grant-quarantine/...` on a role vault — which is the
    same file the `_raw/` shim names, and leaves the shim itself untouched.
    The material is kept (the vault does not delete what it was given) while
    authority is never widened by a signature.
    """
    if not isinstance(grant_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", grant_id):
        raise ProvenanceError("grant_id is not a safe path component")
    safe_name = _safe_rel(name)
    legacy = contract()["layout"]["legacy_map"]
    raw_dir = legacy.get("_raw", "_raw")
    return str(PurePosixPath(raw_dir, "grant-quarantine", grant_id, safe_name))


def consumed_grant_nonces(vault: Path) -> set[str]:
    """Grant nonces this node has already recorded.

    The ledger is the retention store contracts/identity-schema.json requires
    (`nonce.retention`): a nonce in any grant_use block is spent, so replaying
    that grant fails for as long as the chain exists.
    """
    path = vault / "blockchain" / "ledger.json"
    if not path.is_file():
        return set()
    ledger = load_ledger(path)
    return {
        str(block["data"].get("nonce"))
        for block in ledger.get("blocks", [])
        if isinstance(block, dict)
        and isinstance(block.get("data"), dict)
        and block["data"].get("event") == "grant_use"
        and block["data"].get("nonce")
    }


def _consumed_except(vault: Path, grant: dict[str, Any], allow_reused_nonce: bool) -> set[str]:
    """The spent-nonce set, optionally yielding the presenting grant's own nonce.

    The one-shot rule is ``allow_reused_nonce=False``. The session-level
    ``vault_access: all`` toggle passes ``True`` so a grant the operator made
    reusable keeps working after its first mutation; no *other* grant's nonce is
    ever discounted.
    """
    consumed = consumed_grant_nonces(vault)
    if allow_reused_nonce:
        consumed.discard(str(grant.get("nonce") or ""))
    return consumed


def build_grant_use_data(
    *,
    vault: Path,
    grant: dict[str, Any],
    decision: str,
    session: str,
    note_refs: list[str],
    agent: str,
    model: str,
    record: dict[str, Any],
    clock=None,
) -> dict[str, Any]:
    """Assemble a `grant_use` record over the same dual-control envelope as an
    approval: user consent plus node countersignature over one payload.

    `session` is required because it is the whole point of the record — the
    grant says what was permitted, the acting session says who used it, and the
    two differ whenever a subagent inherited a parent grant.
    """
    if decision not in ("granted", "quarantined"):
        raise ProvenanceError(f"decision must be granted|quarantined, got {decision!r}")
    if not isinstance(session, str) or not session:
        raise ProvenanceError("session is required: audit trails to the acting session, not the grant")
    if not isinstance(grant, dict) or not grant.get("grant_id"):
        raise ProvenanceError("grant must carry a grant_id")
    moment = (clock or _now)()
    try:
        blocks = load_ledger(vault / "blockchain" / "ledger.json").get("blocks", [])
    except ProvenanceError:
        blocks = []
    uses = sum(
        1 for block in blocks if isinstance(block, dict) and (block.get("data") or {}).get("event") == "grant_use"
    )
    data: dict[str, Any] = {
        "event": "grant_use",
        "grant_use_id": f"GUSE-{moment.date().isoformat()}-{uses + 1:03d}",
        "grant_id": str(grant.get("grant_id")),
        "parent_grant_id": grant.get("parent_grant_id"),
        "conversation_key": str(grant.get("conversation_key") or ""),
        "nonce": str(grant.get("nonce") or ""),
        "user_identity": str(grant.get("user_identity") or ""),
        "session": session,
        "decision": decision,
        "vault_scope": list(grant.get("vault_scope") or []),
        "agent": agent,
        "model": model,
        "note_refs": sorted(note_refs),
        "owner_id": str(record.get("owner_id")),
        "owner_node": _node_id(vault),
        "node_pubkey_b64": _node_public_b64(vault),
        "recorded_at": _iso(moment),
    }
    data["signatures"] = _dual_sign(vault, record, data)
    return data


def write_granted_note(
    vault: Path,
    grant: dict[str, Any],
    *,
    target: str,
    body: bytes,
    session: str,
    registry: dict[str, Any],
    node_identity: dict[str, Any],
    agent: str = "grant",
    model: str = "local",
    clock=None,
    allow_reused_nonce: bool = False,
) -> tuple[Path, str, dict[str, Any]]:
    """Write one note under a signed session grant. Fail-closed, in this order.

    Returns ``(note_path, decision, ledger_block)``.

    1. The grant is verified against the Master-signed registry and the node
       identity presenting it. A forged, expired, replayed, nonce-reused or
       out-of-node grant raises here and touches nothing — that is
       contracts/identity-schema.json `grant.verification_order`, the guard's
       check order, executed by shared/sparknet-authz.py: the one crypto
       implementation, not a second one.
    2. The target is checked against `vault_scope`. Out of scope never lands at
       the target: the material is quarantined under `_raw/` and the ledger
       records `decision: quarantined`, so nothing is silently lost and nothing
       silently lands outside the grant.
    3. The note is written with provenance frontmatter — owner, the grant, and
       the acting session — and signed with the user key.
    4. A `grant_use` block is appended, dual-signed and hash-chained, carrying
       the grant id, its parent when delegated, and the acting session. Audit
       is therefore finer than authority: authority traces to the parent grant,
       audit traces to the child session that used it.
    """
    authz = _load_authz()
    record = parse_user_record(vault)
    if not user_is_filled(record):
        raise ProvenanceError("user record is unfilled; run `make user-init` first")
    if not isinstance(session, str) or not session:
        raise ProvenanceError("session is required: audit trails to the acting session")
    if not body.strip():
        raise ProvenanceError("refusing to write an empty note")
    master_b64 = str((registry or {}).get("master_public_key_b64") or "")
    if not master_b64:
        raise ProvenanceError("registry carries no master_public_key_b64 — refusing to verify")
    # Fail fast on missing keys, before any file is written.
    _node_public_b64(vault)

    decision = authz.verify_grant(
        grant,
        master_public_key=authz.public_key_from_b64(master_b64),
        registry=registry,
        node_identity=node_identity,
        consumed_nonces=_consumed_except(vault, grant, allow_reused_nonce),
        now=(clock or _now)(),
    )
    if not decision.allowed:
        raise ProvenanceError(f"grant refused ({decision.reason}): {grant.get('grant_id', '?')}")

    now = (clock or _now)()
    rel = _safe_rel(target)
    if grant_scope_allows(list(grant.get("vault_scope") or []), str(rel)):
        outcome = "granted"
        note_rel = str(rel)
    else:
        outcome = "quarantined"
        note_rel = quarantine_rel(vault, str(grant["grant_id"]), rel.name)

    note_path = safe_vault_target(vault, note_rel)
    if note_path.exists():
        raise ProvenanceError(f"{note_rel} already exists — refusing to overwrite a vault note")

    heading = next(
        (line.lstrip("#").strip() for line in body.decode("utf-8", "replace").splitlines() if line.startswith("#")),
        "",
    )
    tracking: dict[str, Any] = {
        "schema": "sparknet-tracking/1",
        "owner_id": str(record.get("owner_id") or ""),
        "owner_node": str(record.get("owner_node") or _node_id(vault)),
        "owner_ref": USER_RECORD_REF,
        "validity": {"state": "unsigned"},
        "conversation": [],
        "shares": [],
        "agent": agent,
        "model": model,
        "approvals": [],
        "grant": {
            "grant_id": str(grant.get("grant_id")),
            "parent_grant_id": grant.get("parent_grant_id"),
            "conversation_key": str(grant.get("conversation_key") or ""),
            "session": session,
            "scope": list(grant.get("vault_scope") or []),
        },
    }
    meta = {"title": heading or PurePosixPath(note_rel).stem, "type": "vault-page", "captured": now.date().isoformat()}
    if not body.endswith(b"\n"):
        body += b"\n"
    note_path.parent.mkdir(parents=True, exist_ok=True)
    note_path.write_bytes(sign_note(emit_note({**meta, "tracking": tracking}, body), vault, agent=agent, model=model))

    block = append_block(
        vault,
        build_grant_use_data(
            vault=vault,
            grant=grant,
            decision=outcome,
            session=session,
            note_refs=[note_rel],
            agent=agent,
            model=model,
            record=record,
            clock=clock,
        ),
    )
    return note_path, outcome, block


def _verified_grant(
    vault: Path,
    grant: dict[str, Any],
    *,
    registry: dict[str, Any],
    node_identity: dict[str, Any],
    session: str,
    clock=None,
    allow_reused_nonce: bool = False,
) -> tuple[dict[str, Any], Any]:
    """The one fail-closed grant ladder every grant-scoped mutation shares.

    write/promote/patch are three entry points, not three policies: each calls
    this and only this to establish that the presenting vault holds the node
    key, that the Master-signed registry names a verifier, and that the grant
    walks identity-schema.json `grant.verification_order` with this node's
    ledger as the nonce store. A mutation that skipped one step of this ladder
    would be the second authority the fabric forbids.

    ``allow_reused_nonce`` is the session-level "all vault tools" toggle
    (``vault_access: all``): the *presenting* grant's own nonce is dropped from
    the consumed set so a grant the operator explicitly made reusable for a
    session keeps working after its first mutation. Every other grant's nonce
    stays spent, the signature, registry, expiry, node identity and per-target
    scope are still checked, and every mutation still appends a grant_use block.
    The default (``False``) is the one-shot rule; only the bridge's session
    toggle turns it on, and only for the grant that enabled it.
    """
    authz = _load_authz()
    if not isinstance(session, str) or not session:
        raise ProvenanceError("session is required: audit trails to the acting session")
    master_b64 = str((registry or {}).get("master_public_key_b64") or "")
    if not master_b64:
        raise ProvenanceError("registry carries no master_public_key_b64 — refusing to verify")
    _node_public_b64(vault)
    record = parse_user_record(vault)
    if not user_is_filled(record):
        raise ProvenanceError("user record is unfilled; run `make user-init` first")
    consumed = _consumed_except(vault, grant, allow_reused_nonce)
    decision = authz.verify_grant(
        grant,
        master_public_key=authz.public_key_from_b64(master_b64),
        registry=registry,
        node_identity=node_identity,
        consumed_nonces=consumed,
        now=(clock or _now)(),
    )
    if not decision.allowed:
        raise ProvenanceError(f"grant refused ({decision.reason}): {grant.get('grant_id', '?')}")
    return record, decision


def _target_within_scope(rel: PurePosixPath, grant: dict[str, Any], verb: str) -> None:
    if rel.suffix != ".md":
        raise ProvenanceError(f"{verb} refuses a non-note target: {rel!s}")
    if rel.parts[0] in ("blockchain", ".state"):
        raise ProvenanceError(f"{verb} refuses to touch {rel.parts[0]!r}: {rel!s}")
    if not grant_scope_allows(list(grant.get("vault_scope") or []), str(rel)):
        raise ProvenanceError(
            f"{verb} target {rel!s} is outside grant vault_scope {list(grant.get('vault_scope') or [])}"
        )


def promote_granted_note(
    vault: Path,
    grant: dict[str, Any],
    *,
    source: str,
    target: str,
    session: str,
    registry: dict[str, Any],
    node_identity: dict[str, Any],
    agent: str = "grant",
    model: str = "local",
    clock=None,
    allow_reused_nonce: bool = False,
) -> tuple[Path, str, dict[str, Any]]:
    """Move one note to its final place under a signed session grant.

    Returns ``(note_path, decision, ledger_block)``. Fail-closed like
    ``write_granted_note``: the grant verifies before anything moves, both the
    source and the destination must be inside ``vault_scope``, the destination
    must be free, and only a **pending raw/staged draft** — an unsigned note
    sitting in ``_raw``/``03_Sources`` or ``_staging`` — may be promoted. A
    signed note is somebody's attributed work; a grant that did not create it
    must not relocate it. Content is unchanged, so the draft's provenance stays
    as it was; the move is recorded as a new dual-signed ``grant_use`` block
    naming the final place.
    """
    record, _ = _verified_grant(
        vault,
        grant,
        registry=registry,
        node_identity=node_identity,
        session=session,
        clock=clock,
        allow_reused_nonce=allow_reused_nonce,
    )
    src = _safe_rel(source)
    dst = _safe_rel(target)
    _target_within_scope(src, grant, "promote")
    _target_within_scope(dst, grant, "promote")
    src_path = vault / src
    dst_path = vault / dst
    if not src_path.is_file():
        raise ProvenanceError(f"promote source does not exist: {src!s}")
    if dst_path.exists():
        raise ProvenanceError(f"promote destination already exists: {dst!s}")

    try:
        frontmatter, _body = split_note(src_path.read_bytes())
        tracking = tracking_of(frontmatter)
    except (FrontmatterError, UnicodeDecodeError):
        # A raw capture with no frontmatter fence is the *definition* of a
        # pending draft — nothing to parse means nothing to misattribute.
        tracking = {}
    validity = tracking.get("validity")
    pending = not isinstance(validity, dict) or validity.get("state") in (None, "unsigned")
    if not pending or src.parts[0] not in ("03_Sources", "_staging"):
        raise ProvenanceError(f"promote refuses {src!s}: only pending raw/staged drafts may be promoted")

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    src_path.replace(dst_path)
    block = append_block(
        vault,
        build_grant_use_data(
            vault=vault,
            grant=grant,
            decision="granted",
            session=session,
            note_refs=[str(dst)],
            agent=agent,
            model=model,
            record=record,
            clock=clock,
        ),
    )
    return dst_path, "granted", block


def patch_granted_note(
    vault: Path,
    grant: dict[str, Any],
    *,
    target: str,
    patch: dict[str, Any],
    session: str,
    registry: dict[str, Any],
    node_identity: dict[str, Any],
    agent: str = "grant",
    model: str = "local",
    clock=None,
    allow_reused_nonce: bool = False,
) -> tuple[Path, str, dict[str, Any]]:
    """Edit one note under a signed session grant, re-signing it.

    Returns ``(note_path, decision, ledger_block)``. The patch is a single
    ``old`` → ``new`` replacement applied to the note body — the frontmatter is
    never part of the search space — and ``old`` must appear exactly once. The
    patched body is re-signed with the user key so the note returns to ``valid``
    instead of drifting to ``stale:content``, and the mutation lands as a
    dual-signed ``grant_use`` block, the same envelope as a capture.
    """
    record, _ = _verified_grant(
        vault,
        grant,
        registry=registry,
        node_identity=node_identity,
        session=session,
        clock=clock,
        allow_reused_nonce=allow_reused_nonce,
    )
    rel = _safe_rel(target)
    _target_within_scope(rel, grant, "patch")
    note_path = safe_vault_target(vault, rel)
    if not note_path.is_file():
        raise ProvenanceError(f"patch target does not exist: {rel!s}")
    if not isinstance(patch, dict) or not isinstance(patch.get("old"), str) or not isinstance(patch.get("new"), str):
        raise ProvenanceError("patch must be an object with string `old` and `new`")
    old = patch["old"]
    if not old.strip():
        raise ProvenanceError("patch `old` cannot be empty")

    frontmatter, body = split_note(note_path.read_bytes())
    if body.count(old.encode("utf-8")) != 1:
        raise ProvenanceError("patch `old` must match exactly one occurrence in the note body")
    patched = body.replace(old.encode("utf-8"), patch["new"].encode("utf-8"), 1)
    if not patched.strip():
        raise ProvenanceError("refusing a patch that would empty the note")
    note_path.write_bytes(sign_note(emit_note(frontmatter, patched), vault, agent=agent, model=model))
    block = append_block(
        vault,
        build_grant_use_data(
            vault=vault,
            grant=grant,
            decision="granted",
            session=session,
            note_refs=[str(rel)],
            agent=agent,
            model=model,
            record=record,
            clock=clock,
        ),
    )
    return note_path, "granted", block


__all__ = [
    "_consumed_except",
    "_safe_rel",
    "_target_within_scope",
    "_verified_grant",
    "build_grant_use_data",
    "consumed_grant_nonces",
    "grant_scope_allows",
    "patch_granted_note",
    "promote_granted_note",
    "quarantine_rel",
    "safe_vault_target",
    "write_granted_note",
]
