"""Step 69C: the Master peer-intake listener on 8090, for real.

This replaces ``test_listener_8090.py``, which Master Step 7 itself flagged as a test
that "passes by reading the source file's text, not by binding a socket or refusing
anything." These bind a real ``ThreadingHTTPServer`` and POST real bodies, so a
refusal the DoD names is a refusal a test can actually provoke.

The source gate is registry-driven, so a test maps ``127.0.0.1`` to a registered peer
(the same trick ``test_registry_dist.py`` uses to reach a loopback guard): attribution
is then exercised end to end, and the gate's own branches are unit-tested directly.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib import error as urlerror
from urllib import request as urlrequest

import pytest

ROLE_ROOT = Path(__file__).resolve().parent.parent
FABRIC_ROOT = ROLE_ROOT.parent
INTAKE_PATH = ROLE_ROOT / "services" / "sparknet-telemetry-intake.py"
ROUTE = "/api/v1/telemetry"
PEER_FP = "a" * 64


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


intake = _load("sparknet_telemetry_intake", INTAKE_PATH)
authz = intake.authz


def _directory(*, telemetry: bool = True, revoked: bool = False, loopback: bool = True) -> intake.PeerDirectory:
    """A directory whose only peer sits at 127.0.0.1, so a loopback POST attributes."""
    entries = []
    if loopback:
        entries.append(
            {
                "fingerprint": PEER_FP,
                "overlay_ipv4": "127.0.0.1/32",
                "capabilities": ["telemetry", "guard-apply"] if telemetry else ["guard-apply"],
                "revoked": revoked,
            }
        )
    return intake.PeerDirectory(entries)


def _report(**overrides) -> dict:
    # No fixed `now`: the intake verifies against the real clock, so a report built
    # at a pinned past instant would arrive expired. build_telemetry_report defaults
    # to the current time, which is what a live pusher would stamp.
    params = {"kind": "status", "peer_fingerprint": PEER_FP, "payload": {"alive": True}}
    params.update(overrides)
    return authz.build_telemetry_report(**params)


def _server(directory, spool: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), intake._Handler)
    server.directory = directory
    server.spool = spool
    server.seen_nonces = set()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, f"http://127.0.0.1:{server.server_address[1]}"


def _post(base: str, report: dict, path: str = ROUTE) -> tuple[int, dict]:
    req = urlrequest.Request(
        base + path, data=json.dumps(report).encode(), headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urlrequest.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urlerror.HTTPError as exc:
        return exc.code, json.loads(exc.read())


# --- the source gate, unit-tested --------------------------------------------


def test_the_source_gate_maps_a_registered_telemetry_peer() -> None:
    assert _directory().attribute("127.0.0.1") == (PEER_FP, "")


def test_the_source_gate_refuses_an_ungranted_peer() -> None:
    """Wiring the telemetry capability: a peer without it may not push."""
    assert _directory(telemetry=False).attribute("127.0.0.1") == (None, "capability_missing")


def test_the_source_gate_refuses_a_revoked_peer() -> None:
    assert _directory(revoked=True).attribute("127.0.0.1") == (None, "revoked")


def test_the_source_gate_refuses_an_unknown_source() -> None:
    assert _directory(loopback=False).attribute("127.0.0.1") == (None, "off_overlay")
    # The Master's own address is not a peer entry, so it is not a telemetry source.
    assert _directory().attribute("10.100.0.1") == (None, "off_overlay")


def test_the_address_is_matched_bare_of_its_prefix() -> None:
    d = intake.PeerDirectory([{"fingerprint": PEER_FP, "overlay_ipv4": "10.100.0.9/32", "capabilities": ["telemetry"]}])
    assert d.attribute("10.100.0.9") == (PEER_FP, "")


# --- the listener, over a real socket ----------------------------------------


def test_a_valid_report_is_recorded_and_acknowledged(tmp_path: Path) -> None:
    spool = tmp_path / "telemetry" / "reports.jsonl"
    server, thread, base = _server(_directory(), spool)
    try:
        report = _report()
        status, body = _post(base, report)
        assert status == 200
        assert body["status"] == "recorded" and body["kind"] == "status" and body["spooled"] is True
        rows = [json.loads(x) for x in spool.read_text().splitlines() if x.strip()]
        assert len(rows) == 1
        assert rows[0]["nonce"] == report["nonce"]
        assert rows[0]["source"] == "127.0.0.1"
        assert oct(spool.stat().st_mode & 0o777) == "0o600"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_a_report_naming_another_peer_is_refused(tmp_path: Path) -> None:
    """Attribution is the overlay: the body's fingerprint must match the source's."""
    server, thread, base = _server(_directory(), tmp_path / "s.jsonl")
    try:
        status, body = _post(base, _report(peer_fingerprint="b" * 64))
        assert status == 403 and body["error"] == "wrong_peer"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_an_ungranted_source_is_refused_before_the_body_is_read(tmp_path: Path) -> None:
    server, thread, base = _server(_directory(telemetry=False), tmp_path / "s.jsonl")
    try:
        status, body = _post(base, _report())
        assert status == 403 and body["error"] == "capability_missing"
        assert not (tmp_path / "s.jsonl").exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_a_replayed_nonce_is_refused(tmp_path: Path) -> None:
    server, thread, base = _server(_directory(), tmp_path / "s.jsonl")
    try:
        report = _report()
        assert _post(base, report)[0] == 200
        status, body = _post(base, report)
        assert status == 409 and body["error"] == "replayed_nonce"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_a_malformed_report_is_refused(tmp_path: Path) -> None:
    server, thread, base = _server(_directory(), tmp_path / "s.jsonl")
    try:
        status, body = _post(base, {**_report(), "escalate": True})
        assert status == 400 and body["error"] == "malformed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_healthz_and_unknown_routes(tmp_path: Path) -> None:
    server, thread, base = _server(_directory(), tmp_path / "s.jsonl")
    try:
        with urlrequest.urlopen(base + "/healthz", timeout=5) as response:
            assert response.status == 200 and json.loads(response.read()) == {"ok": True}
        # Push-only: nothing to GET on the intake route, no sibling to POST to.
        with pytest.raises(urlerror.HTTPError) as raised:
            urlrequest.urlopen(base + ROUTE, timeout=5)
        assert raised.value.code == 404
        assert _post(base, _report(), path="/api/v1/elsewhere")[0] == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_serve_refuses_a_non_overlay_bind(tmp_path: Path) -> None:
    with pytest.raises(intake.IntakeError, match="non-overlay"):
        intake.serve("0.0.0.0", 8090, directory=_directory(), spool=tmp_path / "s.jsonl")


# --- contract + posture pins --------------------------------------------------


def test_the_contract_declares_8090_the_peer_intake() -> None:
    ports = json.loads((FABRIC_ROOT / "contracts" / "ports.json").read_text())
    spec = ports["ports"]["8090"]
    assert spec["service"] == "master-peer-intake"
    assert spec["bound_by"] == "master" and spec["overlay_only"] is True
    assert spec["binds_to"] == "10.100.0.1"
    assert spec["implementation_state"] == "implemented"
    assert "/api/v1/telemetry" in spec["note"]


def test_the_intake_carries_no_authority() -> None:
    """Telemetry observes; it never signs, grants, revokes or approves."""
    source = INTAKE_PATH.read_text()
    for verb in ("sign_bytes", "sign_rfi_answer", "sign_authorization", "guard_approval_message"):
        assert verb not in source, f"the intake must not reach for a signing primitive ({verb})"
    assert "records evidence" in source or "no authority" in source.lower()


def test_the_unit_binds_the_overlay_only() -> None:
    unit = (ROLE_ROOT / "systemd" / "sparknet-telemetry-intake.service").read_text()
    assert "10.100.0.1" in unit
    assert "0.0.0.0" not in unit
    assert "sparknet-telemetry-intake.py" in unit
