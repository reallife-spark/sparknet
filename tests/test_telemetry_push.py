"""Step 70A: the peer telemetry pusher, proven against a real loopback intake.

The pusher is a separate process in production, so the end-to-end tests run it
as one and let the Master's own 69C handler accept the report over a socket.
That is the only shape that proves the DoD's "the intake accepts it end to end":
a unit test of ``build_reports`` would not catch a field-set or route mismatch
between the two sides, and the two sides are the contract.

**Fabric-level, not peer-level, on purpose.** The test loads the Master's intake,
which a peer bundle deliberately does not carry — a peer bundle is the minimal
deployment, and shipping authority-plane code in it would be the overclaim the
bundle split exists to prevent. The same reason ``test_rfi_transport.py`` lives
under ``master-node/`` and drives the peer guard: a cross-role integration test
belongs where both roles are present. The pusher's own unit wiring stays here too
so one file states the whole 70A contract.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sparknet_loader import load_by_path

FABRIC_ROOT = Path(__file__).resolve().parent.parent
ROLE_ROOT = FABRIC_ROOT / "peer-node"
PUSH_PATH = ROLE_ROOT / "services" / "sparknet-telemetry-push.py"
INTAKE_PATH = FABRIC_ROOT / "master-node" / "services" / "sparknet-peer-intake.py"
ROUTE = "/api/v1/telemetry"


def _load(name: str, path: Path) -> ModuleType:
    return load_by_path(name, path)


push = _load("sparknet_telemetry_push", PUSH_PATH)
intake = _load("sparknet_telemetry_intake_for_push", INTAKE_PATH)
authz = push._load_authz()
assert authz is not None


def _fixture_vault(
    tmp_path: Path,
    *,
    capabilities: tuple[str, ...] = ("telemetry",),
    revoked: bool = False,
    anchor: str = "10.100.0.99",
) -> tuple[Path, str]:
    """A peer vault with a real Master-signed registry entry.

    The signature is minted by the shared code, not hand-rolled: a fixture that
    only *looked* like a registry would let the pusher and the intake agree on a
    shape the Master never signs.
    """
    vault = tmp_path / "peer"
    (vault / "manifests" / "keys").mkdir(parents=True)
    identity = {
        "node_id": "sparknet-node-0007",
        "role": "peer",
        "wireguard_public_key_b64": "dGVzdC13aXJlZ3VhcmQta2V5",
        "overlay_ipv4": "10.100.0.7/32",
        "requested_capabilities": ["telemetry", "p2p-sync"],
    }
    private_b64, public_b64 = authz.generate_keypair()
    (vault / "manifests" / "keys" / "master-ed25519.pub.b64").write_text(public_b64 + "\n")
    private_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))
    entry = authz.sign_authorization(identity, private_key, list(capabilities), revoked=revoked)
    (vault / "manifests" / "node-identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    (vault / "manifests" / "node-authorizations.json").write_text(
        json.dumps({"schema_version": "1.0", "authorizations": [entry]}, indent=2) + "\n"
    )
    (vault / "manifests" / "security-policies.json").write_text(
        json.dumps({"wireguard": {"master_anchor_ip": anchor}}) + "\n"
    )
    return vault, authz.fingerprint(identity)


def _intake_server(fingerprint: str, spool: Path) -> tuple[ThreadingHTTPServer, str]:
    directory = intake.PeerDirectory(
        [
            {
                "fingerprint": fingerprint,
                "overlay_ipv4": "127.0.0.1/32",
                "capabilities": ["telemetry"],
                "issued_at": "2020-01-01T00:00:00Z",
                "expires_at": "2099-01-01T00:00:00Z",
            }
        ]
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), intake._Handler)
    server.directory = directory
    server.spool = spool
    server.seen_nonces = set()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _run(vault: Path, endpoint: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PUSH_PATH), "--vault-root", str(vault), "--endpoint", endpoint, *extra],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _rows(spool: Path) -> list[dict[str, Any]]:
    if not spool.exists():
        return []
    return [json.loads(line) for line in spool.read_text().splitlines() if line.strip()]


def _load_regime() -> ModuleType:
    return _load("sparknet_share_regime_for_telemetry", ROLE_ROOT / "services" / "sparknet-share-regime.py")


def _flagged_session(vault: Path, node_id: str, counterpart: str = "sparknet-node-0008") -> None:
    """Persist a real flagged share record, shaped by the share engine itself."""
    engine = _load_regime()
    now = datetime.now(timezone.utc)
    kwargs = {"now": lambda: now, "node_count": lambda: 2, "contracts_dir": FABRIC_ROOT / "contracts"}
    mine = engine.Regime(node_id, **kwargs)
    theirs = engine.Regime(counterpart, **kwargs)
    offer = mine.offer("kb-share", toward=counterpart)
    theirs.dispatch(offer)
    mine.dispatch(theirs.accept(offer["share_id"], "kb-share"))
    sessions = vault / ".state" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "session-1.json").write_text(
        json.dumps({"grant_id": "session-1", "shares": [mine.get(offer["share_id"])]}, indent=2) + "\n"
    )


def test_a_granted_peer_pushes_reports_the_intake_accepts(tmp_path: Path) -> None:
    vault, fingerprint = _fixture_vault(tmp_path)
    spool = tmp_path / "telemetry.jsonl"
    server, base = _intake_server(fingerprint, spool)
    try:
        result = _run(vault, base + ROUTE)
        assert result.returncode == 0, result.stderr
    finally:
        server.shutdown()
        server.server_close()

    rows = _rows(spool)
    assert [row["kind"] for row in rows] == ["status", "metrics"]
    for row in rows:
        report = {key: value for key, value in row.items() if key != "source"}
        ok, reason = authz.verify_telemetry_report(report, expected_fingerprint=fingerprint)
        assert ok, reason
        assert report["peer_fingerprint"] == fingerprint
        assert row["source"] == "127.0.0.1"
    status = next(row for row in rows if row["kind"] == "status")
    assert status["payload"]["node_id"] == "sparknet-node-0007"
    assert status["payload"]["capabilities"] == ["telemetry"]


def test_a_flagged_peer_surfaces_trust_in_status_and_mutates_nothing(tmp_path: Path) -> None:
    """70G: the status report carries the belief, and the telemetry path only reads.

    A flagged share is opened by the real regime, persisted the way the bridge
    persists it, then the real pusher sends a status report to the real intake.
    The registry and share records must be byte-identical afterwards: surfacing a
    flag is evidence, never remediation.
    """
    vault, fingerprint = _fixture_vault(tmp_path)
    _flagged_session(vault, "sparknet-node-0007")
    registry = vault / "manifests" / "node-authorizations.json"
    sessions = vault / ".state" / "sessions" / "session-1.json"
    registry_before, sessions_before = registry.read_bytes(), sessions.read_bytes()

    spool = tmp_path / "telemetry.jsonl"
    server, base = _intake_server(fingerprint, spool)
    try:
        result = _run(vault, base + ROUTE, "--kind", "status")
        assert result.returncode == 0, result.stderr
    finally:
        server.shutdown()
        server.server_close()

    row = _rows(spool)[0]
    trust = row["payload"]["trust"]
    assert trust["level"] == "flagged"
    assert [share["share_id"] for share in trust["flagged_shares"]] == ["share-1"]
    assert trust["flagged_shares"][0]["counterpart"] == "sparknet-node-0008"
    assert registry.read_bytes() == registry_before, "telemetry must not rewrite the signed registry"
    assert sessions.read_bytes() == sessions_before, "telemetry must not rewrite share trust state"


def test_a_ratified_share_keeps_its_flag_as_evidence() -> None:
    """Ratification moves the level; the retained marker is still in the summary."""
    engine = _load_regime()
    now = datetime.now(timezone.utc)
    kwargs = {"now": lambda: now, "node_count": lambda: 3, "contracts_dir": FABRIC_ROOT / "contracts"}
    mine = engine.Regime("sparknet-node-0007", **kwargs)
    theirs = engine.Regime("sparknet-node-0008", **kwargs)
    master = engine.Regime("master", **kwargs)
    offer = mine.offer("kb-share", toward="sparknet-node-0008")
    theirs.dispatch(offer)
    mine.dispatch(theirs.accept(offer["share_id"], "kb-share"))
    theirs.dispatch(master.ratify(offer["share_id"], True, "master"))
    mine.dispatch(master.ratify(offer["share_id"], True, "master"))

    trust = engine.trust_summary([mine.get(offer["share_id"])], "sparknet-node-0007")
    assert trust["level"] == "authenticated"
    assert trust["retained_flags"] == ["flagged"]
    assert trust["flagged_shares"][0]["retained_flags"] == ["flagged"]


def test_a_peer_without_the_telemetry_capability_pushes_nothing(tmp_path: Path) -> None:
    vault, _ = _fixture_vault(tmp_path, capabilities=("p2p-sync",))
    spool = tmp_path / "telemetry.jsonl"
    result = _run(vault, "http://127.0.0.1:9" + ROUTE)
    assert result.returncode == 0
    assert not spool.exists()
    assert "telemetry capability not granted" in result.stderr


def test_a_revoked_peer_pushes_nothing(tmp_path: Path) -> None:
    vault, _ = _fixture_vault(tmp_path, revoked=True)
    spool = tmp_path / "telemetry.jsonl"
    result = _run(vault, "http://127.0.0.1:9" + ROUTE)
    assert result.returncode == 0
    assert not spool.exists()
    assert "revoked" in result.stderr


def test_an_unprovisioned_vault_is_silent(tmp_path: Path) -> None:
    vault = tmp_path / "empty"
    vault.mkdir()
    result = _run(vault, "http://127.0.0.1:9" + ROUTE)
    assert result.returncode == 0
    assert "no readable identity/registry/master key" in result.stderr


def test_a_refused_report_fails_the_run(tmp_path: Path) -> None:
    """A real transport failure is not silence: the timer's journal must say so."""

    class _Refusing(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"error":"unavailable"}')

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Refusing)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        vault, _ = _fixture_vault(tmp_path)
        result = _run(vault, f"http://127.0.0.1:{server.server_address[1]}" + ROUTE)
    finally:
        server.shutdown()
        server.server_close()
    assert result.returncode == 1
    assert "failed" in result.stderr and "503" in result.stderr


def test_dry_run_prints_and_sends_nothing(tmp_path: Path) -> None:
    vault, fingerprint = _fixture_vault(tmp_path)
    result = _run(vault, "http://127.0.0.1:9" + ROUTE, "--dry-run")
    assert result.returncode == 0
    reports = json.loads(result.stdout)
    assert [report["kind"] for report in reports] == ["status", "metrics"]
    for report in reports:
        assert report["peer_fingerprint"] == fingerprint
        assert "signature_b64" not in report
    assert "not pushing" not in result.stderr


def test_the_endpoint_prefers_override_then_environment_then_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, _ = _fixture_vault(tmp_path, anchor="10.100.0.99")
    monkeypatch.delenv("SPARKNET_MASTER_ANCHOR_IP", raising=False)
    monkeypatch.delenv("SPARKNET_TELEMETRY_ENDPOINT", raising=False)
    assert push.resolve_endpoint(vault) == "http://10.100.0.99:8090/api/v1/telemetry"
    monkeypatch.setenv("SPARKNET_MASTER_ANCHOR_IP", "10.100.0.7")
    assert push.resolve_endpoint(vault) == "http://10.100.0.7:8090/api/v1/telemetry"
    monkeypatch.setenv("SPARKNET_TELEMETRY_ENDPOINT", "http://127.0.0.1:4321" + ROUTE)
    assert push.resolve_endpoint(vault) == "http://127.0.0.1:4321" + ROUTE
    assert push.resolve_endpoint(vault, "http://127.0.0.1:1234" + ROUTE) == "http://127.0.0.1:1234" + ROUTE


def test_metrics_are_measured_not_invented(tmp_path: Path) -> None:
    vault, fingerprint = _fixture_vault(tmp_path)
    report = push.build_reports(
        json.loads((vault / "manifests" / "node-identity.json").read_text()),
        ["telemetry"],
        ["metrics"],
        vault,
    )[0]
    payload = report["payload"]
    assert payload["uptime_seconds"] is None or payload["uptime_seconds"] >= 0
    assert payload["vault_disk_total_bytes"] is None or payload["vault_disk_total_bytes"] > 0
    assert payload["idle"]["schema_version"] == "sparknet-idle/1"
    assert payload["idle"]["sampled_at"]
    assert "interactive_sessions" in payload["idle"]
    assert "gpu_util_pct" in payload["idle"]
    assert "errors" in payload["idle"]
    assert report["peer_fingerprint"] == fingerprint


def test_the_pusher_carries_no_authority() -> None:
    """It reports; it never signs, grants, revokes or approves."""
    source = PUSH_PATH.read_text()
    for verb in ("sign_bytes", "sign_telemetry_report", "sign_authorization", "guard_approval_message"):
        assert verb not in source, f"the pusher must not reach for a signing primitive ({verb})"
    assert "no authority" in source.lower()


def test_the_unit_and_timer_are_wired() -> None:
    service = (ROLE_ROOT / "systemd" / "sparknet-telemetry-push.service").read_text()
    timer = (ROLE_ROOT / "systemd" / "sparknet-telemetry-push.timer").read_text()
    installer = (ROLE_ROOT / "scripts" / "sparknet-install-units.sh").read_text()
    assert "sparknet-telemetry-push" in service
    assert "OnCalendar" in timer
    assert "sparknet-telemetry-push.service" in installer
    assert "sparknet-telemetry-push.timer" in installer
    assert (
        "for name in guard wifi-guard sync wireguard-anchor telemetry-push liveness-monitor checkpoint-anchor"
        in installer
    )
    assert "sparknet-telemetry-push.py" in installer
