"""Step 70E: the peer checkpoint anchor, proven over a real ledger and intake.

The service is a separate process in production, so the tests run it as one.
The end-to-end shape is the two real sides: a real vault ledger written by
``shared/sparknet-provenance.py``, and the Master's own 8090 handler accepting
the resulting ``kind=checkpoint_anchor`` report. That proves the DoD rather than
only the builder: the checkpoint block is signed and chained, the Merkle root
matches the chain it snapshots, a re-run writes no second block, and the Master
receives the full signed block.

Fabric-level, not peer-level, for the same reason ``test_telemetry_push.py`` is:
the intake is Master code a peer bundle deliberately does not carry.
"""

from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sparknet_loader import load_by_path

FABRIC_ROOT = Path(__file__).resolve().parent.parent
ROLE_ROOT = FABRIC_ROOT / "peer-node"
SERVICE_PATH = ROLE_ROOT / "services" / "sparknet-checkpoint-anchor.py"
INTAKE_PATH = FABRIC_ROOT / "master-node" / "services" / "sparknet-peer-intake.py"
ROUTE = "/api/v1/telemetry"
KIND = "checkpoint_anchor"


def _load(name: str, path: Path) -> ModuleType:
    return load_by_path(name, path)


service = _load("sparknet_checkpoint_anchor", SERVICE_PATH)
intake = _load("sparknet_peer_intake_for_checkpoint", INTAKE_PATH)
provenance = service._load_provenance()
authz = provenance._load_authz()
assert provenance is not None and authz is not None


def _fixture_vault(
    tmp_path: Path,
    *,
    capabilities: tuple[str, ...] = ("telemetry",),
    seed: bool = True,
) -> tuple[Path, str]:
    """A peer vault with a node key, an optional seed block and a signed registry."""
    vault = tmp_path / "peer"
    state_keys = vault / ".state" / "keys"
    state_keys.mkdir(parents=True, mode=0o700)
    node_private, _ = authz.generate_keypair()
    node_key = state_keys / "ed25519-node.key.b64"
    node_key.write_text(node_private + "\n")
    node_key.chmod(0o600)

    (vault / "manifests" / "keys").mkdir(parents=True)
    identity = {
        "node_id": "sparknet-node-0007",
        "role": "peer",
        "wireguard_public_key_b64": "dGVzdC13aXJlZ3VhcmQta2V5LXNlbGY=",
        "overlay_ipv4": "10.100.0.7/32",
        "requested_capabilities": ["telemetry", "p2p-sync"],
    }
    master_private, master_public = authz.generate_keypair()
    (vault / "manifests" / "keys" / "master-ed25519.pub.b64").write_text(master_public + "\n")
    master_key = Ed25519PrivateKey.from_private_bytes(base64.b64decode(master_private))
    entry = authz.sign_authorization(identity, master_key, list(capabilities))
    (vault / "manifests" / "node-identity.json").write_text(json.dumps(identity, indent=2) + "\n")
    (vault / "manifests" / "node-authorizations.json").write_text(
        json.dumps({"schema_version": "1.0", "authorizations": [entry]}, indent=2) + "\n"
    )
    (vault / "manifests" / "security-policies.json").write_text(
        json.dumps({"wireguard": {"master_anchor_ip": "10.100.0.1"}}) + "\n"
    )

    if seed:
        provenance.append_block(vault, {"event": "test", "note": "seed"})
    return vault, authz.fingerprint(identity)


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
    server = intake.ThreadingHTTPServer(("127.0.0.1", 0), intake._Handler)
    server.directory = directory
    server.spool = spool
    server.seen_nonces = set()
    import threading

    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def _run(vault: Path, endpoint: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SERVICE_PATH), "--vault-root", str(vault), "--endpoint", endpoint, *extra],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _blocks(vault: Path) -> list[dict[str, Any]]:
    path = vault / "blockchain" / "ledger.json"
    if not path.exists():
        return []
    return list(json.loads(path.read_text())["blocks"])


def _rows(spool: Path) -> list[dict[str, Any]]:
    if not spool.exists():
        return []
    return [json.loads(line) for line in spool.read_text().splitlines() if line.strip()]


def test_a_checkpoint_is_appended_and_reaches_the_real_intake(tmp_path: Path) -> None:
    vault, fingerprint = _fixture_vault(tmp_path)
    before = _blocks(vault)
    spool = tmp_path / "telemetry.jsonl"
    server, base = _intake_server(fingerprint, spool)
    try:
        result = _run(vault, base + ROUTE)
    finally:
        server.shutdown()
        server.server_close()
    assert result.returncode == 0, result.stderr

    blocks = _blocks(vault)
    assert len(blocks) == len(before) + 1
    checkpoint = blocks[-1]
    data = checkpoint["data"]
    assert data["event"] == "checkpoint"
    assert data["size"] == len(before)
    assert data["head_hash"] == before[-1]["hash"]
    assert data["root"] == provenance._load_merkle().merkle_root([block["hash"] for block in before])
    ok, detail = provenance.verify_checkpoint(checkpoint)
    assert ok, detail

    rows = _rows(spool)
    assert [row["kind"] for row in rows] == [KIND]
    report = {key: value for key, value in rows[0].items() if key != "source"}
    ok, reason = authz.verify_telemetry_report(report, expected_fingerprint=fingerprint)
    assert ok, reason
    assert rows[0]["source"] == "127.0.0.1"
    assert report["payload"]["checkpoint"] == checkpoint, (
        "the Master must receive the full signed block, not only its root"
    )


def test_a_re_run_over_an_unchanged_chain_appends_nothing(tmp_path: Path) -> None:
    vault, fingerprint = _fixture_vault(tmp_path)
    spool = tmp_path / "telemetry.jsonl"
    server, base = _intake_server(fingerprint, spool)
    try:
        first = _run(vault, base + ROUTE)
        after_first = _blocks(vault)
        second = _run(vault, base + ROUTE)
        after_second = _blocks(vault)
    finally:
        server.shutdown()
        server.server_close()
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert len(after_first) == 2
    assert len(after_second) == 2, "a re-run over an unchanged head must not append a second checkpoint"
    assert after_first[-1]["hash"] == after_second[-1]["hash"]
    assert "already checkpointed" in second.stderr

    rows = _rows(spool)
    assert len(rows) == 2
    assert rows[0]["payload"]["checkpoint"]["hash"] == rows[1]["payload"]["checkpoint"]["hash"]


def test_an_empty_chain_is_silence_not_an_error(tmp_path: Path) -> None:
    vault, _ = _fixture_vault(tmp_path, seed=False)
    spool = tmp_path / "telemetry.jsonl"
    result = _run(vault, "http://127.0.0.1:9" + ROUTE)
    assert result.returncode == 0, result.stderr
    assert "empty chain" in result.stderr
    assert not spool.exists()
    assert _blocks(vault) == []


def test_an_ungranted_peer_still_anchors_but_pushes_nothing(tmp_path: Path) -> None:
    vault, _ = _fixture_vault(tmp_path, capabilities=("p2p-sync",))
    spool = tmp_path / "telemetry.jsonl"
    result = _run(vault, "http://127.0.0.1:9" + ROUTE)
    assert result.returncode == 0, result.stderr
    assert len(_blocks(vault)) == 2
    assert "telemetry capability not granted" in result.stderr
    assert not spool.exists()


def test_a_dry_run_writes_nothing(tmp_path: Path) -> None:
    vault, _ = _fixture_vault(tmp_path)
    path = vault / "blockchain" / "ledger.json"
    before = path.read_text()
    result = _run(vault, "http://127.0.0.1:9" + ROUTE, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["data"]["event"] == "checkpoint"
    assert path.read_text() == before


def test_a_tampered_chain_is_refused_and_not_extended(tmp_path: Path) -> None:
    vault, _ = _fixture_vault(tmp_path)
    path = vault / "blockchain" / "ledger.json"
    ledger = json.loads(path.read_text())
    ledger["blocks"][0]["data"]["note"] = "edited after signing"
    path.write_text(json.dumps(ledger, indent=2) + "\n")

    result = _run(vault, "http://127.0.0.1:9" + ROUTE)
    assert result.returncode == 1
    assert "chain does not verify" in result.stderr
    assert len(_blocks(vault)) == 1


def test_the_checkpoint_is_evidence_and_does_not_touch_the_registry(tmp_path: Path) -> None:
    vault, fingerprint = _fixture_vault(tmp_path)
    registry = vault / "manifests" / "node-authorizations.json"
    before = hashlib.sha256(registry.read_bytes()).hexdigest()
    spool = tmp_path / "telemetry.jsonl"
    server, base = _intake_server(fingerprint, spool)
    try:
        result = _run(vault, base + ROUTE)
    finally:
        server.shutdown()
        server.server_close()
    assert result.returncode == 0, result.stderr
    assert hashlib.sha256(registry.read_bytes()).hexdigest() == before

    source = SERVICE_PATH.read_text()
    for verb in ("sign_bytes", "sign_telemetry_report", "sign_authorization", "guard_approval_message"):
        assert verb not in source, f"the anchor service must not reach for a signing primitive ({verb})"
    assert "write_text" not in source and "open(" not in source
    assert "no authority" in source.lower()
    report = {key: value for key, value in _rows(spool)[0].items() if key != "source"}
    assert authz.verify_telemetry_report(report, expected_fingerprint=fingerprint)[0]


def test_the_unit_timer_installer_and_contracts_agree() -> None:
    service_unit = (ROLE_ROOT / "systemd" / "sparknet-checkpoint-anchor.service").read_text()
    timer_unit = (ROLE_ROOT / "systemd" / "sparknet-checkpoint-anchor.timer").read_text()
    installer = (ROLE_ROOT / "scripts" / "sparknet-install-units.sh").read_text()
    assert "sparknet-checkpoint-anchor" in service_unit
    assert "Type=oneshot" in service_unit
    assert "checkpoint-anchor.timer" in service_unit
    assert "OnCalendar=*:0/15" in timer_unit
    assert "WantedBy=timers.target" in timer_unit

    assert "checkpoint-anchor) printf" in installer
    assert (
        "for name in guard wifi-guard sync wireguard-anchor telemetry-push liveness-monitor checkpoint-anchor"
        in installer
    )
    user_units = installer.split("USER_UNITS=", 1)[1].splitlines()[0]
    assert "sparknet-checkpoint-anchor.service" in user_units
    assert "sparknet-checkpoint-anchor.timer" in user_units
    assert "systemctl --user enable --now sparknet-checkpoint-anchor.timer" in installer

    schema = json.loads((FABRIC_ROOT / "contracts" / "telemetry-schema.json").read_text())
    assert "70E" in schema["implementation_state"]["checkpoint_anchor"]
    assert "checkpoint_anchor" in schema["report"]["kinds"]
    protocol = (FABRIC_ROOT / "contracts" / "provenance-protocol.md").read_text()
    assert "sparknet-checkpoint-anchor.py" in protocol
    assert "kind=checkpoint_anchor" in protocol
    assert "8090" in protocol
