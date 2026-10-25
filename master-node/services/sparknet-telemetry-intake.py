#!/usr/bin/env python3
"""The Master's peer-intake listener — telemetry evidence, pushed not intercepted.

Phase 4 is Master observability *without touching the data path*: peers talk to each
other directly and the Master is authority-plane only, so monitoring means signed
evidence the peer **pushes**, never a Master that sits in the middle. This is the
socket that receives it. Design: ``MASTER_OBSERVABILITY_DESIGN.md`` (fabric Step 69);
contract: ``contracts/telemetry-schema.json``.

It re-scopes **8090**, which ``contracts/ports.json`` recorded as the superseded
``master-instant-push`` listener and Master Step 7 left open ("survives / re-scoped /
retired"). The instant-push purpose is retired — Step 6 pushes the signed registry to
each peer's guard on 9090, so a Master-side ACL-push listener was never needed. What
8090 becomes is the one **peer→Master intake** surface, carrying message *families* as
routes exactly as the peer's guard 9090 carries three: ``POST /api/v1/telemetry`` now,
and Step 68C's RFI request route joins it rather than founding a second listener.

Attribution is the authenticated overlay (Step 68A's Option B), not a signature
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nothing in the fabric binds a peer fingerprint to a node signing public key, so a
peer→Master body is *not* signed — a signature the Master cannot verify is theatre.
WireGuard already authenticates each peer: the Master's ``wg0`` holds one stanza per
node, keyed by ``wireguard_public_key_b64``, ``AllowedIPs`` = its overlay ``/32``. So
the source address of a packet the Master receives **is** an authenticated identity,
and the Master's registry maps ``overlay_ipv4 → fingerprint``. This listener derives
the sender's fingerprint from the source address and refuses a report whose
``peer_fingerprint`` field disagrees — a peer cannot report as another peer.

The ``telemetry`` capability is enforced **here**, on receipt
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Phase 4's "wire the existing telemetry capability" is concrete: a source is accepted
only if its registry entry is present, **not revoked**, and **holds ``telemetry``**.
A peer the registry does not grant it gets ``403 capability_missing`` before the body
is parsed. This is the push complement to the admin console's *pull* feed
(``list_events`` over ``admin-supervise``); the capability split is the point —
``telemetry`` is peer-held, ``admin-supervise`` is Master-held.

Telemetry carries no authority
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A report is recorded as evidence and acknowledged. Nothing here signs, grants,
revokes, escalates, widens a permission or approves anything, and the ``kind``
vocabulary (``status``, ``metrics``, ``liveness``, ``checkpoint_anchor``,
``inbox_alert``) has no authority verb in it. The Master observes; it does not act.

Usage::

    sparknet-telemetry-intake.py --serve --bind 10.100.0.1 --port 8090
    sparknet-telemetry-intake.py --check
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROLE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ROLE_ROOT.parent
AUTHZ_PATH = REPO_ROOT / "shared" / "sparknet-authz.py"

DEFAULT_BIND = "10.100.0.1"
DEFAULT_PORT = 8090
DEFAULT_REGISTRY = ROLE_ROOT / "manifests" / "node-authorizations.json"
MAX_BODY = 256 * 1024

#: Refusal reason -> HTTP status. `off_overlay`, `revoked` and `capability_missing`
#: are the source gate's; the rest come from ``authz.verify_telemetry_report``.
#: Fixed strings, so an operator greps a log for a stable code.
REFUSAL_STATUS = {
    "off_overlay": 403,
    "revoked": 403,
    "capability_missing": 403,
    "malformed": 400,
    "wrong_peer": 403,
    "expired": 403,
    "not_yet_valid": 403,
    "replayed_nonce": 409,
}


def _load_authz() -> Any:
    if "sparknet_intake_authz" in sys.modules:
        return sys.modules["sparknet_intake_authz"]
    spec = importlib.util.spec_from_file_location("sparknet_intake_authz", AUTHZ_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the authz implementation from {AUTHZ_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["sparknet_intake_authz"] = module
    spec.loader.exec_module(module)
    return module


authz = _load_authz()


class IntakeError(Exception):
    """A refusal the listener can report without echoing report content."""


# --- the peer directory: overlay source -> fingerprint ------------------------


def _bare(address: str) -> str:
    """`10.100.0.9/32` -> `10.100.0.9`; a URL wants the bare address."""
    return str(address or "").split("/", 1)[0].strip()


def load_registry(path: Path | str) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = data.get("authorizations") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise IntakeError(f"{path} has no authorizations[] list")
    return entries


class PeerDirectory:
    """Maps an overlay source address to the registered peer that holds it.

    Built from the Master's own signed registry, so attribution is only as current
    as the registry the Master signed — a revoked peer is refused by the same read
    that would otherwise attribute it.
    """

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self._by_address: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            address = _bare(entry.get("overlay_ipv4"))
            fingerprint = entry.get("fingerprint")
            if address and isinstance(fingerprint, str) and fingerprint:
                self._by_address[address] = entry

    @classmethod
    def from_registry(cls, path: Path | str) -> PeerDirectory:
        return cls(load_registry(path))

    def attribute(self, client_address: str) -> tuple[str | None, str]:
        """(fingerprint, "") for an accepted source, else (None, reason).

        The order is the contract's: is this a registered peer at all, is it still
        trusted, may it push telemetry. Each refusal is a distinct code so an
        operator can tell an unknown source from a revoked one from an ungranted one.
        """
        entry = self._by_address.get(_bare(client_address))
        if entry is None:
            return None, "off_overlay"
        if entry.get("revoked"):
            return None, "revoked"
        capabilities = entry.get("capabilities")
        if not isinstance(capabilities, list) or "telemetry" not in capabilities:
            return None, "capability_missing"
        return str(entry["fingerprint"]), ""


# --- the evidence spool -------------------------------------------------------


def default_spool() -> Path:
    """Where received telemetry is recorded. Telemetry goes to ``/mnt/log`` per the
    fabric's canonical placement (not the vault, not ``~/``), beside the reflex
    broker's audit; ``SPARKNET_TELEMETRY_SPOOL`` overrides it."""
    env = os.environ.get("SPARKNET_TELEMETRY_SPOOL", "").strip()
    return Path(env) if env else Path("/mnt/log/sparknet-telemetry.jsonl")


def record_report(spool: Path, report: dict[str, Any], *, source: str) -> bool:
    """Append one accepted report (0600, one object per line). Never raises.

    The spool is the evidence the admin console's feed surfaces (69G); a report the
    Master cannot spool is still acknowledged, because refusing an arrived report
    over a disk fault would punish the peer for the Master's problem.
    """
    row = {"source": _bare(source), **report}
    try:
        spool.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with spool.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            os.chmod(spool, 0o600)
    except OSError as exc:
        print(f"telemetry-intake: spool write failed: {exc}", file=sys.stderr)
        return False
    return True


def spool_nonces(spool: Path) -> set[str]:
    """The nonces already recorded, so a re-pushed report is a replay not a dupe.

    Read once at start and kept in memory thereafter; a corrupt row is skipped.
    Rotating the spool is a future concern — telemetry is evidence, not authority,
    so the cost of growth is disk, not trust.
    """
    seen: set[str] = set()
    if not spool.exists():
        return seen
    try:
        lines = spool.read_text(encoding="utf-8").splitlines()
    except OSError:
        return seen
    for line in lines:
        line = line.strip()
        if not line:
            continue
        with contextlib.suppress(json.JSONDecodeError):
            row = json.loads(line)
            nonce = row.get("nonce") if isinstance(row, dict) else None
            if isinstance(nonce, str) and nonce:
                seen.add(nonce)
    return seen


# --- HTTP surface -------------------------------------------------------------


def _json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    server_version = "sparknet-telemetry-intake"
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"telemetry-intake: {self.address_string()} {fmt % args}", file=sys.stderr)

    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = _json_bytes(body)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(200, {"ok": True})
            return
        self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/api/v1/telemetry":
            self._send(404, {"error": "not_found"})
            return

        client = self.client_address[0]
        # Attribution first, before the body is read: an unregistered, revoked or
        # ungranted source is refused without parsing anything it sent.
        fingerprint, reason = self.server.directory.attribute(client)  # type: ignore[attr-defined]
        if fingerprint is None:
            self._send(REFUSAL_STATUS.get(reason, 403), {"error": reason})
            return

        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            self._send(400, {"error": "malformed"})
            return
        if length <= 0 or length > MAX_BODY:
            self._send(413 if length > MAX_BODY else 400, {"error": "malformed"})
            return
        try:
            report = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, {"error": "malformed"})
            return

        seen = self.server.seen_nonces  # type: ignore[attr-defined]
        ok, verify_reason = authz.verify_telemetry_report(report, expected_fingerprint=fingerprint, seen_nonces=seen)
        if not ok:
            self._send(REFUSAL_STATUS.get(verify_reason, 400), {"error": verify_reason})
            return

        spool = self.server.spool  # type: ignore[attr-defined]
        spooled = record_report(spool, report, source=client)
        seen.add(str(report["nonce"]))
        self._send(
            200,
            {"status": "recorded", "kind": report["kind"], "nonce": report["nonce"], "spooled": spooled},
        )


def serve(
    bind: str,
    port: int,
    *,
    directory: PeerDirectory,
    spool: Path,
    seen_nonces: set[str] | None = None,
) -> None:
    if bind != DEFAULT_BIND and bind not in {"127.0.0.1", "::1"}:
        raise IntakeError("refuse to bind a non-overlay address (the intake is overlay-only)")
    server = ThreadingHTTPServer((bind, port), _Handler)
    server.directory = directory  # type: ignore[attr-defined]
    server.spool = spool  # type: ignore[attr-defined]
    server.seen_nonces = seen_nonces if seen_nonces is not None else spool_nonces(spool)  # type: ignore[attr-defined]
    print(f"telemetry-intake: listening on {bind}:{port}", file=sys.stderr)
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sparknet Master peer-intake listener (telemetry evidence)")
    parser.add_argument("--serve", action="store_true", help="run the HTTP listener")
    parser.add_argument("--check", action="store_true", help="print posture and exit")
    parser.add_argument("--bind", default=os.environ.get("SPARKNET_TELEMETRY_BIND", DEFAULT_BIND))
    parser.add_argument("--port", type=int, default=int(os.environ.get("SPARKNET_TELEMETRY_PORT", DEFAULT_PORT)))
    parser.add_argument("--registry", default=os.environ.get("SPARKNET_TELEMETRY_REGISTRY", str(DEFAULT_REGISTRY)))
    parser.add_argument("--spool", default=os.environ.get("SPARKNET_TELEMETRY_SPOOL", ""))
    args = parser.parse_args(argv)

    spool = Path(args.spool) if args.spool else default_spool()

    if args.check:
        print(
            json.dumps(
                {
                    "service": "telemetry-intake",
                    "bind": args.bind,
                    "port": args.port,
                    "registry": args.registry,
                    "spool": str(spool),
                    "route": "/api/v1/telemetry",
                    "authority": "none — records evidence, never signs/grants/revokes",
                },
                indent=2,
            )
        )
        return 0

    if not args.serve:
        parser.error("choose --serve or --check")

    try:
        directory = PeerDirectory.from_registry(args.registry)
    except (IntakeError, OSError, json.JSONDecodeError) as exc:
        print(f"telemetry-intake: cannot load the registry: {exc}", file=sys.stderr)
        return 2
    try:
        serve(args.bind, args.port, directory=directory, spool=spool)
    except (IntakeError, OSError) as exc:
        print(f"telemetry-intake: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
