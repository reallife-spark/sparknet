"""Nocturnal artefacts: signed projections, coverage and the intake commit."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from types import ModuleType

import pytest
from sparknet_loader import load_by_path

REPO_ROOT = Path(__file__).resolve().parent.parent
NOCTURNAL_PATH = REPO_ROOT / "shared" / "sparknet-nocturnal.py"


@pytest.fixture(scope="module")
def nocturnal(authz: ModuleType) -> ModuleType:
    return load_by_path("sparknet_nocturnal_test", NOCTURNAL_PATH)


def _keypair(authz: ModuleType) -> tuple[str, str]:
    private, public = authz.generate_keypair()
    return private, public


def _result(nocturnal: ModuleType, output: str = "answer") -> dict:
    output_sha = hashlib.sha256(output.encode()).hexdigest()
    return {
        "schema_version": nocturnal.RESULT_SCHEMA,
        "lease_id": "lease-1",
        "job_id": "job-1",
        "subtask_id": "subtask-1",
        "participant_node_id": "node-a",
        "instruction_sha256": hashlib.sha256(b"instruction").hexdigest(),
        "output_sha256": output_sha,
        "model": "qwen3.5-9b-q8",
        "started_at": "2026-11-04T02:00:00Z",
        "ended_at": "2026-11-04T02:00:05Z",
        "coverage": {"answered": ["subtask-1"], "missing": []},
        "output": output,
    }


def _manifest(nocturnal: ModuleType, result: dict) -> dict:
    result_sha = hashlib.sha256((json.dumps(result, sort_keys=True, indent=2) + "\n").encode()).hexdigest()
    return {
        "schema_version": nocturnal.MANIFEST_SCHEMA,
        "lease_id": result["lease_id"],
        "job_id": result["job_id"],
        "participant_node_id": result["participant_node_id"],
        "subtasks": [{"subtask_id": result["subtask_id"], "result_sha256": result_sha, "answered": True}],
        "model": result["model"],
        "corpus_digest": None,
        "started_at": result["started_at"],
        "ended_at": result["ended_at"],
        "coverage": {"answered": ["subtask-1"], "missing": []},
        "created_at": "2026-11-04T02:00:06Z",
    }


def test_result_and_manifest_sign_and_verify(nocturnal: ModuleType, authz: ModuleType) -> None:
    private, public = _keypair(authz)
    result = nocturnal.sign_result(_result(nocturnal), private)
    manifest = nocturnal.sign_manifest(_manifest(nocturnal, result), private)
    assert nocturnal.verify_result(result, public)
    assert nocturnal.verify_manifest(manifest, public)
    assert result["signature_b64"]
    assert manifest["signature_b64"]


def test_output_hash_is_checked(nocturnal: ModuleType, authz: ModuleType) -> None:
    private, public = _keypair(authz)
    result = nocturnal.sign_result(_result(nocturnal), private)
    result["output"] = "tampered"
    assert not nocturnal.verify_result(result, public)


def test_coverage_must_be_disjoint_and_manifest_must_match(nocturnal: ModuleType) -> None:
    result = _result(nocturnal)
    manifest = _manifest(nocturnal, result)
    manifest["coverage"]["missing"] = ["subtask-2"]
    with pytest.raises(nocturnal.ArtifactError):
        nocturnal.validate_manifest(manifest)
    bad = _result(nocturnal)
    bad["coverage"] = {"answered": ["subtask-1"], "missing": ["subtask-1"]}
    with pytest.raises(nocturnal.ArtifactError):
        nocturnal.validate_result(bad)


def test_path_components_are_single_and_safe(nocturnal: ModuleType) -> None:
    with pytest.raises(nocturnal.ArtifactError):
        nocturnal.artifact_dir("/tmp/vault", "../escape", "job-1")
    with pytest.raises(nocturnal.ArtifactError):
        nocturnal.artifact_dir("/tmp/vault", "lease-1", "job/1")


def test_write_artifact_commits_only_the_intake_directory(
    nocturnal: ModuleType, authz: ModuleType, tmp_path: Path
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    subprocess.run(["git", "-C", str(vault), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(vault), "config", "user.email", "test@example.test"], check=True)
    subprocess.run(["git", "-C", str(vault), "config", "user.name", "Test"], check=True)
    (vault / "keep.md").write_text("not an artifact\n")
    subprocess.run(["git", "-C", str(vault), "add", "keep.md"], check=True)
    subprocess.run(["git", "-C", str(vault), "commit", "-qm", "seed"], check=True)

    private, _public = _keypair(authz)
    result = nocturnal.sign_result(_result(nocturnal), private)
    manifest = nocturnal.sign_manifest(_manifest(nocturnal, result), private)
    receipt = nocturnal.write_artifact(vault, "lease-1", "job-1", result, manifest)
    directory = vault / "01_Inbox" / "nocturnal" / "lease-1" / "job-1"
    assert receipt["committed"] is True
    assert (directory / "manifest.json").is_file()
    assert (directory / "result-subtask-1.json").is_file()
    files = subprocess.run(
        ["git", "-C", str(vault), "show", "--name-only", "--pretty=format:", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert files == [
        "01_Inbox/nocturnal/lease-1/job-1/manifest.json",
        "01_Inbox/nocturnal/lease-1/job-1/result-subtask-1.json",
    ]


def test_no_commit_writes_but_does_not_require_a_repo(nocturnal: ModuleType, authz: ModuleType, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    private, _public = _keypair(authz)
    result = nocturnal.sign_result(_result(nocturnal), private)
    manifest = nocturnal.sign_manifest(_manifest(nocturnal, result), private)
    receipt = nocturnal.write_artifact(vault, "lease-1", "job-1", result, manifest, commit=False)
    assert receipt["committed"] is False
    assert (vault / "01_Inbox" / "nocturnal" / "lease-1" / "job-1" / "manifest.json").is_file()
