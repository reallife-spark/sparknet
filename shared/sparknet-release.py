#!/usr/bin/env python3
"""Signed release manifests and package-index binding.

A release is data: it names immutable artifacts and the package index it
belongs to. Signing proves provenance; it does not install, deploy or grant a
capability.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

RELEASE_SCHEMA = "sparknet-release/1"
CHANNELS = ("stable", "candidate", "test")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
RELEASE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,63}$")


class ReleaseError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise ReleaseError(code, message)


def _path(value: Any) -> str:
    _require(isinstance(value, str) and bool(value.strip()), "bad-artifact", "artifact path is empty")
    _require("\\" not in value and "\x00" not in value, "bad-artifact", "artifact path is unsafe")
    candidate = PurePosixPath(value.strip())
    _require(
        candidate.as_posix() not in ("", ".")
        and not candidate.is_absolute()
        and not any(part in ("..", "", ".") for part in candidate.parts),
        "bad-artifact",
        "artifact path escapes the release root",
    )
    return candidate.as_posix()


def _artifact(value: Any) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "bad-artifact", "artifact must be an object")
    digest = value.get("sha256")
    _require(isinstance(digest, str) and bool(DIGEST_RE.fullmatch(digest)), "bad-digest", "artifact sha256 is invalid")
    size = value.get("size")
    _require(
        isinstance(size, int) and not isinstance(size, bool) and size >= 0, "bad-artifact", "artifact size is invalid"
    )
    return {"path": _path(value.get("path")), "sha256": digest, "size": size}


def validate_release(release: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(release, Mapping), "malformed-release", "release must be an object")
    _require(release.get("schema_version") == RELEASE_SCHEMA, "malformed-release", "unknown release schema")
    release_id = release.get("release_id")
    _require(
        isinstance(release_id, str) and bool(RELEASE_ID_RE.fullmatch(release_id)),
        "bad-release-id",
        "release_id is invalid",
    )
    version = release.get("version")
    _require(isinstance(version, str) and bool(version.strip()), "bad-version", "version is required")
    channel = release.get("channel")
    _require(channel in CHANNELS, "bad-channel", "channel is not in the closed vocabulary")
    artifacts = release.get("artifacts")
    _require(isinstance(artifacts, (list, tuple)) and bool(artifacts), "bad-artifact", "release has no artifacts")
    normalised = [_artifact(item) for item in artifacts]
    paths = [item["path"] for item in normalised]
    _require(len(paths) == len(set(paths)), "bad-artifact", "artifact paths must be unique")
    digest = release.get("package_index_sha256")
    _require(
        isinstance(digest, str) and bool(DIGEST_RE.fullmatch(digest)), "bad-digest", "package index digest is invalid"
    )
    signer = release.get("signer_node_id")
    _require(isinstance(signer, str) and bool(signer.strip()), "malformed-release", "signer_node_id is required")
    created = release.get("created_at")
    _require(isinstance(created, str) and bool(created.strip()), "malformed-release", "created_at is required")
    signature = release.get("signature_b64")
    _require(signature is None or isinstance(signature, str), "bad-signature", "signature_b64 must be a string or null")
    return {
        "schema_version": RELEASE_SCHEMA,
        "release_id": release_id,
        "version": version,
        "channel": channel,
        "artifacts": sorted(normalised, key=lambda item: item["path"]),
        "package_index_sha256": digest,
        "signer_node_id": signer.strip(),
        "created_at": created,
        "signature_b64": signature,
    }


def release_message(release: Mapping[str, Any]) -> bytes:
    normalised = validate_release(release)
    projected = {key: value for key, value in normalised.items() if key != "signature_b64"}
    return json.dumps(projected, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode(
        "utf-8"
    )


def _authz() -> Any:
    return load_shared("sparknet-authz.py", "sparknet_authz_release")


def sign_release(release: Mapping[str, Any], private_key: Any) -> dict[str, Any]:
    normalised = validate_release(release)
    normalised["signature_b64"] = _authz().sign_bytes(private_key, release_message(normalised))
    return normalised


def verify_release(release: Mapping[str, Any], public_key: Any) -> bool:
    try:
        normalised = validate_release(release)
        signature = normalised.get("signature_b64")
        return bool(
            isinstance(signature, str)
            and signature
            and _authz().verify_signature(public_key, signature, release_message(normalised))
        )
    except (ReleaseError, ValueError, TypeError):
        return False


def verify_package_index(release: Mapping[str, Any], index_bytes: bytes) -> bool:
    normalised = validate_release(release)
    return hashlib.sha256(index_bytes).hexdigest() == normalised["package_index_sha256"]
