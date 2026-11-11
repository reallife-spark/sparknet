"""Cross-language authority: the fabric's Python authz and goSpark's Go authz must
agree, byte-for-byte, on what a Master signature covers.

A DGX Spark node's goSpark agent verifies tasks against a registry the elected
Master signs. The Master signs with ``shared/sparknet-authz.py`` (the fabric's one
signed-authorization implementation); the agent verifies with goSpark's
``internal/authz``. If the two compute the signed-envelope bytes differently, a
fabric-signed registry silently fails to authorize a node — a trust-boundary bug
that no single-language test can catch. This file drives a real registry entry
through **both** implementations, in both directions:

* **Leg A** — Python signs an entry, Go verifies it (and refuses a tampered one);
* **Leg B** — Go signs a registry, Python verifies it (and refuses a tampered one).

They meet only through the file formats the fabric ships
(``contracts/identity-schema.json``, ``signed_envelope_fields``), so an agreement
here is an agreement on the wire.

Both implementations are used in their **native key format**, on purpose: the
elected Master's operational key is a fabric 32-byte Ed25519 seed, while a node
key is minted by ``sparknetctl keygen``. Only the 32-byte *public* key crosses
between them, which is the only thing a verifier ever needs. The private-key
encodings differing (fabric: 32-byte seed; goSpark: Go's 64-byte
seed+public) is therefore not a blocker for the join path — but it is pinned as
a documented asymmetry by ``test_private_key_encodings_differ_by_design`` so a
future reader does not "fix" one side into the other by accident.

Skipped unless ``sparknetctl`` is built (``make -C <gospark> build``) and the
``cryptography`` package is importable.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
AUTHZ = REPO_ROOT / "shared" / "sparknet-authz.py"
GOSPARK_DIR = Path(os.environ.get("GOSPARK_DIR", REPO_ROOT / "gospark"))
CTL = GOSPARK_DIR / "bin" / "sparknetctl"

pytestmark = pytest.mark.integration


def _have_ctl() -> bool:
    return CTL.is_file() and os.access(CTL, os.X_OK)


def _have_cryptography() -> bool:
    try:
        import cryptography  # noqa: F401 - import decides whether to skip
    except ImportError:
        return False
    return True


requires_tools = pytest.mark.skipif(
    not (_have_ctl() and _have_cryptography()),
    reason=(f"needs {CTL} (run: make -C {GOSPARK_DIR} build) and the cryptography package"),
)


def _run(*args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(a) for a in args],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=os.fspath(cwd) if cwd else None,
    )


def _ctl(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return _run(CTL, *args, cwd=cwd)


def _authz(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    # The suite's interpreter already has cryptography; run the module with it.
    return _run(sys.executable, AUTHZ, *args, cwd=cwd)


def _keygen(cwd: Path, node: str, out: str, *extra: str) -> None:
    proc = _ctl("keygen", "-node", node, *extra, "-out", out, cwd=cwd)
    assert proc.returncode == 0, proc.stderr


def _identity_json(key_file: Path) -> dict:
    """Project a goSpark key file into the fabric's identity record.

    The only rename is ``public_key_b64`` -> ``wireguard_public_key_b64`` (the
    field the contract anchors identity to). This projection is exactly what an
    operator hands the Master when joining a node; it is done here in the test so
    the wire shape, not a convenience CLI, is what gets verified.
    """
    key = json.loads(key_file.read_text())
    return {
        "node_id": key["node_id"],
        "role": key["role"],
        "wireguard_public_key_b64": key["public_key_b64"],
        "overlay_ipv4": key["overlay_ipv4"],
        "requested_capabilities": sorted(key.get("requested_capabilities", [])),
    }


def _write_registry(path: Path, master_pub_b64: str, entry: dict) -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "master_public_key_b64": master_pub_b64,
                "authorizations": [entry],
            },
            indent=2,
        )
    )


@requires_tools
def test_go_signed_registry_verifies_in_fabric_python(tmp_path: Path) -> None:
    """Leg B: goSpark signs; the fabric's own verifier accepts it.

    This is the direction a node join exercises in reverse — it proves the entry
    goSpark would produce is one the fabric Master's tooling recognises.
    """
    _keygen(tmp_path, "master", "master.key", "-role", "master")
    _keygen(tmp_path, "node-a", "node.key", "-role", "peer", "-overlay", "10.100.0.7")
    identity = _identity_json(tmp_path / "node.key")
    (tmp_path / "node.identity.json").write_text(json.dumps(identity))

    sign = _ctl(
        "registry",
        "sign",
        "-master-key",
        "master.key",
        "-node-key",
        "node.key",
        "-caps",
        "telemetry,cluster-serve",
        "-out",
        "reg.go.json",
        cwd=tmp_path,
    )
    assert sign.returncode == 0, sign.stderr

    master_pub = json.loads((tmp_path / "master.key").read_text())["public_key_b64"]
    (tmp_path / "master.pub.b64").write_text(master_pub)

    verify = _authz(
        "verify",
        "node.identity.json",
        "--registry",
        "reg.go.json",
        "--master-pubkey",
        "master.pub.b64",
        cwd=tmp_path,
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr
    decision = json.loads(verify.stdout)
    assert decision["allowed"] is True
    assert decision["reason"] == "ok"
    assert decision["capabilities"] == ["cluster-serve", "telemetry"]
    assert decision["overlay_ipv4"] == "10.100.0.7"


@requires_tools
def test_fabric_python_signed_entry_verifies_in_go(tmp_path: Path) -> None:
    """Leg A: the fabric's Python signs; goSpark accepts the entry.

    This is the direction a node join exercises for real: the Master signs with
    the fabric implementation and the goSpark agent verifies.
    """
    _keygen(tmp_path, "node-a", "node.key", "-role", "peer", "-overlay", "10.100.0.7")
    identity = _identity_json(tmp_path / "node.key")
    (tmp_path / "node.identity.json").write_text(json.dumps(identity))

    kp = _authz("generate-keypair", cwd=tmp_path)
    assert kp.returncode == 0, kp.stderr
    priv_b64, pub_b64 = kp.stdout.split()
    (tmp_path / "master.priv.b64").write_text(priv_b64)

    sign = _authz(
        "sign",
        "node.identity.json",
        "--master-key",
        "master.priv.b64",
        "--capabilities",
        "telemetry,cluster-serve",
        "--out",
        "entry.py.json",
        cwd=tmp_path,
    )
    assert sign.returncode == 0, sign.stderr
    entry = json.loads((tmp_path / "entry.py.json").read_text())
    _write_registry(tmp_path / "reg.py.json", pub_b64, entry)

    verify = _ctl(
        "registry",
        "verify",
        "-registry",
        "reg.py.json",
        "-master-pub",
        pub_b64,
        cwd=tmp_path,
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr
    assert "nodes=1" in verify.stdout


@requires_tools
def test_fabric_signed_entry_with_widened_capabilities_is_refused_by_go(tmp_path: Path) -> None:
    """A tampered fabric-signed entry must fail closed in goSpark.

    Widening ``capabilities`` after signing is the attack the per-entry signature
    exists to stop; the two implementations must agree on that failure, not only
    on success.
    """
    _keygen(tmp_path, "node-a", "node.key", "-role", "peer", "-overlay", "10.100.0.7")
    identity = _identity_json(tmp_path / "node.key")
    (tmp_path / "node.identity.json").write_text(json.dumps(identity))

    kp = _authz("generate-keypair", cwd=tmp_path)
    priv_b64, pub_b64 = kp.stdout.split()
    (tmp_path / "master.priv.b64").write_text(priv_b64)
    _authz(
        "sign",
        "node.identity.json",
        "--master-key",
        "master.priv.b64",
        "--capabilities",
        "telemetry,cluster-serve",
        "--out",
        "entry.py.json",
        cwd=tmp_path,
    )
    entry = json.loads((tmp_path / "entry.py.json").read_text())
    entry["capabilities"] = ["guard-apply", "telemetry"]
    _write_registry(tmp_path / "reg.tampered.json", pub_b64, entry)

    verify = _ctl(
        "registry",
        "verify",
        "-registry",
        "reg.tampered.json",
        "-master-pub",
        pub_b64,
        cwd=tmp_path,
    )
    assert verify.returncode != 0
    assert "signature does not verify" in (verify.stdout + verify.stderr)


@requires_tools
def test_go_signed_registry_with_widened_capabilities_is_refused_by_fabric(tmp_path: Path) -> None:
    """The mirror image: a tampered goSpark-signed registry must fail closed in Python."""
    _keygen(tmp_path, "master", "master.key", "-role", "master")
    _keygen(tmp_path, "node-a", "node.key", "-role", "peer", "-overlay", "10.100.0.7")
    identity = _identity_json(tmp_path / "node.key")
    (tmp_path / "node.identity.json").write_text(json.dumps(identity))
    _ctl(
        "registry",
        "sign",
        "-master-key",
        "master.key",
        "-node-key",
        "node.key",
        "-caps",
        "telemetry,cluster-serve",
        "-out",
        "reg.go.json",
        cwd=tmp_path,
    )
    reg = json.loads((tmp_path / "reg.go.json").read_text())
    reg["authorizations"][0]["capabilities"] = ["guard-apply", "telemetry"]
    (tmp_path / "reg.go.tampered.json").write_text(json.dumps(reg))
    master_pub = json.loads((tmp_path / "master.key").read_text())["public_key_b64"]
    (tmp_path / "master.pub.b64").write_text(master_pub)

    verify = _authz(
        "verify",
        "node.identity.json",
        "--registry",
        "reg.go.tampered.json",
        "--master-pubkey",
        "master.pub.b64",
        cwd=tmp_path,
    )
    assert verify.returncode != 0
    assert json.loads(verify.stdout)["reason"] == "bad_signature"


@requires_tools
def test_fingerprints_agree_across_implementations(tmp_path: Path) -> None:
    """The same projected identity must fingerprint identically in both.

    The fingerprint is the registry's primary key and the digest a node echoes;
    a divergence here would make one side unable to find the entry the other
    signed, independent of any signature check.
    """
    _keygen(tmp_path, "node-a", "node.key", "-role", "peer", "-overlay", "10.100.0.7")
    identity = _identity_json(tmp_path / "node.key")
    (tmp_path / "node.identity.json").write_text(json.dumps(identity))

    go = _ctl("fingerprint", "-key", "node.key", cwd=tmp_path)
    assert go.returncode == 0, go.stderr
    go_fp = next(line.split("=", 1)[1] for line in go.stdout.splitlines() if line.startswith("fingerprint="))

    py = _authz("fingerprint", "node.identity.json", cwd=tmp_path)
    assert py.returncode == 0, py.stderr
    assert py.stdout.strip() == go_fp


@requires_tools
def test_private_key_encodings_differ_by_design(tmp_path: Path) -> None:
    """Pin the one known asymmetry so nobody silently "fixes" it.

    Only public keys cross the trust boundary; each side signs with its own
    private-key encoding. This test records the fact rather than asserting it must
    stay forever: if the encodings are ever unified, this test fails and its
    replacement documents the new contract.
    """
    import base64

    _keygen(tmp_path, "master", "master.key", "-role", "master")
    go_priv = json.loads((tmp_path / "master.key").read_text())["private_key_b64"]
    assert len(base64.b64decode(go_priv)) == 64, "goSpark stores Go's 64-byte seed+public"

    kp = _authz("generate-keypair", cwd=tmp_path)
    fab_priv = kp.stdout.split()[0]
    assert len(base64.b64decode(fab_priv)) == 32, "the fabric stores a 32-byte seed"


@requires_tools
@pytest.mark.parametrize("capability", ["issue-report", "sandbox-supervise"])
def test_new_capabilities_cross_the_language_boundary(tmp_path: Path, capability: str) -> None:
    """Both sides must know a capability before a valid grant can be used.

    `issue-report` and `sandbox-supervise` were added to the contract after the
    first Go snapshot. A registry entry carrying either one is a normal signed
    grant; if Go's vocabulary is stale, the entry is refused as unknown even
    though Python accepts it. Exercise both directions so the two vocabularies
    cannot drift again without a red test.
    """
    _keygen(tmp_path, "node-a", "node.key", "-role", "peer", "-overlay", "10.100.0.7")
    identity = _identity_json(tmp_path / "node.key")
    (tmp_path / "node.identity.json").write_text(json.dumps(identity))

    kp = _authz("generate-keypair", cwd=tmp_path)
    priv_b64, pub_b64 = kp.stdout.split()
    (tmp_path / "master.priv.b64").write_text(priv_b64)

    # Leg A: Python signs, Go verifies.
    sign = _authz(
        "sign",
        "node.identity.json",
        "--master-key",
        "master.priv.b64",
        "--capabilities",
        capability,
        "--out",
        "entry.py.json",
        cwd=tmp_path,
    )
    assert sign.returncode == 0, sign.stderr
    entry = json.loads((tmp_path / "entry.py.json").read_text())
    _write_registry(tmp_path / "reg.py.json", pub_b64, entry)
    verify = _ctl(
        "registry",
        "verify",
        "-registry",
        "reg.py.json",
        "-master-pub",
        pub_b64,
        cwd=tmp_path,
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr
    assert "nodes=1" in verify.stdout

    # Leg B: Go signs, Python verifies.
    _keygen(tmp_path, "master", "master.key", "-role", "master")
    sign = _ctl(
        "registry",
        "sign",
        "-master-key",
        "master.key",
        "-node-key",
        "node.key",
        "-caps",
        capability,
        "-out",
        "reg.go.json",
        cwd=tmp_path,
    )
    assert sign.returncode == 0, sign.stderr
    master_pub = json.loads((tmp_path / "master.key").read_text())["public_key_b64"]
    (tmp_path / "master.pub.b64").write_text(master_pub)
    verify = _authz(
        "verify",
        "node.identity.json",
        "--registry",
        "reg.go.json",
        "--master-pubkey",
        "master.pub.b64",
        cwd=tmp_path,
    )
    assert verify.returncode == 0, verify.stdout + verify.stderr
    assert json.loads(verify.stdout)["allowed"] is True
