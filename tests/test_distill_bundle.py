"""The external-GPU distillation bundle is portable, keyless and complete."""

from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "scripts" / "sparknet-distill-bundle.py"
IMPORT = ROOT / "scripts" / "sparknet-distill-import.py"


@pytest.fixture(scope="module")
def bundle_module():
    return load_by_path("sparknet_distill_bundle_test", BUNDLE)


@pytest.fixture(scope="module")
def import_module():
    return load_by_path("sparknet_distill_import_test", IMPORT)


@pytest.fixture
def dataset(tmp_path: Path) -> Path:
    root = tmp_path / "dataset"
    root.mkdir()
    rows = {
        "train": [{"messages": [{"role": "user", "content": "2+2?"}, {"role": "assistant", "content": "4"}]}],
        "val": [{"messages": [{"role": "user", "content": "3+3?"}, {"role": "assistant", "content": "6"}]}],
        "test": [],
    }
    for name, values in rows.items():
        (root / f"{name}.jsonl").write_text("".join(json.dumps(row) + "\n" for row in values), encoding="utf-8")
    (root / "manifest.json").write_text(
        json.dumps({"schema": "sparknet-distill-dataset/1", "dataset_id": "abc123", "trace_count": 2}),
        encoding="utf-8",
    )
    return root


def test_bundle_contains_trainer_and_dataset(bundle_module, dataset: Path, tmp_path: Path) -> None:
    result = bundle_module.build(dataset, tmp_path / "bundles")
    archive = Path(result["bundle"])
    assert archive.is_file()
    assert result["dataset_id"] == "abc123"
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
        assert "Dockerfile" in names
        assert "train_lora.py" in names
        assert "distill-external-entrypoint.sh" in names
        assert "dataset/train.jsonl" in names
        assert "manifest.json" in names
        manifest = json.load(tar.extractfile("manifest.json"))
    assert manifest["schema"] == "sparknet-distill-bundle/1"
    assert manifest["student_base_model"] == "Qwen/Qwen3-4B-Instruct-2507"
    assert manifest["sequence_length"] == 16384
    assert manifest["signing"].startswith("return to agx32")
    assert not any(name.endswith((".key", ".pem")) for name in names)


def test_external_image_is_qwen3_capable() -> None:
    dockerfile = (ROOT / "master-node" / "configs" / "Dockerfile.distill-external").read_text()
    assert "transformers==4.51.3" in dockerfile
    assert "bitsandbytes" in dockerfile
    assert "b9016" in dockerfile
    entry = (ROOT / "master-node" / "configs" / "distill-external-entrypoint.sh").read_text()
    assert "sparknet-distill-export.py" in entry
    assert "--sign-key" not in entry
    assert "sparknet-sign-artifact.py" not in entry


def test_import_rejects_sha_mismatch(import_module, tmp_path: Path) -> None:
    artifact = tmp_path / "student.gguf"
    artifact.write_bytes(b"x" * (11 * 1024 * 1024))
    expected = hashlib.sha256(b"other").hexdigest()
    with pytest.raises(SystemExit, match="sha256 mismatch"):
        import_module.import_artifact(
            artifact,
            export_json=None,
            expected_sha256=expected,
            run="run-test",
            model="qwen3-4b-2507",
            base="Qwen/Qwen3-4B-Instruct-2507",
        )
