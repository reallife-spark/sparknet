"""Model activation state is explicit and benchmark-gated."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import ModuleType

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit


ROOT = Path(__file__).resolve().parent.parent
UPDATE = ROOT / "scripts" / "sparknet-model-update.py"
MODEL_ID = "qwen3.5-9b-q8"


@pytest.fixture(scope="module")
def update() -> ModuleType:
    return load_by_path("sparknet_model_update_test", UPDATE)


def _store(tmp_path: Path) -> Path:
    store = tmp_path / "models"
    model_dir = store / MODEL_ID
    model_dir.mkdir(parents=True)
    payload = b"fake gguf"
    (model_dir / "model.gguf").write_bytes(payload)
    manifest = {
        "id": MODEL_ID,
        "pinned": True,
        "revision": "main",
        "resolved_revision": "abc123",
        "model_file": "model.gguf",
        "files": [
            {
                "path": "model.gguf",
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size": len(payload),
            }
        ],
    }
    (store / "manifests").mkdir(parents=True)
    (store / "manifests" / f"{MODEL_ID}.json").write_text(json.dumps(manifest))
    return store


def _bench(tmp_path: Path, quality: float = 1.0) -> Path:
    path = tmp_path / "bench.json"
    path.write_text(json.dumps({"candidates": [{"id": MODEL_ID, "quality_pass_rate": quality}]}))
    return path


def test_promote_and_rollback_keep_the_previous_manifest(update: ModuleType, tmp_path: Path) -> None:
    store = _store(tmp_path)
    manifest = store / "manifests" / f"{MODEL_ID}.json"
    assert update.set_candidate("agx32", store, MODEL_ID, manifest)["ok"] is True
    promoted = update.promote("agx32", store, MODEL_ID, "operator", _bench(tmp_path))
    assert promoted["active"]["id"] == MODEL_ID
    assert promoted["previous"] is None
    state = update.load_state(store, "agx32")
    state["previous"] = dict(state["active"])
    update.write_state(store, "agx32", state)
    rolled = update.rollback("agx32", store, "operator")
    assert rolled["active"]["id"] == MODEL_ID
    assert rolled["previous"]["id"] == MODEL_ID


def test_low_quality_is_refused(update: ModuleType, tmp_path: Path) -> None:
    store = _store(tmp_path)
    manifest = store / "manifests" / f"{MODEL_ID}.json"
    update.set_candidate("agx32", store, MODEL_ID, manifest)
    with pytest.raises(SystemExit):
        update.promote("agx32", store, MODEL_ID, "operator", _bench(tmp_path, quality=0.2))
    assert update.load_state(store, "agx32")["active"] is None
