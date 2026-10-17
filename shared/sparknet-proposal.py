#!/usr/bin/env python3
"""sparknet-proposal — the cross-user proposal workflow.

`contracts/proposal-schema.json` is the source of truth for the three records
(proposal, review, decision), the lifecycle and the chain rules. This module
binds those rules to code and adds no cryptography of its own: it loads
`shared/sparknet-provenance.py` by path (which in turn loads the one authz and
merkle implementations) and reuses `dual_sign`, `append_block`,
`canonical_json` and `build_conversation_root`.

A proposal, a review and a decision are ordinary ledger blocks in the **peer**
event vocabulary. `append_block` header-signs each block with the node identity
key and chains it, so `verify_chain` checks them like any other block;
`verify_proposal_chain` adds the proposal-specific half — the logical order
(draft → submitted → reviewed → decided) and each record's own dual-control
signature over its committed conversation.

Run `sparknet-proposal.py --help` for the CLI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

# --- the one by-path loader (D10) --------------------------------------------
# `shared/` is not on sys.path, so this module's own directory is added before
# importing the fabric's single loader. These two lines are deliberately
# identical in every shared module; tests/test_contracts.py pins them.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

DEFAULT_SHARED_DIR = Path(__file__).resolve().parent

PROPOSAL_EVENTS = ("proposal", "review", "decision")
LIFECYCLE_STATES = ("draft", "submitted", "reviewed", "decided")
REVIEW_VERDICTS = ("approve", "reject", "request_changes")
DECISIONS = ("approved", "denied")

_ID_PREFIX = {"proposal": "PRO", "review": "REV", "decision": "DEC"}


class ProposalError(Exception):
    """A refusal with a message the caller can act on."""


# --- loading the implementation ----------------------------------------------


def _load_provenance() -> Any:
    """Load sparknet-provenance.py by path, never by import.

    Same rule as everywhere else in this fabric: one implementation, loaded by
    path. This module carries no Ed25519, no canonicalisation and no Merkle math
    — a private copy could drift and then sign records the verifier refuses.
    The resolve-and-cache mechanics live once in ``shared/sparknet_loader.py``.
    """
    return load_shared(
        "sparknet-provenance.py",
        "sparknet_proposal_provenance",
        error=ProposalError,
        message=(
            "cannot find shared/sparknet-provenance.py; set SPARKNET_SHARED_DIR. "
            "There is exactly one provenance implementation and this tool does not "
            "carry a fallback."
        ),
    )


def _contract() -> dict[str, Any]:
    """The proposal contract, read from disk so the rules are not restated here."""
    provenance = _load_provenance()
    env = os.environ.get("SPARKNET_CONTRACTS_DIR")
    base = Path(env) if env else Path(provenance.DEFAULT_SHARED_DIR).parent / "contracts"
    path = base / "proposal-schema.json"
    if not path.is_file():
        raise ProposalError(
            f"cannot find {path}; this tool refuses to guess its own rules. Set SPARKNET_CONTRACTS_DIR."
        )
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ProposalError(f"{path} is not valid JSON: {exc}") from exc


# --- the record envelope ------------------------------------------------------


def proposal_signable(record: dict[str, Any]) -> bytes:
    """The bytes both signatures cover: the record without its `signatures`.

    Identical to the approval envelope (`shared/sparknet-provenance.py`
    `approval_signable`), because a proposal is the same dual control over a
    different event.
    """
    return _load_provenance().canonical_json({k: v for k, v in record.items() if k != "signatures"})


def _required_fields(event: str) -> list[str]:
    contract = _contract()["records"][event]
    return list(contract["required_fields"].keys())


def _identity_fields(vault: Path, record: dict[str, Any]) -> dict[str, Any]:
    """The inline key material and node identity every record carries.

    A received record must verify with no local key material, so both public
    keys travel inline — the same reasoning the co-signature entry gives.
    """
    provenance = _load_provenance()
    user = provenance.parse_user_record(vault)
    if not provenance.user_is_filled(user):
        raise ProposalError("user record is unfilled; run `make user-init` first")
    return {
        "node_pubkey_b64": provenance.node_public_b64(vault),
        "user_public_key_b64": provenance.user_public_b64(user),
        "user_key_fingerprint": provenance.user_fingerprint(user),
    }


def _sign(vault: Path, record: dict[str, Any]) -> dict[str, Any]:
    """Attach the dual-control envelope (user consent + node attestation)."""
    provenance = _load_provenance()
    record.pop("signatures", None)
    record["signatures"] = provenance.dual_sign(vault, provenance.parse_user_record(vault), record)
    return record


def _next_id(vault: Path, event: str, moment) -> str:
    blocks = _ledger_blocks(vault)
    count = sum(1 for block in blocks if isinstance(block.get("data"), dict) and block["data"].get("event") == event)
    return f"{_ID_PREFIX[event]}-{moment.date().isoformat()}-{count + 1:03d}"


# --- reading the ledger -------------------------------------------------------


def _ledger_blocks(vault: Path) -> list[dict[str, Any]]:
    provenance = _load_provenance()
    path = vault / "blockchain" / "ledger.json"
    if not path.is_file():
        return []
    ledger = provenance.load_ledger(path)
    blocks = ledger.get("blocks")
    return [b for b in blocks if isinstance(b, dict)] if isinstance(blocks, list) else []


def proposal_records(vault: Path, proposal_id: str | None = None) -> list[dict[str, Any]]:
    """Every proposal/review/decision record in chain order, optionally one proposal's."""
    records: list[dict[str, Any]] = []
    for block in _ledger_blocks(vault):
        data = block.get("data")
        if not isinstance(data, dict) or data.get("event") not in PROPOSAL_EVENTS:
            continue
        if proposal_id is not None and data.get("proposal_id") != proposal_id:
            continue
        records.append(data)
    return records


def proposal_state(vault: Path, proposal_id: str) -> str:
    """The lifecycle state of one proposal, derived from the chain.

    Returns 'absent' when no proposal block names the id, else the furthest state
    reached: 'submitted', 'reviewed' or 'decided'.
    """
    matching = proposal_records(vault, proposal_id)
    if not any(r.get("event") == "proposal" for r in matching):
        return "absent"
    if any(r.get("event") == "decision" for r in matching):
        return "decided"
    if any(r.get("event") == "review" for r in matching):
        return "reviewed"
    return "submitted"


# --- building records ---------------------------------------------------------


def build_proposal(
    vault: Path,
    *,
    title: str,
    summary: str,
    agent: str,
    model: str,
    conversation: Iterable[dict[str, Any]] = (),
    clock=None,
) -> dict[str, Any]:
    """A proposal draft: the originating agent's work, uncountersigned and uncommitted.

    `draft` is local by design — the chain records commitments, not intentions.
    `submit_proposal` consumes this and appends the `submitted` block.
    """
    provenance = _load_provenance()
    moment = (clock or provenance.now)()
    user = provenance.parse_user_record(vault)
    if not provenance.user_is_filled(user):
        raise ProposalError("user record is unfilled; run `make user-init` first")
    entries = [dict(entry) for entry in conversation]
    return {
        "event": "proposal",
        "stage": "draft",
        "owner_id": str(user.get("owner_id")),
        "owner_node": provenance.node_id(vault),
        "title": title,
        "summary": summary,
        "agent": agent,
        "model": model,
        "conversation": entries,
        "conversation_root": provenance.build_conversation_root(entries),
        "created_at": provenance.iso(moment),
    }


def submit_proposal(vault: Path, draft: dict[str, Any], clock=None) -> dict[str, Any]:
    """Sign and append a draft as the `submitted` proposal block. Returns the record."""
    if not isinstance(draft, dict) or draft.get("event") != "proposal":
        raise ProposalError("submit_proposal expects a proposal draft")
    if draft.get("stage") != "draft":
        raise ProposalError(f"a proposal is submitted from the `draft` stage, got {draft.get('stage')!r}")
    if "signatures" in draft or "proposal_id" in draft:
        raise ProposalError("this draft was already submitted (it is signed or already has an id)")
    provenance = _load_provenance()
    moment = (clock or provenance.now)()
    record = dict(draft)
    record["stage"] = "submitted"
    record["proposal_id"] = _next_id(vault, "proposal", moment)
    record["recorded_at"] = provenance.iso(moment)
    record.update(_identity_fields(vault, record))
    _sign(vault, record)
    provenance.append_block(vault, record)
    return record


def build_review(
    vault: Path,
    *,
    proposal_id: str,
    verdict: str,
    reason: str,
    agent: str,
    model: str,
    conversation: Iterable[dict[str, Any]] = (),
    clock=None,
) -> dict[str, Any]:
    """A review draft: one reviewer's verdict, attributed to their agent and model."""
    if verdict not in REVIEW_VERDICTS:
        raise ProposalError(f"verdict must be one of {REVIEW_VERDICTS}, got {verdict!r}")
    provenance = _load_provenance()
    moment = (clock or provenance.now)()
    user = provenance.parse_user_record(vault)
    if not provenance.user_is_filled(user):
        raise ProposalError("user record is unfilled; run `make user-init` first")
    entries = [dict(entry) for entry in conversation]
    return {
        "event": "review",
        "stage": "draft",
        "proposal_id": proposal_id,
        "verdict": verdict,
        "reason": reason,
        "agent": agent,
        "model": model,
        "owner_id": str(user.get("owner_id")),
        "owner_node": provenance.node_id(vault),
        "conversation": entries,
        "conversation_root": provenance.build_conversation_root(entries),
        "created_at": provenance.iso(moment),
    }


def review_proposal(vault: Path, review: dict[str, Any], clock=None) -> dict[str, Any]:
    """Sign and append a review, fail-closed on the lifecycle. Returns the record."""
    if not isinstance(review, dict) or review.get("event") != "review":
        raise ProposalError("review_proposal expects a review draft")
    if review.get("stage") != "draft" or "signatures" in review:
        raise ProposalError("this review was already submitted (it is signed or not a draft)")
    proposal_id = str(review.get("proposal_id") or "")
    state = proposal_state(vault, proposal_id)
    if state == "absent":
        raise ProposalError(f"no proposal {proposal_id!r} on this chain; submit it first")
    if state == "decided":
        raise ProposalError(f"proposal {proposal_id!r} is already decided; it takes no more reviews")
    return _finalize_review(vault, review, clock)


def _finalize_review(vault: Path, review: dict[str, Any], clock=None) -> dict[str, Any]:
    """Sign and append one review draft; the lifecycle check happened already."""
    provenance = _load_provenance()
    moment = (clock or provenance.now)()
    record = {k: v for k, v in review.items() if k != "stage"}
    record["review_id"] = _next_id(vault, "review", moment)
    record["recorded_at"] = provenance.iso(moment)
    record.update(_identity_fields(vault, record))
    _sign(vault, record)
    provenance.append_block(vault, record)
    return record


def build_decision(
    vault: Path,
    *,
    proposal_id: str,
    decision: str,
    reason: str,
    agent: str,
    model: str,
    conversation: Iterable[dict[str, Any]] = (),
    clock=None,
) -> dict[str, Any]:
    """A decision draft: the owner's approve/deny. The owner_id is the deciding boss."""
    if decision not in DECISIONS:
        raise ProposalError(f"decision must be one of {DECISIONS}, got {decision!r}")
    provenance = _load_provenance()
    moment = (clock or provenance.now)()
    user = provenance.parse_user_record(vault)
    if not provenance.user_is_filled(user):
        raise ProposalError("user record is unfilled; run `make user-init` first")
    entries = [dict(entry) for entry in conversation]
    return {
        "event": "decision",
        "stage": "draft",
        "proposal_id": proposal_id,
        "decision": decision,
        "reason": reason,
        "agent": agent,
        "model": model,
        "owner_id": str(user.get("owner_id")),
        "owner_node": provenance.node_id(vault),
        "conversation": entries,
        "conversation_root": provenance.build_conversation_root(entries),
        "created_at": provenance.iso(moment),
    }


def decide_proposal(vault: Path, decision: dict[str, Any], clock=None) -> dict[str, Any]:
    """Sign and append a decision, fail-closed on the lifecycle. Returns the record."""
    if not isinstance(decision, dict) or decision.get("event") != "decision":
        raise ProposalError("decide_proposal expects a decision draft")
    if decision.get("stage") != "draft" or "signatures" in decision:
        raise ProposalError("this decision was already submitted (it is signed or not a draft)")
    proposal_id = str(decision.get("proposal_id") or "")
    state = proposal_state(vault, proposal_id)
    if state == "absent":
        raise ProposalError(f"no proposal {proposal_id!r} on this chain; submit it first")
    if state == "submitted":
        raise ProposalError(f"proposal {proposal_id!r} has no review yet; a decision needs at least one")
    if state == "decided":
        raise ProposalError(f"proposal {proposal_id!r} is already decided")
    return _finalize_decision(vault, decision, clock)


def _finalize_decision(vault: Path, decision: dict[str, Any], clock=None) -> dict[str, Any]:
    """Sign and append one decision draft; the lifecycle check happened already."""
    provenance = _load_provenance()
    moment = (clock or provenance.now)()
    record = {k: v for k, v in decision.items() if k != "stage"}
    record["decision_id"] = _next_id(vault, "decision", moment)
    record["recorded_at"] = provenance.iso(moment)
    record.update(_identity_fields(vault, record))
    _sign(vault, record)
    provenance.append_block(vault, record)
    return record


# --- the transport half: reviewing and deciding a *received* bundle -------------
#
# A proposal lives on its origin's ledger; a review lives on its reviewer's; a
# decision on its owner's. No node re-records a foreign author's block — a block
# whose `data.signatures.user` is another user's key would fail that node's own
# ledger verification (shared/sparknet-provenance.py `verify_approval_blocks`
# checks each peer-event record's user signature against *this* node's user key).
# So the lifecycle check for a received proposal runs against the whole bundle,
# not the local chain, and only the local node's own record is appended here.


def _state_from_records(records: list[dict[str, Any]]) -> str:
    """The furthest lifecycle state a bundle of records reaches."""
    events = {r.get("event") for r in records if isinstance(r, dict)}
    if "proposal" not in events:
        return "absent"
    if "decision" in events:
        return "decided"
    if "review" in events:
        return "reviewed"
    return "submitted"


def _bundle_proposal_id(bundle: list[dict[str, Any]]) -> str:
    for record in bundle:
        if isinstance(record, dict) and record.get("event") == "proposal":
            return str(record.get("proposal_id") or "")
    raise ProposalError("the bundle carries no proposal record")


def review_bundle(
    vault: Path,
    bundle: list[dict[str, Any]],
    *,
    verdict: str,
    reason: str,
    agent: str,
    model: str,
    conversation: Iterable[dict[str, Any]] = (),
    clock=None,
) -> dict[str, Any]:
    """Review a proposal received in ``bundle``; append this node's review only.

    The received chain is verified with the shared ladder first, so a forged or
    reordered bundle is refused before anything is signed. The lifecycle check is
    made against the bundle (the proposal is on its origin's ledger, not this
    vault's), and only the review is appended here.
    """
    problems = verify_proposal_chain(bundle)
    if problems:
        raise ProposalError("refusing a bundle that does not verify: " + "; ".join(problems))
    proposal_id = _bundle_proposal_id(bundle)
    if _state_from_records(bundle) == "decided":
        raise ProposalError(f"proposal {proposal_id!r} is already decided; it takes no more reviews")
    draft = build_review(
        vault,
        proposal_id=proposal_id,
        verdict=verdict,
        reason=reason,
        agent=agent,
        model=model,
        conversation=conversation,
        clock=clock,
    )
    return _finalize_review(vault, draft, clock)


def decide_bundle(
    vault: Path,
    bundle: list[dict[str, Any]],
    *,
    decision: str,
    reason: str,
    agent: str,
    model: str,
    conversation: Iterable[dict[str, Any]] = (),
    clock=None,
) -> dict[str, Any]:
    """Decide a proposal received in ``bundle``; append this node's decision only.

    As with ``review_bundle``: verify with the shared ladder, check the lifecycle
    against the bundle, and append only the decision to this vault's ledger.
    """
    problems = verify_proposal_chain(bundle)
    if problems:
        raise ProposalError("refusing a bundle that does not verify: " + "; ".join(problems))
    proposal_id = _bundle_proposal_id(bundle)
    state = _state_from_records(bundle)
    if state == "submitted":
        raise ProposalError(f"proposal {proposal_id!r} has no review yet; a decision needs at least one")
    if state == "decided":
        raise ProposalError(f"proposal {proposal_id!r} is already decided")
    draft = build_decision(
        vault,
        proposal_id=proposal_id,
        decision=decision,
        reason=reason,
        agent=agent,
        model=model,
        conversation=conversation,
        clock=clock,
    )
    return _finalize_decision(vault, draft, clock)


# --- verification -------------------------------------------------------------


def _record_problems(record: Any) -> list[str]:
    """Everything wrong with one record, independent of the chain around it."""
    if not isinstance(record, dict):
        return ["record is not an object"]
    event = record.get("event")
    if event not in PROPOSAL_EVENTS:
        return [f"unknown proposal event {event!r}"]
    missing = [f for f in _required_fields(event) if f not in record]
    if missing:
        return [f"{event} record missing {', '.join(missing)}"]

    provenance = _load_provenance()
    authz = provenance._load_authz()
    problems: list[str] = []

    if record.get("conversation_root") != provenance.build_conversation_root(record.get("conversation")):
        problems.append("conversation_root does not match the recorded conversation")

    user_public = str(record.get("user_public_key_b64") or "")
    user_pub = None
    try:
        expected_fp = provenance.fingerprint_label_of_public_b64(user_public)
    except provenance.ProvenanceError:
        problems.append("user_public_key_b64 is not a usable Ed25519 public key")
    else:
        if record.get("user_key_fingerprint") != expected_fp:
            problems.append("user_key_fingerprint does not match user_public_key_b64")
        try:
            user_pub = authz.public_key_from_b64(user_public)
        except Exception:
            user_pub = None

    message = proposal_signable(record)
    signatures = record.get("signatures")
    signatures = signatures if isinstance(signatures, dict) else {}

    if user_pub is not None and not authz.verify_signature(user_pub, str(signatures.get("user") or ""), message):
        problems.append("the user signature does not verify over the record")

    try:
        node_pub = authz.public_key_from_b64(str(record.get("node_pubkey_b64") or ""))
    except Exception:
        node_pub = None
    if node_pub is None:
        problems.append("node_pubkey_b64 is not a usable Ed25519 public key")
    elif not authz.verify_signature(node_pub, str(signatures.get("node") or ""), message):
        problems.append("the node signature does not verify over the record")

    return problems


def verify_proposal_chain(records: Any) -> list[str]:
    """Walk proposal → reviews → decision and return every problem found.

    Empty means a well-formed, in-order, signed chain. A forged signature, a
    swapped key, a tampered conversation, a missing proposal, a second decision,
    a decision before any review or a review after the decision each yields a
    problem. Integrity and order only: a byte-intact record proves the bytes and
    the attestation, not yet *who* the signer is — the caller resolves identity
    against the registry or a user.md snapshot, as with a co-signature.
    """
    if not isinstance(records, list) or not records:
        return ["no proposal records"]

    problems: list[str] = []
    for index, record in enumerate(records):
        for problem in _record_problems(record):
            problems.append(f"record {index}: {problem}")

    def indices(event: str) -> list[int]:
        return [i for i, r in enumerate(records) if isinstance(r, dict) and r.get("event") == event]

    proposals = indices("proposal")
    reviews = indices("review")
    decisions = indices("decision")

    if not proposals:
        problems.append("no proposal record")
        return problems
    if len(proposals) > 1:
        problems.append("more than one proposal record")
    proposal_index = proposals[0]
    if proposal_index != 0:
        problems.append("the proposal is not the first record")
    if len(decisions) > 1:
        problems.append("more than one decision record")
    decision_index = decisions[0] if decisions else -1

    for index in reviews:
        if index < proposal_index:
            problems.append("a review precedes the proposal")
        if decision_index != -1 and index > decision_index:
            problems.append("a review follows the decision")
    if decision_index != -1 and not any(i < decision_index for i in reviews):
        problems.append("the decision precedes every review")

    proposal_id = records[proposal_index].get("proposal_id")
    for index, record in enumerate(records):
        if not isinstance(record, dict) or record.get("event") not in ("review", "decision"):
            continue
        if record.get("proposal_id") != proposal_id:
            problems.append(
                f"record {index} references proposal {record.get('proposal_id')!r}, expected {proposal_id!r}"
            )
    return problems


def verify_vault_proposals(vault: Path) -> list[str]:
    """Verify every proposal chain on this vault's ledger, one problem list each."""
    problems: list[str] = []
    seen: list[str] = []
    for record in proposal_records(vault):
        if record.get("event") != "proposal":
            continue
        proposal_id = str(record.get("proposal_id"))
        if proposal_id in seen:
            continue
        seen.append(proposal_id)
        for problem in verify_proposal_chain(proposal_records(vault, proposal_id)):
            problems.append(f"{proposal_id}: {problem}")
    return problems


# --- CLI ----------------------------------------------------------------------


def _emit(record: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(record, indent=2, sort_keys=True) + "\n")


def _resolve_vault(args: argparse.Namespace) -> Path:
    if args.vault:
        return Path(args.vault).resolve()
    env = os.environ.get("VAULT_PATH")
    if env:
        return Path(env).resolve()
    cwd = Path.cwd()
    for candidate in (cwd, *cwd.parents):
        if (candidate / "00_System" / "user.md").is_file():
            return candidate
        if (candidate / "blockchain").is_dir() and (candidate / "manifests").is_dir():
            return candidate
    raise ProposalError("cannot find a vault; pass --vault or set VAULT_PATH")


def _load_json(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ProposalError(f"cannot read {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sparknet-proposal.py",
        description=(
            "The cross-user proposal workflow (contracts/proposal-schema.json): "
            "propose, review, decide, and verify the chain."
        ),
    )
    parser.add_argument("--vault", help="the vault root (default: VAULT_PATH or the cwd)")
    sub = parser.add_subparsers(dest="command")

    propose = sub.add_parser("propose", help="build an unsigned proposal draft")
    propose.add_argument("--title", required=True)
    propose.add_argument("--summary", required=True)
    propose.add_argument("--agent", required=True)
    propose.add_argument("--model", required=True)
    propose.add_argument("--conversation", help="a JSON file with a conversation list")
    propose.add_argument("--out", help="write the draft here (default: stdout)")

    submit = sub.add_parser("submit", help="sign and append a proposal draft")
    submit.add_argument("draft", help="a draft JSON file from `propose`")

    review = sub.add_parser("review", help="build, sign and append a review")
    review.add_argument("--proposal-id", required=True)
    review.add_argument("--verdict", required=True, choices=REVIEW_VERDICTS)
    review.add_argument("--reason", required=True)
    review.add_argument("--agent", required=True)
    review.add_argument("--model", required=True)

    decide = sub.add_parser("decide", help="build, sign and append a decision")
    decide.add_argument("--proposal-id", required=True)
    decide.add_argument("--decision", required=True, choices=DECISIONS)
    decide.add_argument("--reason", required=True)
    decide.add_argument("--agent", required=True)
    decide.add_argument("--model", required=True)

    verify = sub.add_parser("verify", help="verify a proposal chain from a JSON file")
    verify.add_argument("chain", help="a JSON file with a list of records")

    listing = sub.add_parser("list", help="list the proposal chains on this vault")
    listing.add_argument("--proposal-id")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2

    try:
        if args.command == "verify":
            problems = verify_proposal_chain(_load_json(args.chain))
            if problems:
                for problem in problems:
                    sys.stdout.write(problem + "\n")
                return 1
            sys.stdout.write("proposal chain ok\n")
            return 0

        vault = _resolve_vault(args)

        if args.command == "propose":
            conversation = _load_json(args.conversation) if args.conversation else []
            draft = build_proposal(
                vault,
                title=args.title,
                summary=args.summary,
                agent=args.agent,
                model=args.model,
                conversation=conversation,
            )
            if args.out:
                Path(args.out).write_text(json.dumps(draft, indent=2, sort_keys=True) + "\n")
                sys.stdout.write(f"draft written to {args.out}\n")
            else:
                _emit(draft)
            return 0

        if args.command == "submit":
            record = submit_proposal(vault, _load_json(args.draft))
            _emit(record)
            return 0

        if args.command == "review":
            review = build_review(
                vault,
                proposal_id=args.proposal_id,
                verdict=args.verdict,
                reason=args.reason,
                agent=args.agent,
                model=args.model,
            )
            _emit(review_proposal(vault, review))
            return 0

        if args.command == "decide":
            decision = build_decision(
                vault,
                proposal_id=args.proposal_id,
                decision=args.decision,
                reason=args.reason,
                agent=args.agent,
                model=args.model,
            )
            _emit(decide_proposal(vault, decision))
            return 0

        if args.command == "list":
            for record in proposal_records(vault, args.proposal_id):
                label = record.get("verdict") or record.get("decision") or record.get("stage") or ""
                sys.stdout.write(f"{record.get('event', '?'):9} {record.get('proposal_id', ''):16} {label}\n")
            return 0
    except ProposalError as exc:
        sys.stderr.write(f"refused: {exc}\n")
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
