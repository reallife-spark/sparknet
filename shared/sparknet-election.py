#!/usr/bin/env python3
"""Sparknet election — the exchange that turns n votes into a trust root.

`shared/sparknet-consensus.py` knows how to *count* a vote and how to *check* a
root. It does not know how a conversation happens: nothing in it collects
ballots from all live cluster members, binds the winner's operational key into a
root, or hands that root around to be co-signed. That gap is this module.

Everything is delegated. Signature work goes through `sparknet-authz.py`;
verification, tallying, canonicalisation, co-signing and root acceptance go
through `sparknet-consensus.py`. This module contains no cryptography of its
own, and `tests/test_election.py` fails if that ever stops being true — a
second implementation of Ed25519 inside the one file that decides who may hold
the operational key would be the worst possible place for one.

Three properties are deliberate:

* **The service holds no private key.** It validates, tallies and merges;
  every signature is made by a member process that holds its own cluster key.
  An HTTP listener carrying a signing key is a worse trade than one more round
  trip, and the fabric already isolated the operational key for that reason.
* **Loopback first.** `serve` binds 127.0.0.1 unless told otherwise, because
  binding a real overlay address is a deployment act on a host that has the
  overlay, and this host does not. Port 4210 carries signed votes and signed
  root signatures only — never a registry entry and never an approval — so it
  decides who holds authority without ever carrying any.
* **A member will not co-sign what it did not vote for.** `root-sign` refuses
  a root naming anyone but the candidate it was told to expect, so a lying
  exchange cannot launder two honest votes into a third signature.

Normative: `contracts/consensus-protocol.md`. The endpoint shapes live in its
*Exchange* section; this file is that section's implementation.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request

try:  # Python 3.9+
    from collections.abc import Callable
except ImportError:  # pragma: no cover - Python 3.8
    from typing import Callable  # noqa: UP035

from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

# --- the one by-path loader (D10) --------------------------------------------
# `shared/` is not on sys.path, so this module's own directory is added before
# importing the fabric's single loader. These two lines are deliberately
# identical in every shared module; tests/test_contracts.py pins them.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_by_path as _load_by_path_impl

DEFAULT_SHARED_DIR = Path(__file__).resolve().parent

#: The exchange's port, from contracts/ports.json (`cluster-election`).
DEFAULT_PORT = 4210

#: Loopback, deliberately. See the module docstring.
DEFAULT_BIND = "127.0.0.1"

#: The election this exchange is running. Ballots carry it, so a later
#: election's votes cannot be replayed into an earlier one's tally. A
#: master-change is a new election and is run with a new id.
DEFAULT_ELECTION_ID = "cluster-election-1"

#: Poll interval while `member` waits for the other two. Transport politeness
#: only: no deadline in this protocol is measured in it — consensus-protocol.md
#: specifies unanimity (a count), not a window.
POLL_INTERVAL_SECONDS = 0.05

#: What a candidate signs when it offers its operational key.
REQUEST_FIELDS = ("node_id", "operational_pubkey_b64", "nonce", "ts")

REASON_MALFORMED = "malformed"
REASON_NOT_A_MEMBER = "signer_not_a_member"
REASON_BAD_SIGNATURE = "bad_signature"
REASON_MISSING_FIELD = "missing_field"
REASON_BID_ALREADY_FILED = "bid_already_filed"
REASON_WRONG_ELECTION_ID = "wrong_election_id"
REASON_NO_ROOT_YET = "no_root_yet"
REASON_ALREADY_SIGNED = "already_signed"
REASON_UNEXPECTED_MASTER = "unexpected_master"
REASON_ROOT_UNUSABLE = "root_unusable"
REASON_KEY_MISSING = "cluster_key_missing"
REASON_UNREACHABLE = "exchange_unreachable"
REASON_TIMEOUT = "election_timeout"

HTTP_BAD_REQUEST = 400
HTTP_FORBIDDEN = 403
HTTP_CONFLICT = 409

_CONFLICT_REASONS = {REASON_BID_ALREADY_FILED, REASON_ALREADY_SIGNED, REASON_NO_ROOT_YET}
_FORBIDDEN_REASONS = {
    REASON_NOT_A_MEMBER,
    REASON_BAD_SIGNATURE,
    REASON_UNEXPECTED_MASTER,
    REASON_KEY_MISSING,
}


class ElectionError(Exception):
    """An exchange refusal, carrying a stable machine-readable reason."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail

    def payload(self) -> dict[str, Any]:
        return {"ok": False, "reason": self.reason, "detail": self.detail}


# --- loading the implementations this module may not duplicate ------------------


def _load_by_path(name: str, path: Path) -> Any:
    """Load a hyphen-named sibling module, once.

    `sparknet-consensus.py` cannot be imported by name (the hyphen), so it is
    loaded by path and registered in `sys.modules` *before* execution. The
    resolve-and-cache mechanics live once in ``shared/sparknet_loader.py``; this
    wrapper only translates the loader's ``ImportError`` into this module's own
    refusal vocabulary.
    """
    try:
        return _load_by_path_impl(name, path)
    except ImportError:
        raise ElectionError(REASON_MALFORMED, f"cannot load {path}") from None


def load_consensus(shared_dir: Path | None = None) -> Any:
    here = Path(shared_dir) if shared_dir else DEFAULT_SHARED_DIR
    path = here / "sparknet-consensus.py"
    if not path.is_file():
        raise ElectionError(REASON_MALFORMED, f"shared/sparknet-consensus.py not found at {path}")
    return _load_by_path("sparknet_consensus", path)


def load_authz(shared_dir: Path | None = None) -> Any:
    """The one crypto implementation, reached the way consensus reaches it.

    `sparknet-consensus` already puts `sparknet-authz` in `sys.modules`, and
    this module always loads consensus first, so the common path is a lookup.
    Falling back to consensus's loader keeps one candidate list rather than two
    that must agree about where the implementation lives.
    """
    cached = sys.modules.get("sparknet_authz")
    if cached is not None:
        return cached
    return load_consensus(shared_dir)._load_authz(Path(shared_dir) if shared_dir else None)


def load_http(shared_dir: Path | None = None) -> Any:
    """The shared handler base, reached the way consensus reaches its deps.

    `sparknet-http.py` owns the socket timeout (``TimeoutHandler``); this
    module's listener must share that base or the exchange silently reverts to
    unbounded reads (review finding F4).  The usual callers already put
    ``sparknet-http`` in ``sys.modules``, so the common path is a lookup.
    """
    cached = sys.modules.get("sparknet_http")
    if cached is not None:
        return cached
    here = Path(shared_dir) if shared_dir else DEFAULT_SHARED_DIR
    path = here / "sparknet-http.py"
    if not path.is_file():
        raise ElectionError(REASON_MALFORMED, f"shared/sparknet-http.py not found at {path}")
    return _load_by_path("sparknet_http", path)


#: Loaded at import: the handler base is code, not configuration, so the one
#: sibling copy is the only correct source. ``tests/test_service_timeouts.py``
#: fails if the listener stops deriving from TimeoutHandler.
_HTTP = load_http()


# --- keys -----------------------------------------------------------------------


def key_path(key_dir: Path, name: str, private: bool) -> Path:
    return key_dir / (f"{name}.ed25519" if private else f"{name}.pub.b64")


def read_keypair(key_dir: Path, name: str, authz: Any) -> tuple[str, str]:
    """Read `<name>.ed25519` and its public half, deriving the latter if needed.

    The `.pub.b64` file is a convenience, never the source of truth: a public
    file that disagrees with the private key would produce a bid nobody can
    verify against the member, so the private key always wins.
    """
    private_path = key_path(key_dir, name, private=True)
    if not private_path.is_file():
        raise ElectionError(
            REASON_KEY_MISSING,
            f"{private_path} does not exist. A member joins a cluster with its "
            f"cluster key already issued — run `keygen --key-dir {key_dir}` first",
        )
    private_b64 = private_path.read_text().strip()
    try:
        key = authz.private_key_from_b64(private_b64)
    except Exception as exc:
        raise ElectionError(REASON_MALFORMED, f"{private_path} is not a usable key: {exc}") from exc
    public_b64 = authz.public_key_b64(key.public_key())
    public_path = key_path(key_dir, name, private=False)
    if public_path.is_file() and public_path.read_text().strip() != public_b64:
        public_path.write_text(public_b64 + "\n")
    return private_b64, public_b64


def ensure_keypair(key_dir: Path, name: str, authz: Any, force: bool = False) -> tuple[str, str, bool]:
    """Create `<name>` in `key_dir` unless it exists. Returns (private, public, created)."""
    private_path = key_path(key_dir, name, private=True)
    if private_path.is_file() and not force:
        private_b64, public_b64 = read_keypair(key_dir, name, authz)
        return private_b64, public_b64, False
    key_dir.mkdir(parents=True, exist_ok=True)
    private_b64, public_b64 = authz.generate_keypair()
    # Create the private half with its mode already set; chmod-after-write has
    # a window in which the key is readable.
    descriptor = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(private_b64 + "\n")
    except Exception:
        os.close(descriptor)
        raise
    public_path = key_path(key_dir, name, private=False)
    public_path.write_text(public_b64 + "\n")
    public_path.chmod(0o644)
    return private_b64, public_b64, True


# --- membership -----------------------------------------------------------------


def load_members(path: Path) -> list[dict[str, Any]]:
    """The cluster roster: two (a pair) or three distinct members, as a root names them.

    Membership is out of band by contract — there is no authority to bootstrap
    from, so the nodes exchange WireGuard public keys among themselves
    and this file is what came of it. The exchange verifies every ballot
    against it.
    """
    consensus = load_consensus()
    try:
        document = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ElectionError(REASON_MALFORMED, f"membership file unreadable: {exc}") from exc
    members = document.get("members")
    if not isinstance(members, list):
        raise ElectionError(REASON_MALFORMED, "membership file has no `members` list")
    required = ("node_id", "fingerprint", "wireguard_pubkey", "cluster_pubkey")
    for index, member in enumerate(members):
        if not isinstance(member, dict):
            raise ElectionError(REASON_MALFORMED, f"member {index} is not an object")
        absent = [field for field in required if field not in member]
        if absent:
            raise ElectionError(REASON_MISSING_FIELD, f"member {index} is missing {', '.join(absent)}")
    ids = [member["node_id"] for member in members]
    if len(set(ids)) != len(ids):
        raise ElectionError(REASON_MALFORMED, "membership contains a duplicate node_id")
    if len(members) < consensus.MIN_CLUSTER_SIZE or len(members) > consensus.MAX_CLUSTER_SIZE:
        raise ElectionError(
            REASON_MALFORMED,
            f"a cluster is {consensus.MIN_CLUSTER_SIZE} to "
            f"{consensus.MAX_CLUSTER_SIZE} members, this file has {len(members)}",
        )
    return members


# --- the candidate's bid ---------------------------------------------------------


def canonical_request(request: dict[str, Any]) -> bytes:
    """Bytes a candidate signs when offering its operational key.

    Sorted and tight, the same rule as every other canonical form in the
    fabric, so two nodes encoding the same bid agree byte for byte.
    """
    absent = [field for field in REQUEST_FIELDS if field not in request]
    if absent:
        raise ElectionError(REASON_MISSING_FIELD, f"election request is missing {', '.join(absent)}")
    envelope = {field: request[field] for field in sorted(REQUEST_FIELDS)}
    return json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_request(
    request: dict[str, Any],
    cluster_private_b64: str,
    shared_dir: Path | None = None,
) -> dict[str, Any]:
    """Sign a bid with the member's cluster key.

    The cluster key, not the operational one. At this point the candidate has
    just generated the operational key the bid carries, so signing the bid with
    that key would be offering a key and proving it with itself — circular, and
    it would let a bid stand on a key no membership had seen yet.
    """
    authz = load_authz(shared_dir)
    try:
        key = authz.private_key_from_b64(cluster_private_b64)
        signature_b64 = authz.sign_bytes(key, canonical_request(request))
    except Exception as exc:
        raise ElectionError(REASON_MALFORMED, f"cannot sign election request: {exc}") from exc
    return {**request, "signature_b64": signature_b64}


def verify_request(
    request: dict[str, Any],
    members: list[dict[str, Any]],
    shared_dir: Path | None = None,
) -> tuple[bool, str]:
    """Check a bid's signature against the member's cluster key and its key's shape."""
    authz = load_authz(shared_dir)
    try:
        message = canonical_request(request)
    except ElectionError as exc:
        return False, exc.reason
    member = {m["node_id"]: m for m in members}.get(request.get("node_id"))
    if member is None:
        return False, REASON_NOT_A_MEMBER
    if not request.get("signature_b64"):
        return False, REASON_MISSING_FIELD
    try:
        public_key = authz.public_key_from_b64(member["cluster_pubkey"])
        if not authz.verify_signature(public_key, request["signature_b64"], message):
            return False, REASON_BAD_SIGNATURE
    except Exception:
        return False, REASON_BAD_SIGNATURE
    try:
        # The bid exists to name a usable operational key, so reject one that
        # will not parse now rather than all signatures later.
        authz.public_key_from_b64(request["operational_pubkey_b64"])
    except Exception:
        return False, REASON_MALFORMED
    return True, "ok"


# --- the root -------------------------------------------------------------------


def build_root(
    request: dict[str, Any],
    tally_result: dict[str, Any],
    members: list[dict[str, Any]],
    now: datetime | None = None,
    previous_root_id: str = "",
    epoch: int = 0,
    removal_proofs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The unsigned root a unanimous tally produces.

    `previous_root_id` links this root to the root it supersedes (the empty
    string for a cluster's first root). A re-formation through the election
    ceremony passes the held root's id here; the consensus module refuses any
    supersession that does not name the root in force, so omitting it only
    ever yields a genesis root.

    `epoch` is the signed, clock-free height of the root (0 at genesis, the
    parent's epoch + 1 for a re-formation). `removal_proofs` certifies a
    reduced-membership re-formation: they are carried alongside the root but are
    not one of the signed fields (each is independently signed), so the members'
    co-signatures stay small while `verify_root` still refuses a chained root
    whose dropped set is not exactly what the proofs evidence.

    `master_pubkey` is the candidate's operational key from its signed bid —
    the point of the whole ceremony: the root is what binds a key nobody else
    has into the identity every node will trust afterwards. The consensus
    module owns the field set (`ROOT_SIGNED_FIELDS`) and the member shape
    (`ROOT_MEMBER_FIELDS`); this only supplies values, so a field added there
    cannot be quietly omitted here. Members arrive as the membership file's
    full records — a root that named only ids could not be verified against
    the cluster keys it is supposed to bind.
    """
    consensus = load_consensus()
    formed_at = (now or datetime.now(timezone.utc)).isoformat()
    unsigned = {
        "version": consensus.SCHEMA_VERSION,
        "nonce": secrets.token_hex(16),
        "formed_at": formed_at,
        "members": list(members),
        "master_node_id": request["node_id"],
        "master_pubkey": request["operational_pubkey_b64"],
        "previous_root_id": previous_root_id,
        "epoch": epoch,
    }
    missing = [field for field in consensus.ROOT_SIGNED_FIELDS if field not in unsigned]
    if missing:
        raise ElectionError(
            REASON_ROOT_UNUSABLE,
            "consensus expects fields this builder does not produce: " + ", ".join(missing),
        )
    # Prove it is buildable before anyone signs it: a root that fails
    # canonical_root now would fail at every one of the co-signers.
    consensus.canonical_root(unsigned)
    if tally_result.get("master_node_id") != unsigned["master_node_id"]:
        raise ElectionError(REASON_ROOT_UNUSABLE, "tally and root disagree about the winner")
    if removal_proofs:
        unsigned["removal_proofs"] = [dict(proof) for proof in removal_proofs]
    return unsigned


# --- the exchange ---------------------------------------------------------------


class ElectionExchange:
    """Collects bids, ballots and root signatures; never holds a private key.

    All mutation happens under a plain lock: members posting over
    loopback race only on the order of milliseconds, and a tally computed
    across an interleaved vote insertion is the one thing here that would be
    silently wrong rather than obviously wrong.
    """

    def __init__(
        self,
        members: list[dict[str, Any]],
        shared_dir: Path | None = None,
        clock: Callable[[], datetime] | None = None,
        election_id: str = DEFAULT_ELECTION_ID,
        previous_root_id: str = "",
        epoch: int = 0,
        removal_proofs: list[dict[str, Any]] | None = None,
    ) -> None:
        self.shared_dir = Path(shared_dir) if shared_dir else DEFAULT_SHARED_DIR
        self.consensus = load_consensus(self.shared_dir)
        self.members = members
        self.member_ids = {member["node_id"] for member in members}
        self.members_by_id = {member["node_id"]: member for member in members}
        self.election_id = election_id
        self.previous_root_id = previous_root_id
        self.epoch = epoch
        self.removal_proofs = [dict(proof) for proof in (removal_proofs or [])]
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.requests: dict[str, dict[str, Any]] = {}
        self.votes: dict[str, dict[str, Any]] = {}
        self.signatures: dict[str, str] = {}
        self.root: dict[str, Any] | None = None
        self.tally_result: dict[str, Any] | None = None
        self.formed_at: str | None = None
        self.errors: dict[str, str] = {}
        self._lock = threading.Lock()

    # -- state -----------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_locked()

    def _status_locked(self) -> dict[str, Any]:
        root = self.root
        signed = len(self.signatures) if root is not None else 0
        if root is None:
            if self.tally_result is None:
                state = "collecting"
            elif self.tally_result.get("agreed"):
                # Tally agreed, so what is missing is the winner's bid.
                state = "awaiting_operational_key"
            else:
                # The tally already ran and nobody agreed. Saying
                # awaiting_operational_key here would imply a bid could still
                # rescue this election; it cannot.
                state = "no_agreement"
        elif len(self.signatures) < len(self.members):
            state = "awaiting_signatures"
        else:
            state = "formed"
        status: dict[str, Any] = {
            "ok": True,
            "state": state,
            "election_id": self.election_id,
            "members": sorted(self.member_ids),
            "bids": sorted(self.requests),
            "votes": sorted(self.votes),
            "signatures": sorted(self.signatures),
            "signatures_signed": signed,
            "signatures_required": len(self.members),
            "master_node_id": (root.get("master_node_id") if root else None),
            # Root carries whatever signatures exist so a member can fetch it,
            # verify what is there and add its own; `root_bytes` ignores them.
            "root": ({**root, "signatures": dict(self.signatures)} if root is not None else None),
            "root_id": (self.consensus.root_id(root) if root else None),
        }
        return status

    # -- ballots ---------------------------------------------------------------

    def submit_request(self, request: dict[str, Any]) -> dict[str, Any]:
        """Accept one bid per member. Re-filing the identical bid is idempotent."""
        with self._lock:
            if not isinstance(request, dict):
                raise ElectionError(REASON_MALFORMED, "request is not an object")
            node_id = request.get("node_id")
            if not isinstance(node_id, str) or not node_id:
                raise ElectionError(REASON_MISSING_FIELD, "request has no node_id")
            if node_id not in self.member_ids:
                raise ElectionError(REASON_NOT_A_MEMBER, f"{node_id} is not a member")
            existing = self.requests.get(node_id)
            if existing is not None:
                if canonical_request(existing) == canonical_request(request):
                    return self._status_locked()
                raise ElectionError(
                    REASON_BID_ALREADY_FILED,
                    f"{node_id} already filed a different election request",
                )
            ok, reason = verify_request(request, self.members, self.shared_dir)
            if not ok:
                raise ElectionError(reason, f"bid from {node_id} rejected")
            self.requests[node_id] = request
            self._maybe_tally_locked()
            self._maybe_form_root_locked()
            return self._status_locked()

    def submit_vote(self, vote: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if not isinstance(vote, dict):
                raise ElectionError(REASON_MALFORMED, "vote is not an object")
            if vote.get("election_id") != self.election_id:
                raise ElectionError(
                    REASON_WRONG_ELECTION_ID,
                    f"expected {self.election_id!r}, got {vote.get('election_id')!r}",
                )
            node_id = vote.get("node_id")
            if node_id not in self.member_ids:
                raise ElectionError(REASON_NOT_A_MEMBER, f"{node_id} is not a member")
            existing = self.votes.get(node_id)
            if existing is not None:
                if existing.get("candidate_node_id") == vote.get("candidate_node_id"):
                    # Same choice, new nonce: one member, one vote, already counted.
                    # Idempotent so an honest retry is not read as treachery.
                    return self._status_locked()
                raise ElectionError(
                    REASON_ALREADY_SIGNED,
                    f"{node_id} already cast a different vote (equivocation refused)",
                )
            if vote.get("candidate_node_id") not in self.member_ids:
                raise ElectionError(
                    REASON_NOT_A_MEMBER,
                    f"vote names {vote.get('candidate_node_id')!r}, not a member",
                )
            try:
                ok, why = self.consensus.verify_vote(vote, self.members)
            except self.consensus.ConsensusError as exc:
                raise ElectionError(REASON_BAD_SIGNATURE, str(exc)) from exc
            if not ok:
                raise ElectionError(REASON_BAD_SIGNATURE, f"vote from {node_id}: {why}")
            self.votes[node_id] = vote
            self._maybe_tally_locked()
            self._maybe_form_root_locked()
            return self._status_locked()

    def submit_signature(self, node_id: str, signature_b64: str, election_id: str | None = None) -> dict[str, Any]:
        """Merge one member's co-signature into the root; form it at n signatures."""
        with self._lock:
            if election_id is not None and election_id != self.election_id:
                raise ElectionError(REASON_WRONG_ELECTION_ID, f"expected {self.election_id!r}")
            if node_id not in self.member_ids:
                raise ElectionError(REASON_NOT_A_MEMBER, f"{node_id} is not a member")
            if self.root is None:
                raise ElectionError(REASON_NO_ROOT_YET, "no root exists yet to co-sign")
            existing = self.signatures.get(node_id)
            if existing is not None:
                if existing == signature_b64:
                    return self._status_locked()
                raise ElectionError(
                    REASON_ALREADY_SIGNED,
                    f"{node_id} already co-signed a different signature",
                )
            if not isinstance(signature_b64, str) or not signature_b64:
                raise ElectionError(REASON_MISSING_FIELD, "no signature_b64")
            # Verify this one signature on its own before storing it.
            # `verify_root` checks members-before-signatures, so a bad early
            # signature would hide behind "missing_signature" until all members
            # arrived — and by then honest members had believed the
            # election was done. Same delegated primitives as everywhere else:
            # authz verifies, consensus supplies the bytes.
            authz = load_authz(self.shared_dir)
            try:
                valid = authz.verify_signature(
                    authz.public_key_from_b64(self.members_by_id[node_id]["cluster_pubkey"]),
                    signature_b64,
                    self.consensus.root_bytes(self.root),
                )
            except Exception:
                valid = False
            if not valid:
                raise ElectionError(
                    REASON_BAD_SIGNATURE,
                    f"{node_id}'s signature does not verify against its cluster key",
                )
            self.signatures[node_id] = signature_b64
            if len(self.signatures) >= len(self.members):
                # Belt and braces: everything checked individually, now check
                # the whole — the seal the members' client also runs.
                ok, detail = self.consensus.verify_root({**self.root, "signatures": dict(self.signatures)})
                if not ok:
                    del self.signatures[node_id]
                    raise ElectionError(REASON_ROOT_UNUSABLE, detail)
            self._maybe_form_root_locked()
            return self._status_locked()

    # -- transitions -----------------------------------------------------------

    def _maybe_tally_locked(self) -> None:
        """Tally once, as soon as every member has voted."""
        if self.tally_result is not None or len(self.votes) < len(self.members):
            return
        self.tally_result = self.consensus.tally(list(self.votes.values()), self.members, self.election_id)

    def _maybe_form_root_locked(self) -> None:
        """Build the root when the tally agreed and the winner has bid; seal it at n signatures."""
        if self.root is not None:
            if len(self.signatures) >= len(self.members):
                self.formed_at = self.formed_at or self._clock().isoformat()
            return
        if self.tally_result is None:
            return
        if not self.tally_result.get("agreed"):
            return
        winner = self.tally_result.get("master_node_id")
        request = self.requests.get(winner)  # type: ignore[arg-type]
        if request is None:
            return  # winner has not bid yet: awaiting_operational_key
        self.root = build_root(
            request,
            self.tally_result,
            list(self.members),
            now=self._clock(),
            previous_root_id=self.previous_root_id,
            epoch=self.epoch,
            removal_proofs=self.removal_proofs,
        )
        if len(self.signatures) >= len(self.members):
            self.formed_at = self._clock().isoformat()

    @property
    def formed(self) -> bool:
        with self._lock:
            return self.root is not None and len(self.signatures) >= len(self.members)


# --- HTTP -----------------------------------------------------------------------


class _Handler(_HTTP.TimeoutHandler):
    """Four endpoints, all of them validated before they mutate anything.

    The contract's *Exchange* section specifies these shapes; anything that
    fails validation answers with a JSON body carrying a stable `reason` so a
    member can distinguish a refusal from an outage without parsing prose.
    """

    server_version = "sparknet-election/1"
    exchange: ElectionExchange

    def log_message(self, fmt: str, *args: Any) -> None:
        return  # loopback service; a poll every 50 ms would drown any log

    def _read_json(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > 1_048_576:
            raise ElectionError(REASON_MALFORMED, "empty or oversized body")
        try:
            return json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise ElectionError(REASON_MALFORMED, f"body is not JSON: {exc}") from exc

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _refuse(self, exc: ElectionError) -> None:
        if exc.reason in _CONFLICT_REASONS:
            code = HTTP_CONFLICT
        elif exc.reason in _FORBIDDEN_REASONS:
            code = HTTP_FORBIDDEN
        else:
            code = HTTP_BAD_REQUEST
        self._send(code, exc.payload())

    def do_GET(self) -> None:
        exchange = self.server.exchange  # type: ignore[attr-defined]
        if self.path in ("/election/status", "/election/root"):
            try:
                status = exchange.status()
            except ElectionError as exc:
                self._refuse(exc)
                return
            if status.get("root") is None and self.path == "/election/root":
                self._refuse(ElectionError(REASON_NO_ROOT_YET, "no root has formed"))
                return
            self._send(200, status)
            return
        self._send(404, {"ok": False, "reason": REASON_MALFORMED, "detail": self.path})

    def do_POST(self) -> None:
        exchange = self.server.exchange  # type: ignore[attr-defined]
        try:
            body = self._read_json()
            if self.path == "/election/request":
                payload = exchange.submit_request(body)
            elif self.path == "/election/vote":
                payload = exchange.submit_vote(body)
            elif self.path == "/election/root-signature":
                if not isinstance(body, dict):
                    raise ElectionError(REASON_MALFORMED, "body is not an object")
                payload = exchange.submit_signature(
                    body.get("node_id"),
                    body.get("signature_b64"),
                    body.get("election_id"),
                )
            else:
                self._send(
                    404,
                    {"ok": False, "reason": REASON_MALFORMED, "detail": self.path},
                )
                return
        except ElectionError as exc:
            self._refuse(exc)
            return
        except Exception as exc:
            # The reason stays stable; the exception names internals a member
            # has no right to see. Log it where only an operator will read it.
            print(f"[election] internal error on {self.path}: {exc!r}", file=sys.stderr)
            self._send(
                500,
                {"ok": False, "reason": REASON_MALFORMED, "detail": "internal error"},
            )
            return
        self._send(200, payload)


def _load_held_root(path: Path) -> dict[str, Any]:
    """Read a held root from a file — either a bare root or a `root` document.

    A node's held root lives as `{"root": {...}, "root_id": ...}` (what
    `accept_root` writes), but a bare root dict is also accepted so a test or an
    operator can point `serve` at a root directly.
    """
    try:
        document = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ElectionError(REASON_MALFORMED, f"held root unreadable: {exc}") from exc
    root = document.get("root") if isinstance(document, dict) else None
    if not isinstance(root, dict):
        root = document if isinstance(document, dict) else None
    if not isinstance(root, dict) or "members" not in root:
        raise ElectionError(REASON_MALFORMED, f"{path} is not a root document")
    return root


def serve(
    members_path: Path,
    bind: str = DEFAULT_BIND,
    port: int = DEFAULT_PORT,
    shared_dir: Path | None = None,
    clock: Callable[[], datetime] | None = None,
    election_id: str = DEFAULT_ELECTION_ID,
    trust_root: Path | None = None,
    removal_proofs: Path | None = None,
    ready: Callable[[], None] | None = None,
) -> None:
    """Run the exchange until interrupted.

    `trust_root` is the root in force: supplying it turns this exchange into a
    **re-formation** — the formed root chains to it by `previous_root_id` and
    takes the next `epoch`. Omit it for a genesis election. `removal_proofs` is
    a JSON list of removal proofs carried onto a reduced-membership root, so a
    cluster that dropped a member forms a child the verifier will accept (the
    survivors are the `members_path` roster; the dropped member is simply not in
    it). The consensus module checks that the dropped set equals the evidenced
    set exactly, so proofs for a member who is not dropped are refused.

    `ready` is called once the socket is listening, so a test can know when to
    start its members without sleeping on a guess.
    """
    previous_root_id = ""
    epoch = 0
    proofs: list[dict[str, Any]] | None = None
    if trust_root is not None:
        held = _load_held_root(trust_root)
        consensus = load_consensus(shared_dir)
        previous_root_id = consensus.root_id(held)
        epoch = int(held.get("epoch", 0)) + 1
    if removal_proofs is not None:
        try:
            proofs = json.loads(Path(removal_proofs).read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ElectionError(REASON_MALFORMED, f"removal proofs unreadable: {exc}") from exc
        if not isinstance(proofs, list):
            raise ElectionError(REASON_MALFORMED, "removal proofs must be a JSON list")
    exchange = ElectionExchange(
        load_members(members_path),
        shared_dir=shared_dir,
        clock=clock,
        election_id=election_id,
        previous_root_id=previous_root_id,
        epoch=epoch,
        removal_proofs=proofs,
    )
    server = ThreadingHTTPServer((bind, port), _Handler)
    server.exchange = exchange  # type: ignore[attr-defined]
    if ready is not None:
        ready()
    try:
        server.serve_forever(poll_interval=0.05)
    finally:
        server.server_close()


# --- client ---------------------------------------------------------------------
#
# The member side. Every function here runs in a member's own process, which is
# where the cluster keys live; nothing below ever sends a private key anywhere.


def _url(base: str, path: str) -> str:
    return base.rstrip("/") + path


def _call(
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """POST `payload` or GET when it is None, mapping failures to ElectionError.

    A refusal and an outage must not look alike to the caller: an HTTPError
    carries the exchange's stable `reason`, anything else is `unreachable`, and
    `member` retries only the latter.
    """
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"} if data else {},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            document = json.loads(raw)
        except json.JSONDecodeError:
            raise ElectionError(REASON_MALFORMED, f"HTTP {exc.code}: {raw[:200]}") from exc
        raise ElectionError(
            document.get("reason", REASON_MALFORMED),
            str(document.get("detail", "")),
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        raise ElectionError(REASON_UNREACHABLE, str(exc)) from exc


def status_of(base: str, timeout: float = 5.0) -> dict[str, Any]:
    return _call(_url(base, "/election/status"), None, timeout)


def wait_for(
    base: str,
    predicate: Callable[[dict[str, Any]], bool],
    wait_seconds: float,
    interval: float = POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Poll status until `predicate` holds; the only place `member` sleeps.

    `time.sleep` appears nowhere else in this module on purpose: the protocol
    has no deadline, only this transport-level patience test, and a reader
    grepping for `sleep` should find exactly one — this one.
    """
    deadline = time.monotonic() + wait_seconds
    last: dict[str, Any] = {}
    while True:
        try:
            last = status_of(base)
            if predicate(last):
                return last
        except ElectionError as exc:
            if exc.reason != REASON_UNREACHABLE:
                raise
        if time.monotonic() >= deadline:
            raise ElectionError(
                REASON_TIMEOUT,
                f"no progress after {wait_seconds}s; last state {last.get('state', 'unreachable')!r}",
            )
        time.sleep(interval)


def cast_request(
    base: str,
    node_id: str,
    key_dir: Path,
    shared_dir: Path | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """File this node's bid: a fresh operational key, signed with the cluster key.

    The operational key is created on demand here, matching the contract: the
    candidate generates its operational keypair. Creating it earlier would
    leave a key sitting in a key directory that never got elected.
    """
    authz = load_authz(shared_dir)
    cluster_private, _ = read_keypair(key_dir, "cluster", authz)
    _, operational_public, _ = ensure_keypair(key_dir, "operational", authz)
    request = {
        "node_id": node_id,
        "operational_pubkey_b64": operational_public,
        "nonce": secrets.token_hex(16),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    signed = sign_request(request, cluster_private, shared_dir)
    return _call(_url(base, "/election/request"), signed, timeout)


def cast_vote(
    base: str,
    node_id: str,
    candidate: str,
    election_id: str,
    key_dir: Path,
    shared_dir: Path | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Cast this node's ballot: signed by the cluster key, counted by consensus."""
    authz = load_authz(shared_dir)
    cluster_private, _ = read_keypair(key_dir, "cluster", authz)
    consensus = load_consensus(shared_dir)
    vote = {
        "node_id": node_id,
        "candidate_node_id": candidate,
        "election_id": election_id,
        "nonce": secrets.token_hex(16),
        "cast_at": datetime.now(timezone.utc).isoformat(),
    }
    signed = consensus.sign_vote(vote, cluster_private)
    return _call(_url(base, "/election/vote"), signed.as_dict(), timeout)


def sign_root(
    base: str,
    node_id: str,
    candidate: str,
    election_id: str,
    key_dir: Path,
    shared_dir: Path | None = None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Co-sign the formed root — after refusing any root naming someone else.

    This check is the member's half of unanimity. The exchange built the root
    from a tally this member voted in, but a member that signs whatever the
    exchange hands it has delegated its vote: `--expect-master` pins the
    signature to the candidate the ballot named, so two honest votes plus one
    lying exchange get two refusals, not a master.
    """
    consensus = load_consensus(shared_dir)
    status = status_of(base, timeout)
    root = status.get("root")
    if not isinstance(root, dict):
        raise ElectionError(REASON_NO_ROOT_YET, "no root has formed yet")
    try:
        members = {m["node_id"] for m in root["members"]}
    except (KeyError, TypeError) as exc:
        raise ElectionError(REASON_ROOT_UNUSABLE, f"root members unreadable: {exc}") from exc
    if node_id not in members:
        raise ElectionError(REASON_NOT_A_MEMBER, f"{node_id} is not named by this root")
    if root.get("master_node_id") != candidate:
        raise ElectionError(
            REASON_UNEXPECTED_MASTER,
            f"root names {root.get('master_node_id')!r} but this member voted for {candidate!r}; refusing to co-sign",
        )
    try:
        consensus.canonical_root(root)
    except consensus.ConsensusError as exc:
        raise ElectionError(REASON_ROOT_UNUSABLE, str(exc)) from exc
    if node_id in (root.get("signatures") or {}):
        return status  # already co-signed: idempotent
    authz = load_authz(shared_dir)
    cluster_private, _ = read_keypair(key_dir, "cluster", authz)
    try:
        signature_map = consensus.sign_root(root, node_id, cluster_private)
    except consensus.ConsensusError as exc:
        raise ElectionError(REASON_ROOT_UNUSABLE, str(exc)) from exc
    return _call(
        _url(base, "/election/root-signature"),
        {
            "node_id": node_id,
            "signature_b64": signature_map[node_id],
            "election_id": election_id,
        },
        timeout,
    )


def accept_root(
    root: dict[str, Any],
    identity_path: Path,
    shared_dir: Path | None = None,
    trust_root: dict[str, Any] | None = None,
    root_out: Path | None = None,
    root_doc: Path | None = None,
) -> dict[str, Any]:
    """Install an elected root on this node — or leave the node a peer.

    The flip is guarded, not spelled out: exactly four fields may change
    (`role`, `role_note`, `operational_key.held`/`root_id`, and the new
    `trust_root` block), and the write is refused outright if anything else
    would move. The no-loss property is not a test someone has to remember to
    run; it is the last thing that happens before the file is replaced.
    """
    consensus = load_consensus(shared_dir)
    authz = load_authz(shared_dir)
    if root_doc is not None and root_out is None:
        root_out = root_doc
    try:
        identity = json.loads(identity_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ElectionError(REASON_MALFORMED, f"identity unreadable: {exc}") from exc

    ok, detail = consensus.verify_root(root, trust=trust_root)
    if not ok:
        raise ElectionError(REASON_ROOT_UNUSABLE, detail)
    try:
        authz.public_key_from_b64(root["master_pubkey"])
    except Exception as exc:
        raise ElectionError(REASON_ROOT_UNUSABLE, f"root's master_pubkey does not parse: {exc}") from exc

    node_id = identity.get("node_id")
    members = {m["node_id"] for m in root["members"]}
    if node_id not in members:
        raise ElectionError(REASON_NOT_A_MEMBER, f"{node_id} is not named by this root")

    root_id = consensus.root_id(root)
    if node_id != root["master_node_id"]:
        # Correct outcome for the two members that stayed peers: verify and
        # report, change nothing, do not fail the ceremony.
        return {
            "accepted": False,
            "reason": "not_elected",
            "detail": f"{node_id} is a member, not the elected master",
            "root_id": root_id,
            "role": identity.get("role"),
        }

    updated = json.loads(json.dumps(identity))  # deep copy, JSON-typed
    if updated.get("role") != "master":
        updated["role"] = "master"
        updated["role_note"] = (
            f"role became 'master' when {node_id} was elected: all "
            f"{len(members)} members co-signed cluster trust root {root_id} "
            f"(formed {root.get('formed_at')}), naming this node's operational "
            f"key. See contracts/consensus-protocol.md."
        )
    operational_key = dict(updated.get("operational_key") or {})
    operational_key["held"] = True
    operational_key["root_id"] = root_id
    updated["operational_key"] = operational_key
    updated["trust_root"] = {
        "root_id": root_id,
        "master_node_id": root["master_node_id"],
        "master_pubkey": root["master_pubkey"],
        "formed_at": root.get("formed_at"),
    }

    # The no-loss guard: nothing outside the four permitted fields may move.
    # Comparing before writing is the only moment this is provable — once the
    # file is replaced, nobody can tell what was lost.
    allowed_top = {"role", "role_note", "operational_key", "trust_root"}
    for key, value in identity.items():
        if key in allowed_top:
            continue
        if updated.get(key) != value:
            raise ElectionError(
                REASON_ROOT_UNUSABLE,
                f"refusing to write: field {key!r} would change under accept",
            )
    if set(updated) - set(identity) - allowed_top:
        raise ElectionError(REASON_ROOT_UNUSABLE, "refusing to write: accept would invent fields")

    tmp = identity_path.with_name(identity_path.name + ".tmp")
    tmp.write_text(json.dumps(updated, indent=2, sort_keys=False) + "\n")
    tmp.replace(identity_path)

    if root_out is not None:
        document = json.loads(root_out.read_text()) if root_out.is_file() else {}
        document["root"] = root
        document["root_id"] = root_id
        tmp_doc = root_out.with_name(root_out.name + ".tmp")
        tmp_doc.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n")
        tmp_doc.replace(root_out)

    return {
        "accepted": True,
        "root_id": root_id,
        "role": updated["role"],
        "master_node_id": root["master_node_id"],
        "identity_path": str(identity_path),
        "root_doc": str(root_doc) if root_doc else None,
    }


def run_member(
    base: str,
    node_id: str,
    candidate: str,
    key_dir: Path,
    identity_path: Path | None = None,
    election_id: str = DEFAULT_ELECTION_ID,
    wait_seconds: float = 30.0,
    shared_dir: Path | None = None,
    root_out: Path | None = None,
    root_doc: Path | None = None,
) -> dict[str, Any]:
    """The full ceremony from one member's seat: bid, vote, wait, co-sign, accept.

    One process per member, deliberately. Votes must come from separate seats at
    the table, and a function that collected them from one process
    would prove nothing about whether a real cluster can actually do this.
    """
    authz = load_authz(shared_dir)
    read_keypair(key_dir, "cluster", authz)  # fail before the exchange sees us
    out: dict[str, Any] = {"node_id": node_id, "candidate": candidate}
    # Resume, don't restart: a second run of the same ceremony finds its bid
    # and ballot already in and leaves them alone. Nonces are fresh per call,
    # so re-posting would read as a different bid and be refused — checking
    # first is what makes an interrupted ceremony pick up where it stopped.
    pre = status_of(base)
    out["request"] = (
        cast_request(base, node_id, key_dir, shared_dir)
        if node_id not in pre.get("bids", [])
        else {"already_filed": True}
    )
    out["vote"] = (
        cast_vote(base, node_id, candidate, election_id, key_dir, shared_dir)
        if node_id not in pre.get("votes", [])
        else {"already_cast": True}
    )
    out["root"] = wait_for(base, lambda s: isinstance(s.get("root"), dict), wait_seconds)
    if out["root"].get("state") != "formed":
        out["co_sign"] = sign_root(base, node_id, candidate, election_id, key_dir, shared_dir)
        out["formed"] = wait_for(base, lambda s: s.get("state") == "formed", wait_seconds)
    else:
        out["formed"] = out["root"]
    root = out["formed"]["root"]
    # The member's refusal invariant, checked here as well as in sign_root:
    # once the root is formed, root-sign is skipped (already co-signed), and a
    # member must still never install a root naming anyone but the candidate
    # its own ballot named. Skipping the signing step must not skip the loyalty
    # check.
    if root.get("master_node_id") != candidate:
        raise ElectionError(
            REASON_UNEXPECTED_MASTER,
            f"formed root names {root.get('master_node_id')!r} but this member "
            f"voted for {candidate!r}; refusing to install it",
        )
    if root_out is None and root_doc is None and identity_path is None:
        return out  # co-signing was the whole errand
    if identity_path is None:
        raise ElectionError(REASON_MALFORMED, "--identity is required to accept a root")
    if root_out is None and root_doc is None:
        root_out = identity_path.with_name("trust-root.json")
    trust = None
    if root_doc is not None and root_doc.is_file():
        held = json.loads(root_doc.read_text()).get("root")
        if isinstance(held, dict) and held.get("nonce") != root.get("nonce"):
            trust = held  # a held root of a different nonce: supersession rules
    out["accept"] = accept_root(root, identity_path, shared_dir, trust, root_out, root_doc)
    return out


# --- command line ----------------------------------------------------------------


def _identity_node_id(path: Path) -> str:
    try:
        node_id = json.loads(path.read_text()).get("node_id")
    except (OSError, json.JSONDecodeError) as exc:
        raise ElectionError(REASON_MALFORMED, f"identity unreadable: {exc}") from exc
    if not isinstance(node_id, str) or not node_id:
        raise ElectionError(REASON_MALFORMED, f"{path} has no node_id")
    return node_id


def _resolve_node_id(args: argparse.Namespace) -> str:
    if args.node_id:
        return args.node_id
    identity = getattr(args, "identity", None)
    if identity is not None:
        return _identity_node_id(identity)
    raise ElectionError(REASON_MALFORMED, "--node-id is required")


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sparknet-election",
        description="The cluster election: bid, vote, co-sign, install a trust root.",
    )
    parser.add_argument("--shared-dir", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("keygen", help="create a cluster keypair in --key-dir")
    p.add_argument("--key-dir", type=Path, required=True)
    p.add_argument("--name", default="cluster")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("serve", help="run the exchange (holds no private key)")
    p.add_argument("--members", type=Path, required=True)
    p.add_argument("--bind", default=DEFAULT_BIND)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--election-id", default=DEFAULT_ELECTION_ID)
    p.add_argument(
        "--trust",
        type=Path,
        default=None,
        help="root in force: turns this into a re-formation chaining to it",
    )
    p.add_argument(
        "--removal-proofs",
        type=Path,
        default=None,
        help="JSON list of removal proofs for a reduced-membership re-formation",
    )

    def member_args(p: argparse.ArgumentParser, with_identity: bool = False) -> None:
        p.add_argument("--url", default=f"http://{DEFAULT_BIND}:{DEFAULT_PORT}")
        p.add_argument("--key-dir", type=Path, required=True)
        p.add_argument("--node-id", default=None)
        if with_identity:
            # Node id from the identity file when --node-id is not spelled out,
            # so a script may pass whichever it already has on hand.
            p.add_argument("--identity", type=Path, default=None)

    p = sub.add_parser("request", help="file this node's bid")
    member_args(p, with_identity=True)

    p = sub.add_parser("vote", help="cast this node's ballot")
    member_args(p, with_identity=True)
    p.add_argument("--candidate", required=True)
    p.add_argument("--election-id", default=DEFAULT_ELECTION_ID)

    p = sub.add_parser("root-sign", help="co-sign the formed root")
    member_args(p, with_identity=True)
    p.add_argument("--expect-master", required=True)
    p.add_argument("--election-id", default=DEFAULT_ELECTION_ID)

    p = sub.add_parser("accept", help="install a formed root on this node")
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--identity", type=Path, required=True)
    p.add_argument("--trust", type=Path, default=None)
    p.add_argument("--root-out", type=Path, default=None)
    p.add_argument("--root-doc", type=Path, default=None)

    p = sub.add_parser("member", help="the whole ceremony, one process")
    member_args(p)
    p.add_argument("--candidate", required=True)
    p.add_argument("--election-id", default=DEFAULT_ELECTION_ID)
    p.add_argument("--identity", type=Path, default=None)
    p.add_argument("--wait-seconds", type=float, default=30.0)
    p.add_argument("--root-out", type=Path, default=None)
    p.add_argument("--root-doc", type=Path, default=None)

    args = parser.parse_args(argv)
    shared_dir = args.shared_dir

    try:
        if args.command == "keygen":
            authz = load_authz(shared_dir)
            _, public_b64, created = ensure_keypair(args.key_dir, args.name, authz, force=args.force)
            payload = {
                "created": created,
                "name": args.name,
                "public": public_b64,
                "private_path": str(key_path(args.key_dir, args.name, True)),
                "public_path": str(key_path(args.key_dir, args.name, False)),
            }
        elif args.command == "serve":
            serve(
                args.members,
                bind=args.bind,
                port=args.port,
                shared_dir=shared_dir,
                election_id=args.election_id,
                trust_root=args.trust,
                removal_proofs=args.removal_proofs,
            )
            payload = {"stopped": True}
        elif args.command == "request":
            payload = cast_request(args.url, _resolve_node_id(args), args.key_dir, shared_dir)
        elif args.command == "vote":
            payload = cast_vote(
                args.url,
                _resolve_node_id(args),
                args.candidate,
                args.election_id,
                args.key_dir,
                shared_dir,
            )
        elif args.command == "root-sign":
            payload = sign_root(
                args.url,
                _resolve_node_id(args),
                args.expect_master,
                args.election_id,
                args.key_dir,
                shared_dir,
            )
        elif args.command == "accept":
            root_document = json.loads(args.root.read_text())
            if isinstance(root_document.get("root"), dict):
                root_document = root_document["root"]
            trust = None
            if args.trust is not None:
                trust_document = json.loads(args.trust.read_text())
                trust = trust_document.get("root") if isinstance(trust_document.get("root"), dict) else trust_document
            payload = accept_root(
                root_document,
                args.identity,
                shared_dir,
                trust,
                args.root_out,
                args.root_doc,
            )
        else:  # member
            payload = run_member(
                args.url,
                _resolve_node_id(args),
                args.candidate,
                args.key_dir,
                identity_path=args.identity,
                election_id=args.election_id,
                wait_seconds=args.wait_seconds,
                shared_dir=shared_dir,
                root_out=args.root_out,
                root_doc=args.root_doc,
            )
    except ElectionError as exc:
        print(json.dumps(exc.payload(), indent=2, sort_keys=True))
        return 1
    except (OSError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"ok": False, "reason": REASON_MALFORMED, "detail": str(exc)},
                indent=2,
                sort_keys=True,
            )
        )
        return 1

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
