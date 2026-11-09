"""Step 70D: the peer liveness service, proven over a real socket and intake.

The service is a separate process in production, so the tests run it as one.
The end-to-end shape is deliberately the two real sides: the service's own
probe listener on 4211 (overridden to a free loopback port here), and the
Master's own 8090 handler accepting the resulting ``kind=liveness`` report.
A unit test of ``build_report`` alone would not prove DoD (1) the monitor is
driven by a real service, (2) the claim reaches the Master, or (3) the probe
port is non-serving.

Fabric-level, not peer-level, for the same reason ``test_telemetry_push.py``
is: the intake is Master code a peer bundle deliberately does not carry.
"""

from __future__ import annotations

import base64
import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sparknet_loader import load_by_path

FABRIC_ROOT = Path(__file__).resolve().parent.parent
ROLE_ROOT = FABRIC_ROOT / "peer-node"
SERVICE_PATH = ROLE_ROOT / "services" / "sparknet-liveness-monitor.py"
INTAKE_PATH = FABRIC_ROOT / "master-node" / "services" / "sparknet-peer-intake.py"
ROUTE = "/api/v1/telemetry"


def _load(name: str, path: Path) -> ModuleType:
    return load_by_path(name, path)


service = _load("sparknet_liveness_monitor", SERVICE_PATH)
intake = _load("sparknet_peer_intake_for_liveness", INTAKE_PATH)
authz = service._load_authz()
assert authz is not None


def _fixture_vault(
    tmp_path: Path,
    *,
    self_capabilities: tuple[str, ...] = ("telemetry",),
    sibling_revoked: bool = False,
    sibling_role: str = "peer",
) -> tuple[Path, str, str]:
    """A peer vault with a Master-signed registry containing self and a sibling."""
    vault = tmp_path / "peer"
    (vault / "manifests" / "keys").mkdir(parents=True)
    self_identity = {
        "node_id": "sparknet-node-0007",
        "role": "peer",
        "wireguard_public_key_b64": "dGVzdC13aXJlZ3VhcmQta2V5LXNlbGY=",
        "overlay_ipv4": "10.100.0.7/32",
        "requested_capabilities": ["telemetry", "p2p-sync"],
    }
    sibling_identity = {
        "node_id": "sparknet-node-0008",
        "role": sibling_role,
        "wireguard_public_key_b64": "dGVzdC13aXJlZ3VhcmQta2V5LXNpYmxpbmc=",
        "overlay_ipv4": "127.0.0.1/32",
        "requested_capabilities": ["telemetry"],
    }
    private_b64, public_b64 = authz.generate_keypair()
    (vault / "manifests" / "keys" / "master-ed25519.pub.b64").write_text(public_b64 + "\n")
    private_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(private_b64))
    entries = [
        authz.sign_authorization(self_identity, private_key, list(self_capabilities)),
        authz.sign_authorization(
            sibling_identity,
            private_key,
            ["telemetry"],
            revoked=sibling_revoked,
        ),
    ]
    (vault / "manifests" / "node-identity.json").write_text(json.dumps(self_identity, indent=2) + "\n")
    (vault / "manifests" / "node-authorizations.json").write_text(
        json.dumps({"schema_version": "1.0", "authorizations": entries}, indent=2) + "\n"
    )
    (vault / "manifests" / "security-policies.json").write_text(
        json.dumps({"wireguard": {"master_anchor_ip": "10.100.0.1"}}) + "\n"
    )
    return vault, authz.fingerprint(self_identity), authz.fingerprint(sibling_identity)


def _intake_server(fingerprint: str, spool: Path) -> tuple[Any, str]:
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
    listener = intake.build_listener(bind="127.0.0.1", port=0, directory=directory, spool=spool)
    listener.start()
    return listener, f"http://127.0.0.1:{listener.servers[0].server_address[1]}"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run(vault: Path, endpoint: str, port: int, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SERVICE_PATH),
            "--vault-root",
            str(vault),
            "--endpoint",
            endpoint,
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            *extra,
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _rows(spool: Path) -> list[dict[str, Any]]:
    if not spool.exists():
        return []
    return [json.loads(line) for line in spool.read_text().splitlines() if line.strip()]


def _wait_for_port(port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError(f"probe listener never came up on 127.0.0.1:{port}")


def test_a_liveness_claim_reaches_the_real_intake(tmp_path: Path) -> None:
    vault, fingerprint, sibling_fingerprint = _fixture_vault(tmp_path)
    spool = tmp_path / "telemetry.jsonl"
    server, base = _intake_server(fingerprint, spool)
    port = _free_port()
    try:
        result = _run(vault, base + ROUTE, port, "--once")
    finally:
        server.shutdown()
        server.server_close()
    assert result.returncode == 0, result.stderr

    rows = _rows(spool)
    assert [row["kind"] for row in rows] == ["liveness"]
    report = {key: value for key, value in rows[0].items() if key != "source"}
    ok, reason = authz.verify_telemetry_report(report, expected_fingerprint=fingerprint)
    assert ok, reason
    assert rows[0]["source"] == "127.0.0.1"
    payload = report["payload"]
    assert payload["observer"] == "sparknet-node-0007"
    assert payload["probe_port"] == port
    claims = {claim["node"]: claim for claim in payload["claims"]}
    assert claims["sparknet-node-0008"]["alive"] is True
    assert claims["sparknet-node-0008"]["missed_probes"] == 0
    assert sibling_fingerprint != fingerprint


def test_an_ungranted_peer_probes_but_pushes_nothing(tmp_path: Path) -> None:
    vault, _, _ = _fixture_vault(tmp_path, self_capabilities=("p2p-sync",))
    spool = tmp_path / "telemetry.jsonl"
    port = _free_port()
    result = _run(vault, "http://127.0.0.1:9" + ROUTE, port, "--once")
    assert result.returncode == 0, result.stderr
    assert not spool.exists()
    assert "telemetry capability not granted" in result.stderr


def test_a_revoked_sibling_is_not_a_probe_target(tmp_path: Path) -> None:
    vault, _, _ = _fixture_vault(tmp_path, sibling_revoked=True)
    spool = tmp_path / "telemetry.jsonl"
    port = _free_port()
    result = _run(vault, "http://127.0.0.1:9" + ROUTE, port, "--once")
    assert result.returncode == 0, result.stderr
    assert not spool.exists()
    assert "no registry peers to claim" in result.stderr


def test_a_non_peer_registry_entry_is_not_probed(tmp_path: Path) -> None:
    vault, _, _ = _fixture_vault(tmp_path, sibling_role="master")
    result = _run(vault, "http://127.0.0.1:9" + ROUTE, _free_port(), "--once")
    assert result.returncode == 0, result.stderr
    assert "no registry peers to claim" in result.stderr


def test_the_probe_listener_answers_nothing_and_closes(tmp_path: Path) -> None:
    """DoD (3): the probe port is non-serving — connect, immediate EOF, no bytes."""
    vault, _, _ = _fixture_vault(tmp_path)
    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            str(SERVICE_PATH),
            "--vault-root",
            str(vault),
            "--endpoint",
            "http://127.0.0.1:9" + ROUTE,
            "--bind",
            "127.0.0.1",
            "--port",
            str(port),
            "--interval",
            "1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_port(port)
        with socket.create_connection(("127.0.0.1", port), timeout=2.0) as sock:
            sock.settimeout(2.0)
            assert sock.recv(1) == b""
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    assert process.returncode == 0, process.stderr.read()


def test_a_serving_port_is_refused_as_the_probe_port(tmp_path: Path) -> None:
    vault, _, _ = _fixture_vault(tmp_path)
    for port in (4201, 8090, 9090):
        result = _run(vault, "http://127.0.0.1:9" + ROUTE, port, "--once")
        assert result.returncode == 2
        assert "serving/authority port" in result.stderr


def test_the_roster_requires_a_valid_master_signature(tmp_path: Path) -> None:
    vault, _, _ = _fixture_vault(tmp_path)
    identity, registry, public_key, loaded_authz = service.load_vault(vault)
    registry["authorizations"][1]["capabilities"] = ["guard-apply"]
    roster = service.peer_roster(identity, registry, public_key, loaded_authz)
    assert roster == {}, "an edited registry entry must not become a probe target"


def test_no_peer_means_no_claim(tmp_path: Path) -> None:
    vault, _, _ = _fixture_vault(tmp_path, sibling_role="master")
    result = _run(vault, "http://127.0.0.1:9" + ROUTE, _free_port(), "--dry-run")
    assert result.returncode == 0
    assert result.stdout.strip() == ""
    assert "no registry peers to claim" in result.stderr


def test_the_contracted_port_unit_and_installer_agree() -> None:
    ports = json.loads((FABRIC_ROOT / "contracts" / "ports.json").read_text())
    entry = ports["ports"]["4211"]
    assert entry["service"] == "liveness-probe"
    assert entry["bound_by"] == "peer"
    assert entry["overlay_only"] is True
    assert entry["implementation_state"] == "implemented"
    assert entry["runtime"] == "not-verifiable-here"
    assert service.DEFAULT_PORT == 4211

    service_unit = (ROLE_ROOT / "systemd" / "sparknet-liveness-monitor.service").read_text()
    installer = (ROLE_ROOT / "scripts" / "sparknet-install-units.sh").read_text()
    assert "sparknet-liveness-monitor" in service_unit
    assert "Restart=on-failure" in service_unit
    assert service_unit.count("[Service]") == 1
    assert "sparknet-liveness-monitor.service" in installer
    assert "liveness-monitor) printf" in installer
    assert "liveness-monitor" in installer.split("USER_UNITS=", 1)[1]
    assert (
        "for name in guard wifi-guard sync wireguard-anchor telemetry-push liveness-monitor checkpoint-anchor"
        in installer
    )

    health = (FABRIC_ROOT / "contracts" / "health-protocol.md").read_text()
    assert "4211" in health
    assert "Attribution is the overlay" in health
    assert "claims are unsigned" in health
    assert "DoD: confirm: user" in health


def test_the_service_carries_no_authority_and_writes_no_registry(tmp_path: Path) -> None:
    source = SERVICE_PATH.read_text()
    for verb in ("sign_bytes", "sign_telemetry_report", "sign_authorization", "guard_approval_message"):
        assert verb not in source, f"the liveness service must not reach for a signing primitive ({verb})"
    assert "write_text" not in source and "open(" not in source
    assert "no authority" in source.lower()


def test_the_shared_monitor_announces_each_round() -> None:
    """ContinuousMonitor's on_round hook is what drives probe+evict+claim."""
    module = service._load_monitor()
    seen = threading.Event()
    monitor = module.ContinuousMonitor(
        {"sibling": module.Peer("sibling")},
        resolve=lambda name: name,
        probe=lambda address: True,
        probe_interval=0.01,
        on_round=seen.set,
    )
    monitor.start()
    try:
        assert seen.wait(2.0), "the service hook never ran"
    finally:
        monitor.stop()
