#!/usr/bin/env python3
"""Signed package manifests and a closed install planner.

A package is data. The module validates the manifest, canonicalises the bytes a
signature covers, and computes a deterministic dependency-first install plan.
It never downloads, installs or executes anything.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

PACKAGE_SCHEMA = "sparknet-package/1"
INDEX_SCHEMA = "sparknet-package-index/1"
PACKAGE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[.-][0-9A-Za-z.-]+)?$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class PackageError(Exception):
    """A fail-closed package refusal."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise PackageError(code, message)


def _nonempty(value: Any, field: str, code: str = "malformed-package") -> str:
    _require(isinstance(value, str) and bool(value.strip()), code, f"{field} must be a non-empty string")
    return value.strip()


def _package_id(value: Any) -> str:
    package_id = _nonempty(value, "package_id", "bad-package-id")
    _require(bool(PACKAGE_ID_RE.fullmatch(package_id)), "bad-package-id", "package_id has the wrong shape")
    return package_id


def _version(value: Any) -> str:
    version = _nonempty(value, "version", "bad-version")
    _require(bool(VERSION_RE.fullmatch(version)), "bad-version", "version is not semver-like")
    return version


def _path(value: Any) -> str:
    _require(isinstance(value, str) and bool(value.strip()), "bad-artifact-path", "artifact path is empty")
    _require(
        "\\" not in value and "\x00" not in value, "bad-artifact-path", "artifact path contains an unsafe character"
    )
    candidate = PurePosixPath(value.strip())
    _require(
        candidate.as_posix() not in ("", ".")
        and not candidate.is_absolute()
        and not any(part in ("..", "", ".") for part in candidate.parts),
        "bad-artifact-path",
        "artifact path escapes the package root",
    )
    return candidate.as_posix()


def _artifact(value: Any) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "bad-artifact", "artifact must be an object")
    digest = _nonempty(value.get("sha256"), "artifact.sha256", "bad-digest")
    _require(bool(DIGEST_RE.fullmatch(digest)), "bad-digest", "artifact.sha256 must be 64 lowercase hex characters")
    size = value.get("size")
    _require(
        isinstance(size, int) and not isinstance(size, bool) and size >= 0,
        "bad-artifact",
        "artifact.size must be a non-negative integer",
    )
    artifact = {"path": _path(value.get("path")), "sha256": digest, "size": size}
    mode = value.get("mode")
    if mode is not None:
        _require(
            isinstance(mode, int) and not isinstance(mode, bool) and 0 <= mode <= 0o777,
            "bad-artifact",
            "artifact.mode must be an integer between 0 and 0o777",
        )
        artifact["mode"] = mode
    return artifact


def _dependency(value: Any) -> dict[str, str]:
    _require(isinstance(value, Mapping), "bad-dependency", "dependency must be an object")
    return {"package_id": _package_id(value.get("package_id")), "version": _version(value.get("version"))}


def _timestamp(value: Any) -> datetime:
    _require(
        isinstance(value, str) and bool(value.strip()), "malformed-package", "timestamp must be an ISO-8601 string"
    )
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise PackageError("malformed-package", "timestamp is not valid") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def make_package(
    *,
    package_id: str,
    version: str,
    artifacts: Sequence[Mapping[str, Any]],
    dependencies: Sequence[Mapping[str, Any]] = (),
    description: str = "",
    signer_node_id: str = "",
    created_at: datetime | None = None,
    signature_b64: str | None = None,
) -> dict[str, Any]:
    moment = created_at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    package = {
        "schema_version": PACKAGE_SCHEMA,
        "package_id": package_id,
        "version": version,
        "description": str(description),
        "artifacts": [_artifact(item) for item in artifacts],
        "dependencies": [_dependency(item) for item in dependencies],
        "signer_node_id": str(signer_node_id),
        "created_at": _iso(moment),
        "signature_b64": signature_b64,
    }
    return validate_package(package)


def validate_package(package: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(package, Mapping), "malformed-package", "package must be an object")
    _require(package.get("schema_version") == PACKAGE_SCHEMA, "malformed-package", "unknown package schema")
    artifacts = package.get("artifacts")
    _require(isinstance(artifacts, (list, tuple)) and bool(artifacts), "bad-artifact", "package has no artifacts")
    normalised_artifacts = [_artifact(item) for item in artifacts]
    paths = [item["path"] for item in normalised_artifacts]
    _require(len(paths) == len(set(paths)), "bad-artifact", "artifact paths must be unique")
    dependencies = package.get("dependencies")
    _require(isinstance(dependencies, (list, tuple)), "bad-dependency", "dependencies must be a list")
    normalised_dependencies = [_dependency(item) for item in dependencies]
    signer_node_id = _nonempty(package.get("signer_node_id"), "signer_node_id", "malformed-package")
    signature = package.get("signature_b64")
    _require(signature is None or isinstance(signature, str), "bad-signature", "signature_b64 must be a string or null")
    return {
        "schema_version": PACKAGE_SCHEMA,
        "package_id": _package_id(package.get("package_id")),
        "version": _version(package.get("version")),
        "description": str(package.get("description") or ""),
        "artifacts": sorted(normalised_artifacts, key=lambda item: item["path"]),
        "dependencies": sorted(normalised_dependencies, key=lambda item: (item["package_id"], item["version"])),
        "signer_node_id": signer_node_id,
        "created_at": _iso(_timestamp(package.get("created_at"))),
        "signature_b64": signature,
    }


def package_message(package: Mapping[str, Any]) -> bytes:
    normalised = validate_package(package)
    projected = {key: value for key, value in normalised.items() if key != "signature_b64"}
    return json.dumps(projected, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode(
        "utf-8"
    )


def make_index(
    packages: Sequence[Mapping[str, Any]],
    *,
    updated_at: datetime | None = None,
    signature_b64: str | None = None,
) -> dict[str, Any]:
    moment = updated_at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    index = {
        "schema_version": INDEX_SCHEMA,
        "updated_at": _iso(moment),
        "packages": list(packages),
        "signature_b64": signature_b64,
    }
    return validate_index(index)


def validate_index(index: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(index, Mapping), "malformed-index", "index must be an object")
    _require(index.get("schema_version") == INDEX_SCHEMA, "malformed-index", "unknown index schema")
    packages = index.get("packages")
    _require(isinstance(packages, (list, tuple)), "malformed-index", "packages must be a list")
    normalised = [validate_package(item) for item in packages]
    keys = [(item["package_id"], item["version"]) for item in normalised]
    _require(len(keys) == len(set(keys)), "duplicate-package", "package id/version pairs must be unique")
    normalised.sort(key=lambda item: (item["package_id"], item["version"]))
    signature = index.get("signature_b64")
    _require(signature is None or isinstance(signature, str), "bad-signature", "signature_b64 must be a string or null")
    return {
        "schema_version": INDEX_SCHEMA,
        "updated_at": _iso(_timestamp(index.get("updated_at"))),
        "packages": normalised,
        "signature_b64": signature,
    }


def index_message(index: Mapping[str, Any]) -> bytes:
    normalised = validate_index(index)
    projected = {key: value for key, value in normalised.items() if key != "signature_b64"}
    return json.dumps(projected, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode(
        "utf-8"
    )


def install_plan(index: Mapping[str, Any], roots: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Dependency-first order; unknown packages and cycles fail closed."""
    normalised = validate_index(index)
    by_key = {(item["package_id"], item["version"]): item for item in normalised["packages"]}
    ordered: list[dict[str, str]] = []
    visiting: set[tuple[str, str]] = set()
    done: set[tuple[str, str]] = set()

    def check(key: tuple[str, str], stack: set[tuple[str, str]], depth: int) -> None:
        _require(depth <= 1000, "dependency-cycle", "dependency chain is too deep")
        if key in stack:
            raise PackageError("dependency-cycle", f"dependency cycle at {key[0]} {key[1]}")
        package = by_key.get(key)
        if package is None:
            raise PackageError("unknown-package", f"unknown package {key[0]} {key[1]}")
        stack.add(key)
        for dependency in package["dependencies"]:
            check((dependency["package_id"], dependency["version"]), stack, depth + 1)
        stack.remove(key)

    for key in by_key:
        check(key, set(), 0)

    def visit(key: tuple[str, str]) -> None:
        if key in done:
            return
        if key in visiting:
            raise PackageError("dependency-cycle", f"dependency cycle at {key[0]} {key[1]}")
        package = by_key.get(key)
        if package is None:
            raise PackageError("unknown-package", f"unknown package {key[0]} {key[1]}")
        visiting.add(key)
        for dependency in package["dependencies"]:
            visit((dependency["package_id"], dependency["version"]))
        visiting.remove(key)
        done.add(key)
        ordered.append({"package_id": key[0], "version": key[1]})

    for root in roots:
        _require(isinstance(root, Mapping), "unknown-package", "root must be an object")
        visit((_package_id(root.get("package_id")), _version(root.get("version"))))
    return ordered


def verify_artifact(artifact: Mapping[str, Any], data: bytes) -> bool:
    normalised = _artifact(artifact)
    return len(data) == normalised["size"] and hashlib.sha256(data).hexdigest() == normalised["sha256"]


def _authz() -> Any:
    """Load the one signing implementation by path, never a package-local copy."""
    return load_shared("sparknet-authz.py", "sparknet_authz_package")


def sign_package(package: Mapping[str, Any], private_key: Any) -> dict[str, Any]:
    """Return a validated package with an Ed25519 signature over its projection."""
    normalised = validate_package(package)
    normalised["signature_b64"] = _authz().sign_bytes(private_key, package_message(normalised))
    return normalised


def verify_package_signature(package: Mapping[str, Any], public_key: Any) -> bool:
    """Verify a package signature; an unsigned or malformed package is false."""
    try:
        normalised = validate_package(package)
        signature = normalised.get("signature_b64")
        if not isinstance(signature, str) or not signature:
            return False
        return bool(_authz().verify_signature(public_key, signature, package_message(normalised)))
    except (PackageError, ValueError, TypeError):
        return False


def sign_index(index: Mapping[str, Any], private_key: Any) -> dict[str, Any]:
    """Return a validated package index with an Ed25519 signature over its projection."""
    normalised = validate_index(index)
    normalised["signature_b64"] = _authz().sign_bytes(private_key, index_message(normalised))
    return normalised


def verify_index_signature(index: Mapping[str, Any], public_key: Any) -> bool:
    """Verify a package-index signature; an unsigned or malformed index is false."""
    try:
        normalised = validate_index(index)
        signature = normalised.get("signature_b64")
        if not isinstance(signature, str) or not signature:
            return False
        return bool(_authz().verify_signature(public_key, signature, index_message(normalised)))
    except (PackageError, ValueError, TypeError):
        return False
