"""Release manifests bind signed artifacts to a package index."""

from __future__ import annotations

import hashlib
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sparknet_loader import load_by_path

ROOT = Path(__file__).resolve().parent.parent


def _load(name, filename):
    return load_by_path(name, ROOT / "shared" / filename)


release = _load("release_test", "sparknet-release.py")


def _manifest():
    return {
        "schema_version": "sparknet-release/1",
        "release_id": "rel-1",
        "version": "1.0.0",
        "channel": "stable",
        "artifacts": [{"path": "packages/index.json", "sha256": "a" * 64, "size": 10}],
        "package_index_sha256": "b" * 64,
        "signer_node_id": "master",
        "created_at": "2099-01-01T00:00:00Z",
    }


def test_release_signature_and_index_binding():
    key = Ed25519PrivateKey.generate()
    signed = release.sign_release(_manifest(), key)
    assert release.verify_release(signed, key.public_key()) is True
    tampered = dict(signed, version="1.0.1")
    assert release.verify_release(tampered, key.public_key()) is False
    data = b"index-bytes"
    bound = dict(_manifest(), package_index_sha256=hashlib.sha256(data).hexdigest())
    assert release.verify_package_index(bound, data) is True
    assert release.verify_package_index(bound, b"other") is False


def test_release_refuses_unsafe_artifacts_and_unknown_channels():
    bad = _manifest()
    bad["artifacts"] = [{"path": "../escape", "sha256": "a" * 64, "size": 1}]
    try:
        release.validate_release(bad)
    except release.ReleaseError as exc:
        assert exc.code == "bad-artifact"
    else:
        raise AssertionError("unsafe path accepted")
    bad = _manifest()
    bad["channel"] = "nightly"
    try:
        release.validate_release(bad)
    except release.ReleaseError as exc:
        assert exc.code == "bad-channel"
    else:
        raise AssertionError("unknown channel accepted")
