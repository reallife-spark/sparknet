#!/usr/bin/env python3
"""Sparknet provenance facade: one path over the accountability-chain modules.

Callers and role code load this file by path. It re-exports the lifecycle
modules and keeps the CLI, so ``provenance.<name>`` and every existing command
stay unchanged. The lifecycle modules are:

* ``sparknet-provenance-base.py`` — loader, canonical form, crypto loaders,
  contract reader, time/key-path helpers and shared key patterns;
* ``sparknet-provenance-scan.py`` — secret-index scanning;
* ``sparknet-provenance-note.py`` — note envelope, co-signatures, user record,
  shims and inbox intake;
* ``sparknet-provenance-ledger.py`` — ledger, approvals, checkpoints, inbox
  acceptance and vault-wide verification;
* ``sparknet-provenance-grant.py`` — scope containment, nonce retention and
  grant-scoped writes.

The canonical note message, ledger block bytes and grant verification order are
implemented once; this facade only loads and re-exports them. The normative
contracts are ``contracts/tracking-schema.json`` and
``contracts/provenance-protocol.md``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

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
        "cannot find shared/sparknet-provenance-base.py; the provenance facade carries exactly "
        "one implementation and this tool does not carry a fallback. Set "
        "SPARKNET_SHARED_DIR."
    ),
)

_scan = load_shared(
    "sparknet-provenance-scan.py",
    "sparknet_provenance_scan",
    error=ImportError,
    message=(
        "cannot find shared/sparknet-provenance-scan.py; the provenance facade carries exactly "
        "one implementation and this tool does not carry a fallback. Set "
        "SPARKNET_SHARED_DIR."
    ),
)

_note = load_shared(
    "sparknet-provenance-note.py",
    "sparknet_provenance_note",
    error=_base.ProvenanceError,
    message=(
        "cannot find shared/sparknet-provenance-note.py; the provenance facade carries exactly "
        "one implementation and this tool does not carry a fallback. Set "
        "SPARKNET_SHARED_DIR."
    ),
)

_ledger = load_shared(
    "sparknet-provenance-ledger.py",
    "sparknet_provenance_ledger",
    error=_base.ProvenanceError,
    message=(
        "cannot find shared/sparknet-provenance-ledger.py; the provenance facade carries exactly "
        "one implementation and this tool does not carry a fallback. Set "
        "SPARKNET_SHARED_DIR."
    ),
)

_grant = load_shared(
    "sparknet-provenance-grant.py",
    "sparknet_provenance_grant",
    error=_base.ProvenanceError,
    message=(
        "cannot find shared/sparknet-provenance-grant.py; the provenance facade carries exactly "
        "one implementation and this tool does not carry a fallback. Set "
        "SPARKNET_SHARED_DIR."
    ),
)


# The public compatibility surface. Every lifecycle module owns its names; the
# facade only binds the same objects and never redefines their behaviour.
DEFAULT_SHARED_DIR = _base.DEFAULT_SHARED_DIR
FINGERPRINT_RE = _base.FINGERPRINT_RE
OWNER_ID_RE = _base.OWNER_ID_RE
USER_RECORD_REF = _base.USER_RECORD_REF
_PATTERNS = _base._PATTERNS
FrontmatterError = _base.FrontmatterError
ProvenanceError = _base.ProvenanceError
_find_vault_from_cwd = _base._find_vault_from_cwd
_iso = _base._iso
_load_abac = _base._load_abac
_load_authz = _base._load_authz
_load_merkle = _base._load_merkle
_node_id = _base._node_id
_node_key_path = _base._node_key_path
_now = _base._now
_refuse_loose_key = _base._refuse_loose_key
_split_frontmatter = _base._split_frontmatter
_state_dir = _base._state_dir
_user_key_path = _base._user_key_path
canonical_json = _base.canonical_json
contract = _base.contract
emit_yaml = _base.emit_yaml
fingerprint_label_of_public_b64 = _base.fingerprint_label_of_public_b64
fingerprint_of_public_b64 = _base.fingerprint_of_public_b64
parse_yaml_subset = _base.parse_yaml_subset
sha256_hex = _base.sha256_hex

SECRET_INDEX_ENTRY_KEYS = _scan.SECRET_INDEX_ENTRY_KEYS
SECRET_INDEX_FORBIDDEN = _scan.SECRET_INDEX_FORBIDDEN
_SCAN_EXEMPT = _scan._SCAN_EXEMPT
_resolve_secret_ref = _scan._resolve_secret_ref
_tracked_files = _scan._tracked_files
scan = _scan.scan

CO_SIGNATURE_FIELDS = _note.CO_SIGNATURE_FIELDS
INGEST_SOURCES = _note.INGEST_SOURCES
NOTE_DOMAIN = _note.NOTE_DOMAIN
NOTE_VERSION = _note.NOTE_VERSION
USER_KEY_FIELDS = _note.USER_KEY_FIELDS
USER_RECORD_KEYS = _note.USER_RECORD_KEYS
_RECORDED_HASH_FIELDS = _note._RECORDED_HASH_FIELDS
_SLUG_RE = _note._SLUG_RE
_recorded_from_signature = _note._recorded_from_signature
_registry_admits_node = _note._registry_admits_node
_user_record_matches = _note._user_record_matches
_verify_lock = _note._verify_lock
add_co_signature = _note.add_co_signature
authorised_senders = _note.authorised_senders
build_conversation_root = _note.build_conversation_root
changed_meta_keys = _note.changed_meta_keys
check_shims = _note.check_shims
check_user_record = _note.check_user_record
emit_note = _note.emit_note
ingest_note = _note.ingest_note
meta_of = _note.meta_of
note_hashes = _note.note_hashes
note_message = _note.note_message
parse_user_record = _note.parse_user_record
sign_note = _note.sign_note
slugify = _note.slugify
split_note = _note.split_note
tracking_of = _note.tracking_of
unsigned_tracking = _note.unsigned_tracking
user_fingerprint = _note.user_fingerprint
user_init = _note.user_init
user_is_filled = _note.user_is_filled
user_public_b64 = _note.user_public_b64
user_record_path = _note.user_record_path
verify_co_signatures = _note.verify_co_signatures
verify_note = _note.verify_note

INBOX_SOURCES = _ledger.INBOX_SOURCES
INBOX_UNTRUSTED_SOURCES = _ledger.INBOX_UNTRUSTED_SOURCES
_adopt_vault_owner = _ledger._adopt_vault_owner
_anchored_checkpoints_path = _ledger._anchored_checkpoints_path
_checkpoint_block_problems = _ledger._checkpoint_block_problems
_dual_sign = _ledger._dual_sign
_node_public_b64 = _ledger._node_public_b64
_safe_frontmatter = _ledger._safe_frontmatter
anchor = _ledger.anchor
append_block = _ledger.append_block
approval_ids_in_ledger = _ledger.approval_ids_in_ledger
approval_signable = _ledger.approval_signable
block_hash = _ledger.block_hash
block_header_signable = _ledger.block_header_signable
build_approval_data = _ledger.build_approval_data
build_checkpoint_data = _ledger.build_checkpoint_data
build_inbox_acceptance = _ledger.build_inbox_acceptance
checkpoint = _ledger.checkpoint
dual_sign = _ledger.dual_sign
iso = _ledger.iso
load_anchored = _ledger.load_anchored
load_ledger = _ledger.load_ledger
node_id = _ledger.node_id
node_public_b64 = _ledger.node_public_b64
note_paths = _ledger.note_paths
now = _ledger.now
save_anchored = _ledger.save_anchored
verify_approval_blocks = _ledger.verify_approval_blocks
verify_chain = _ledger.verify_chain
verify_checkpoint = _ledger.verify_checkpoint
verify_vault = _ledger.verify_vault

_consumed_except = _grant._consumed_except
_safe_rel = _grant._safe_rel
_target_within_scope = _grant._target_within_scope
_verified_grant = _grant._verified_grant
build_grant_use_data = _grant.build_grant_use_data
consumed_grant_nonces = _grant.consumed_grant_nonces
grant_scope_allows = _grant.grant_scope_allows
patch_granted_note = _grant.patch_granted_note
promote_granted_note = _grant.promote_granted_note
quarantine_rel = _grant.quarantine_rel
safe_vault_target = _grant.safe_vault_target
write_granted_note = _grant.write_granted_note


__all__ = [
    "CO_SIGNATURE_FIELDS",
    "DEFAULT_SHARED_DIR",
    "FINGERPRINT_RE",
    "INBOX_SOURCES",
    "INBOX_UNTRUSTED_SOURCES",
    "INGEST_SOURCES",
    "NOTE_DOMAIN",
    "NOTE_VERSION",
    "OWNER_ID_RE",
    "SECRET_INDEX_ENTRY_KEYS",
    "SECRET_INDEX_FORBIDDEN",
    "USER_KEY_FIELDS",
    "USER_RECORD_KEYS",
    "USER_RECORD_REF",
    "_PATTERNS",
    "_RECORDED_HASH_FIELDS",
    "_SCAN_EXEMPT",
    "_SLUG_RE",
    "FrontmatterError",
    "ProvenanceError",
    "_adopt_vault_owner",
    "_anchored_checkpoints_path",
    "_checkpoint_block_problems",
    "_consumed_except",
    "_dual_sign",
    "_find_vault_from_cwd",
    "_iso",
    "_load_abac",
    "_load_authz",
    "_load_merkle",
    "_node_id",
    "_node_key_path",
    "_node_public_b64",
    "_now",
    "_recorded_from_signature",
    "_refuse_loose_key",
    "_registry_admits_node",
    "_resolve_secret_ref",
    "_safe_frontmatter",
    "_safe_rel",
    "_split_frontmatter",
    "_state_dir",
    "_target_within_scope",
    "_tracked_files",
    "_user_key_path",
    "_user_record_matches",
    "_verified_grant",
    "_verify_lock",
    "add_co_signature",
    "anchor",
    "append_block",
    "approval_ids_in_ledger",
    "approval_signable",
    "authorised_senders",
    "block_hash",
    "block_header_signable",
    "build_approval_data",
    "build_checkpoint_data",
    "build_conversation_root",
    "build_grant_use_data",
    "build_inbox_acceptance",
    "canonical_json",
    "changed_meta_keys",
    "check_shims",
    "check_user_record",
    "checkpoint",
    "consumed_grant_nonces",
    "contract",
    "dual_sign",
    "emit_note",
    "emit_yaml",
    "fingerprint_label_of_public_b64",
    "fingerprint_of_public_b64",
    "grant_scope_allows",
    "ingest_note",
    "iso",
    "load_anchored",
    "load_ledger",
    "main",
    "meta_of",
    "node_id",
    "node_public_b64",
    "note_hashes",
    "note_message",
    "note_paths",
    "now",
    "parse_user_record",
    "parse_yaml_subset",
    "patch_granted_note",
    "promote_granted_note",
    "quarantine_rel",
    "safe_vault_target",
    "save_anchored",
    "scan",
    "sha256_hex",
    "sign_note",
    "slugify",
    "split_note",
    "tracking_of",
    "unsigned_tracking",
    "user_fingerprint",
    "user_init",
    "user_is_filled",
    "user_public_b64",
    "user_record_path",
    "verify_approval_blocks",
    "verify_chain",
    "verify_checkpoint",
    "verify_co_signatures",
    "verify_note",
    "verify_vault",
    "write_granted_note",
]


def _resolve_vault(args: argparse.Namespace) -> Path:
    for candidate in (args.vault, os.environ.get("SPARKNET_VAULT_ROOT"), os.environ.get("VAULT_PATH")):
        if candidate:
            return Path(candidate).resolve()
    return _find_vault_from_cwd()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="sparknet provenance — notes, approvals, user record, secrets")
    parser.add_argument(
        "--vault",
        help="role vault root (default: $SPARKNET_VAULT_ROOT, else walk up from cwd)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_sign = sub.add_parser("sign-note", help="sign a note's current bytes with the user key")
    p_sign.add_argument("note", type=Path)
    p_sign.add_argument("--agent")
    p_sign.add_argument("--model")

    p_verify = sub.add_parser("verify-note", help="verify one note against the user record")
    p_verify.add_argument("note", type=Path)

    p_cosign = sub.add_parser(
        "co-sign",
        help="append this vault user's co-signature to a note, leaving the primary intact",
    )
    p_cosign.add_argument("note", type=Path)

    p_cosign_verify = sub.add_parser(
        "verify-co-signatures",
        help="verify a note's co-signatures against a registry and/or user.md snapshots",
    )
    p_cosign_verify.add_argument("note", type=Path)
    p_cosign_verify.add_argument(
        "--registry",
        type=Path,
        help="Master-signed node registry; default: <vault>/manifests/node-authorizations.json",
    )
    p_cosign_verify.add_argument(
        "--trusted-user",
        type=Path,
        action="append",
        default=[],
        dest="trusted_users",
        help="a user.md snapshot to trust offline (repeatable)",
    )

    p_vault = sub.add_parser("verify", help="verify notes, the ledger and approvals for a vault")
    p_vault.add_argument("--strict", action="store_true", help="treat stale:content as failure")

    p_init = sub.add_parser("user-init", help="generate the user key and fill 00_System/user.md once")
    p_init.add_argument("--owner-id", help="use this U-##### instead of assigning one")
    p_init.add_argument(
        "--force",
        action="store_true",
        help="re-key deliberately (invalidates every existing note signature)",
    )

    p_append = sub.add_parser("append-approval", help="record a dual-signed approval in the ledger")
    p_append.add_argument("--question", required=True)
    p_append.add_argument("--decision", required=True, choices=("approved", "rejected", "clarified"))
    p_append.add_argument(
        "--note",
        action="append",
        default=[],
        dest="notes",
        help="vault-relative note path (repeatable)",
    )
    p_append.add_argument("--agent", required=True)
    p_append.add_argument("--model", required=True)

    sub.add_parser(
        "append-checkpoint",
        help="append a signed checkpoint block (chain size, head hash, RFC 6962 root)",
    )

    p_anchor = sub.add_parser(
        "anchor-checkpoint",
        help="verify a signed checkpoint from another node and record the anchor",
    )
    p_anchor.add_argument(
        "--block",
        type=Path,
        required=True,
        help="the checkpoint block JSON, exactly as the other node sent it",
    )
    p_anchor.add_argument(
        "--proof",
        type=Path,
        help="consistency-proof JSON (a list of hash hex) for a growing checkpoint",
    )

    p_grant = sub.add_parser(
        "grant-write",
        help="write a vault note under a signed session grant (fail-closed; offline)",
    )
    p_grant.add_argument(
        "--grant",
        type=Path,
        required=True,
        help="the signed grant artifact (sparknet-authz.py grant-mint)",
    )
    p_grant.add_argument("--target", required=True, help="vault-relative write path, e.g. 05_Knowledge/concepts/foo.md")
    p_grant.add_argument("--body", help="note body text (one of --body / --body-file / stdin)")
    p_grant.add_argument("--body-file", type=Path, help="note body from a file")
    p_grant.add_argument("--session", required=True, help="the acting session id; a subagent passes its own child id")
    p_grant.add_argument("--agent", default="grant")
    p_grant.add_argument("--model", default="local")
    p_grant.add_argument(
        "--registry",
        type=Path,
        help="default: <vault>/manifests/node-authorizations.json",
    )
    p_grant.add_argument(
        "--node-identity",
        type=Path,
        help="default: <vault>/manifests/node-identity.json",
    )

    p_ingest = sub.add_parser("ingest", help="land one item in 01_Inbox/ as a pending note")
    p_ingest.add_argument(
        "path",
        nargs="?",
        default="-",
        help="file to read, or - for stdin (default)",
    )
    p_ingest.add_argument("--source", required=True, choices=INGEST_SOURCES)
    p_ingest.add_argument("--sender", help="the sender address; required for --source email")
    p_ingest.add_argument("--title", help="title and slug; defaults to the first heading")
    p_ingest.add_argument(
        "--classification",
        choices=_load_abac().CLASSIFICATIONS,
        help="classification recorded at O1; source defaults apply when omitted",
    )
    p_ingest.add_argument("--department", help="department attribute recorded at O1")
    p_ingest.add_argument("--agent", default="ingest")
    p_ingest.add_argument("--model", default="local")

    p_accept = sub.add_parser(
        "accept-inbox",
        help="record an inbox acceptance in the ledger (the item itself is not moved)",
    )
    p_accept.add_argument("item", help="vault-relative path under 01_Inbox/")
    p_accept.add_argument("--source", required=True, choices=INBOX_SOURCES)
    p_accept.add_argument("--decision", default="accepted", choices=("accepted", "rejected"))
    p_accept.add_argument("--reviewer", default="", help="named reviewer; required for untrusted ingress")
    p_accept.add_argument(
        "--sanitized",
        action="store_true",
        help="record that the reviewer sanitizes this untrusted item (sets validity=sanitized)",
    )
    p_accept.add_argument("--sender", default="", help="authorised sender for an email source")
    p_accept.add_argument("--note", action="append", default=[], dest="notes", help="related note path (repeatable)")
    p_accept.add_argument("--agent", default="inbox")
    p_accept.add_argument("--model", default="local")

    sub.add_parser("shims", help="prove every legacy name is a symlink to its numbered home")

    sub.add_parser("scan", help="fail on registered secrets or key-shaped literals in tracked files")

    args = parser.parse_args(argv)
    vault = _resolve_vault(args)

    try:
        if args.command == "sign-note":
            note = args.note if args.note.is_absolute() else Path.cwd() / args.note
            signed = sign_note(note.read_bytes(), vault, agent=args.agent, model=args.model)
            note.write_bytes(signed)
            print(f"signed: {note}")
            return 0
        if args.command == "verify-note":
            note = args.note if args.note.is_absolute() else Path.cwd() / args.note
            outcome, detail = verify_note(note, vault=vault)
            print(f"{outcome}: {detail}")
            return {"valid": 0, "pending": 0, "stale:metadata": 0, "stale:content": 2, "invalid": 1}[outcome]
        if args.command == "co-sign":
            note = args.note if args.note.is_absolute() else Path.cwd() / args.note
            signed = add_co_signature(note.read_bytes(), vault)
            note.write_bytes(signed)
            print(f"co-signed: {note}")
            return 0
        if args.command == "verify-co-signatures":
            note = args.note if args.note.is_absolute() else Path.cwd() / args.note
            frontmatter, _ = split_note(note.read_bytes())
            registry = None
            registry_path = args.registry or (vault / "manifests" / "node-authorizations.json")
            if registry_path.is_file():
                registry = json.loads(registry_path.read_text())
            elif args.registry is not None:
                raise ProvenanceError(f"registry not found: {registry_path}")
            trusted_users = []
            for path in args.trusted_users:
                raw_path = path if path.is_absolute() else Path.cwd() / path
                record_fm, _ = split_note(raw_path.read_bytes())
                trusted_users.append(record_fm)
            problems = verify_co_signatures(frontmatter, trusted_users=trusted_users, registry=registry)
            if not problems:
                print(f"co-signatures ok: {note}")
                return 0
            for problem in problems:
                print(f"  {problem}")
            return 1
        if args.command == "verify":
            code, text = verify_vault(vault, strict=args.strict)
            print(text)
            return code
        if args.command == "user-init":
            try:
                was_filled = user_is_filled(parse_user_record(vault))
            except ProvenanceError:
                was_filled = False
            record = user_init(vault, owner_id=args.owner_id, force=args.force)
            if was_filled and not args.force:
                print(f"already filled: {record['owner_id']} ({user_record_path(vault)}) — nothing changed")
                return 0
            print(f"filled user record: {record['owner_id']} ({user_record_path(vault)})")
            print(f"private key: {_user_key_path(vault)} (0600, never committed)")
            if args.force:
                print("re-keyed: every existing note signature is now stale — re-sign them")
            return 0
        if args.command == "ingest":
            if args.path == "-" or args.path is None:
                body = sys.stdin.buffer.read()
            else:
                source_path = Path(args.path)
                if not source_path.is_absolute():
                    source_path = Path.cwd() / source_path
                if not source_path.is_file():
                    raise ProvenanceError(f"no such file: {source_path}")
                body = source_path.read_bytes()
            if not body.strip():
                raise ProvenanceError("refusing to ingest an empty item")
            target = ingest_note(
                vault,
                body,
                source=args.source,
                sender=args.sender,
                title=args.title,
                classification=args.classification,
                department=args.department,
                agent=args.agent,
                model=args.model,
            )
            print(f"ingested: {target}")
            print("state: unsigned (pending) — acceptance and signature come later")
            return 0
        if args.command == "accept-inbox":
            record = parse_user_record(vault)
            data = build_inbox_acceptance(
                vault,
                item=args.item,
                source=args.source,
                decision=args.decision,
                reviewer=args.reviewer,
                sanitized=args.sanitized,
                sender=args.sender,
                note_refs=args.notes,
                record=record,
            )
            block = append_block(vault, data)
            print(
                f"recorded {data['acceptance_id']} as block {block['block_id']} "
                f"({data['decision']}, validity={data['validity']})"
            )
            return 0
        if args.command == "append-approval":
            record = parse_user_record(vault)
            data = build_approval_data(
                vault=vault,
                question=args.question,
                decision=args.decision,
                note_refs=args.notes,
                agent=args.agent,
                model=args.model,
                record=record,
            )
            block = append_block(vault, data)
            print(f"appended {data['approval_id']} as block {block['block_id']} (hash {block['hash'][:16]}...)")
            return 0
        if args.command == "append-checkpoint":
            block = checkpoint(vault)
            data = block["data"]
            print(
                f"appended checkpoint as block {block['block_id']}: "
                f"size {data['size']} head {data['head_hash'][:16]}... "
                f"root {data['root'][:16]}..."
            )
            return 0
        if args.command == "anchor-checkpoint":
            block = json.loads(args.block.read_text())
            proof = json.loads(args.proof.read_text()) if args.proof else None
            if proof is not None and not isinstance(proof, list):
                raise ProvenanceError("--proof must name a JSON list of hashes")
            ok, detail, _ = anchor(vault, block, proof=proof)
            print(f"{'anchored' if ok else 'refused'}: {detail}")
            return 0 if ok else 1
        if args.command == "grant-write":
            if not args.grant.is_file():
                raise ProvenanceError(f"no such grant file: {args.grant}")
            grant = json.loads(args.grant.read_text())
            if args.body_file:
                body = args.body_file.read_bytes()
            elif args.body is not None:
                body = args.body.encode("utf-8")
            else:
                body = sys.stdin.buffer.read()
            registry_path = args.registry or vault / "manifests" / "node-authorizations.json"
            identity_path = args.node_identity or vault / "manifests" / "node-identity.json"
            registry = json.loads(registry_path.read_text())
            identity = json.loads(identity_path.read_text())
            note_path, outcome, block = write_granted_note(
                vault,
                grant,
                target=args.target,
                body=body,
                session=args.session,
                registry=registry,
                node_identity=identity,
                agent=args.agent,
                model=args.model,
            )
            print(
                f"{outcome}: {note_path.relative_to(vault)} "
                f"(grant {grant['grant_id']}, session {args.session}, "
                f"block {block['block_id']} hash {block['hash'][:16]}...)"
            )
            return 0
        if args.command == "shims":
            code, text = check_shims(vault)
            print(text)
            return code
        if args.command == "scan":
            code, text = scan(vault)
            print(text)
            return code
    except ProvenanceError as exc:
        print(f"{args.command}: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
