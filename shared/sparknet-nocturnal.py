#!/usr/bin/env python3
"""Signed nocturnal artefacts: validate, canonicalise, write and commit.

One implementation shared by the participant and the Master. The cryptographic
part stays in ``sparknet-authz.py``; this module only projects the signed fields,
validates the shape, checks the output hash and writes the intake directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

AUTHZ = load_shared("sparknet-authz.py", "sparknet_nocturnal_authz")

RESULT_SCHEMA = "sparknet-nocturnal-result/1"
MANIFEST_SCHEMA = "sparknet-nocturnal-manifest/1"
RESULT_SIGNED_FIELDS = (
    "schema_version",
    "lease_id",
    "job_id",
    "subtask_id",
    "participant_node_id",
    "instruction_sha256",
    "output_sha256",
    "model",
    "started_at",
    "ended_at",
    "coverage",
)
MANIFEST_SIGNED_FIELDS = (
    "schema_version",
    "lease_id",
    "job_id",
    "participant_node_id",
    "subtasks",
    "model",
    "corpus_digest",
    "started_at",
    "ended_at",
    "coverage",
    "created_at",
)
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


class ArtifactError(Exception):
    """A refusal the operator can act on; never a partially written artifact."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ArtifactError(message)


def _timestamp(value: Any, field: str) -> str:
    _require(isinstance(value, str) and value.strip(), f"{field} must be an ISO-8601 string")
    return value.strip()


def _hash(value: Any, field: str) -> str:
    _require(isinstance(value, str) and bool(_HEX64.match(value)), f"{field} must be 64 lowercase hex characters")
    return value


def _component(value: Any, field: str) -> str:
    _require(isinstance(value, str) and value.strip(), f"{field} must be a non-empty string")
    return value.strip()


def _coverage(value: Any) -> dict[str, list[str]]:
    _require(isinstance(value, dict), "coverage must be an object")
    answered = value.get("answered")
    missing = value.get("missing")
    _require(
        isinstance(answered, list) and all(isinstance(x, str) and x for x in answered),
        "coverage.answered must be a list of ids",
    )
    _require(
        isinstance(missing, list) and all(isinstance(x, str) and x for x in missing),
        "coverage.missing must be a list of ids",
    )
    answered = sorted(dict.fromkeys(answered))
    missing = sorted(dict.fromkeys(missing))
    _require(not set(answered) & set(missing), "coverage.answered and coverage.missing must be disjoint")
    return {"answered": answered, "missing": missing}


def _canonical(payload: dict[str, Any], fields: Iterable[str]) -> bytes:
    _require(isinstance(payload, dict), "payload must be an object")
    projected = {}
    for name in fields:
        _require(name in payload, f"missing field: {name}")
        projected[name] = payload[name]
    if "coverage" in projected:
        projected["coverage"] = _coverage(projected["coverage"])
    return json.dumps(projected, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_result(result: dict[str, Any]) -> bytes:
    return _canonical(result, RESULT_SIGNED_FIELDS)


def canonical_manifest(manifest: dict[str, Any]) -> bytes:
    return _canonical(manifest, MANIFEST_SIGNED_FIELDS)


def validate_result(result: dict[str, Any]) -> dict[str, Any]:
    _require(result.get("schema_version") == RESULT_SCHEMA, f"result schema_version must be {RESULT_SCHEMA}")
    for field in ("lease_id", "job_id", "subtask_id", "participant_node_id"):
        _component(result.get(field), field)
    _hash(result.get("instruction_sha256"), "instruction_sha256")
    _hash(result.get("output_sha256"), "output_sha256")
    _timestamp(result.get("started_at"), "started_at")
    _timestamp(result.get("ended_at"), "ended_at")
    _require(isinstance(result.get("model"), str) and result["model"].strip(), "model must be a non-empty string")
    if "output" in result:
        _require(isinstance(result["output"], str), "output must be a string")
        actual = hashlib.sha256(result["output"].encode("utf-8")).hexdigest()
        _require(actual == result["output_sha256"], "output_sha256 does not match output")
    canonical_result(result)
    return result


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    _require(manifest.get("schema_version") == MANIFEST_SCHEMA, f"manifest schema_version must be {MANIFEST_SCHEMA}")
    for field in ("lease_id", "job_id", "participant_node_id"):
        _component(manifest.get(field), field)
    _require(isinstance(manifest.get("model"), str) and manifest["model"].strip(), "model must be a non-empty string")
    _timestamp(manifest.get("started_at"), "started_at")
    _timestamp(manifest.get("ended_at"), "ended_at")
    _timestamp(manifest.get("created_at"), "created_at")
    _require(
        manifest.get("corpus_digest") is None or isinstance(manifest.get("corpus_digest"), str),
        "corpus_digest must be a string or null",
    )
    subtasks = manifest.get("subtasks")
    _require(isinstance(subtasks, list) and subtasks, "subtasks must be a non-empty list")
    seen: set[str] = set()
    for item in subtasks:
        _require(isinstance(item, dict), "each subtask must be an object")
        subtask_id = _component(item.get("subtask_id"), "subtasks[].subtask_id")
        _require(subtask_id not in seen, f"duplicate subtask id: {subtask_id}")
        seen.add(subtask_id)
        _hash(item.get("result_sha256"), "subtasks[].result_sha256")
        _require(isinstance(item.get("answered"), bool), "subtasks[].answered must be a boolean")
    _require(
        [item["subtask_id"] for item in subtasks] == sorted(seen),
        "subtasks must be sorted by subtask_id",
    )
    coverage = _coverage(manifest.get("coverage"))
    _require(
        set(coverage["missing"]) == {item["subtask_id"] for item in subtasks if not item["answered"]},
        "coverage.missing must equal the subtasks marked answered:false",
    )
    canonical_manifest(manifest)
    return manifest


def sign_result(result: dict[str, Any], private_key_b64: str) -> dict[str, Any]:
    validate_result(result)
    payload = dict(result)
    key = AUTHZ.private_key_from_b64(private_key_b64)
    payload["signature_b64"] = AUTHZ.sign_bytes(key, canonical_result(result))
    return payload


def verify_result(result: dict[str, Any], public_key_b64: str) -> bool:
    try:
        validate_result(result)
        signature = result.get("signature_b64")
        if not isinstance(signature, str) or not signature:
            return False
        return AUTHZ.verify_signature(
            AUTHZ.public_key_from_b64(public_key_b64),
            signature,
            canonical_result(result),
        )
    except Exception:
        return False


def sign_manifest(manifest: dict[str, Any], private_key_b64: str) -> dict[str, Any]:
    validate_manifest(manifest)
    payload = dict(manifest)
    key = AUTHZ.private_key_from_b64(private_key_b64)
    payload["signature_b64"] = AUTHZ.sign_bytes(key, canonical_manifest(manifest))
    return payload


def verify_manifest(manifest: dict[str, Any], public_key_b64: str) -> bool:
    try:
        validate_manifest(manifest)
        signature = manifest.get("signature_b64")
        if not isinstance(signature, str) or not signature:
            return False
        return AUTHZ.verify_signature(
            AUTHZ.public_key_from_b64(public_key_b64),
            signature,
            canonical_manifest(manifest),
        )
    except Exception:
        return False


def artifact_dir(vault_root: str | Path, lease_id: str, job_id: str) -> Path:
    root = Path(vault_root)
    lease = _component(lease_id, "lease_id")
    job = _component(job_id, "job_id")
    _require(not any(ch in lease for ch in "/\\") and lease not in (".", ".."), "lease_id must be one path component")
    _require(not any(ch in job for ch in "/\\") and job not in (".", ".."), "job_id must be one path component")
    return root / "01_Inbox" / "nocturnal" / lease / job


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    data = json.dumps(payload, sort_keys=True, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)
        raise


def _git_commit(vault_root: Path, relative: Path, message: str, git_dir: str | Path | None) -> None:
    if git_dir:
        base = ["git", f"--git-dir={Path(git_dir)}", f"--work-tree={vault_root}"]
    else:
        probe = subprocess.run(
            ["git", "-C", str(vault_root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode != 0:
            raise ArtifactError("no git worktree at the vault; pass --git-dir or --no-commit")
        base = ["git", "-C", str(vault_root)]
    for command in (
        [*base, "add", str(relative)],
        [*base, "commit", "-m", message],
    ):
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise ArtifactError(f"git failed: {' '.join(command)}: {result.stderr.strip()}")


def write_artifact(
    vault_root: str | Path,
    lease_id: str,
    job_id: str,
    result: dict[str, Any],
    manifest: dict[str, Any],
    *,
    git_dir: str | Path | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Write one participant result and manifest, then commit only that directory."""
    root = Path(vault_root)
    validate_result(result)
    validate_manifest(manifest)
    _require(result["lease_id"] == manifest["lease_id"], "result and manifest lease_id differ")
    _require(result["job_id"] == manifest["job_id"], "result and manifest job_id differ")
    _require(result["participant_node_id"] == manifest["participant_node_id"], "result and manifest participant differ")
    _require(
        result["subtask_id"] in {item["subtask_id"] for item in manifest["subtasks"]},
        "result subtask is not in the manifest",
    )

    directory = artifact_dir(root, lease_id, job_id)
    result_name = f"result-{_UNSAFE.sub('-', result['subtask_id']).strip('.-') or 'subtask'}.json"
    result_path = directory / result_name
    result_bytes = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode("utf-8")
    result_sha = hashlib.sha256(result_bytes).hexdigest()
    expected = next(
        item["result_sha256"] for item in manifest["subtasks"] if item["subtask_id"] == result["subtask_id"]
    )
    _require(expected == result_sha, "manifest result_sha256 does not match the result file")

    _atomic_write(result_path, result)
    manifest_path = directory / "manifest.json"
    _atomic_write(manifest_path, manifest)
    committed = False
    if commit:
        relative = directory.relative_to(root)
        _git_commit(root, relative, f"nocturnal: {lease_id}/{job_id}", git_dir)
        committed = True
    return {
        "ok": True,
        "directory": str(directory),
        "result": str(result_path),
        "manifest": str(manifest_path),
        "result_sha256": result_sha,
        "committed": committed,
    }


def write_artifact_set(
    vault_root: str | Path,
    lease_id: str,
    job_id: str,
    results: Iterable[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    git_dir: str | Path | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Write every participant result plus one manifest, then commit once."""
    root = Path(vault_root)
    validate_manifest(manifest)
    directory = artifact_dir(root, lease_id, job_id)
    expected = {item["subtask_id"]: item["result_sha256"] for item in manifest["subtasks"]}
    written: list[dict[str, Any]] = []
    seen: set[str] = set()
    for result in results:
        validate_result(result)
        _require(result["lease_id"] == lease_id, "result lease_id differs from the manifest")
        _require(result["job_id"] == job_id, "result job_id differs from the manifest")
        _require(
            result["participant_node_id"] == manifest["participant_node_id"],
            "result participant differs from the manifest",
        )
        subtask_id = result["subtask_id"]
        _require(subtask_id not in seen, f"duplicate result for subtask {subtask_id}")
        seen.add(subtask_id)
        _require(subtask_id in expected, f"result subtask {subtask_id} is not in the manifest")
        result_name = f"result-{_UNSAFE.sub('-', subtask_id).strip('.-') or 'subtask'}.json"
        result_path = directory / result_name
        result_bytes = (json.dumps(result, sort_keys=True, indent=2) + "\n").encode("utf-8")
        result_sha = hashlib.sha256(result_bytes).hexdigest()
        _require(expected[subtask_id] == result_sha, f"manifest hash does not match result {subtask_id}")
        _atomic_write(result_path, result)
        written.append({"subtask_id": subtask_id, "path": str(result_path), "sha256": result_sha})
    _require(set(expected) == seen, "manifest names a subtask with no result file")
    manifest_path = directory / "manifest.json"
    _atomic_write(manifest_path, manifest)
    committed = False
    if commit:
        _git_commit(root, directory.relative_to(root), f"nocturnal: {lease_id}/{job_id}", git_dir)
        committed = True
    return {
        "ok": True,
        "directory": str(directory),
        "results": written,
        "manifest": str(manifest_path),
        "committed": committed,
    }


def write_aggregate(
    vault_root: str | Path,
    lease_id: str,
    job_id: str,
    aggregate: dict[str, Any],
    manifest: dict[str, Any],
    *,
    git_dir: str | Path | None = None,
    commit: bool = True,
) -> dict[str, Any]:
    """Write the Master's reduced result and the collected participant manifest."""
    root = Path(vault_root)
    validate_manifest(manifest)
    _require(isinstance(aggregate, dict), "aggregate must be an object")
    directory = artifact_dir(root, lease_id, job_id)
    _atomic_write(directory / "aggregate.json", aggregate)
    _atomic_write(directory / "manifest.json", manifest)
    committed = False
    if commit:
        _git_commit(root, directory.relative_to(root), f"nocturnal aggregate: {lease_id}/{job_id}", git_dir)
        committed = True
    return {
        "ok": True,
        "directory": str(directory),
        "aggregate": str(directory / "aggregate.json"),
        "manifest": str(directory / "manifest.json"),
        "committed": committed,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate, sign or write a nocturnal artifact")
    parser.add_argument("--validate-result", type=Path)
    parser.add_argument("--validate-manifest", type=Path)
    parser.add_argument("--vault-root", type=Path)
    parser.add_argument("--lease-id")
    parser.add_argument("--job-id")
    parser.add_argument("--result", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--git-dir", type=Path)
    parser.add_argument("--no-commit", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.validate_result:
            print(json.dumps(validate_result(json.loads(args.validate_result.read_text())), sort_keys=True, indent=2))
            return 0
        if args.validate_manifest:
            print(
                json.dumps(validate_manifest(json.loads(args.validate_manifest.read_text())), sort_keys=True, indent=2)
            )
            return 0
        if not all((args.vault_root, args.lease_id, args.job_id, args.result, args.manifest)):
            parser.error("write requires --vault-root --lease-id --job-id --result --manifest")
        result = json.loads(args.result.read_text())
        manifest = json.loads(args.manifest.read_text())
        print(
            json.dumps(
                write_artifact(
                    args.vault_root,
                    args.lease_id,
                    args.job_id,
                    result,
                    manifest,
                    git_dir=args.git_dir,
                    commit=not args.no_commit,
                ),
                sort_keys=True,
                indent=2,
            )
        )
        return 0
    except (ArtifactError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
