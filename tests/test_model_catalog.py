"""The model catalog and role placement.

The catalog is the closed list of models a node may pull. It is not knowledge
and not authority, so the tests here check placement and shape rather than
serving behaviour: the teacher belongs to the 64 GB peer, the student to the
32 GB Master, and a teacher must never be eligible for agx32.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CATALOG = ROOT / "contracts" / "model-catalog.json"
PULL = ROOT / "scripts" / "sparknet-model-pull.py"
RUNTIME = ROOT / "scripts" / "sparknet-model-runtime.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pull = _load(PULL, "sparknet_model_pull_catalog_test")
runtime = _load(RUNTIME, "sparknet_model_runtime_catalog_test")


@pytest.fixture(scope="module")
def catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def test_catalog_is_valid(catalog: dict) -> None:
    assert pull.validate_catalog(catalog) == []


def test_teacher_is_only_eligible_on_the_64gb_peer(catalog: dict) -> None:
    teachers = [model for model in catalog["models"] if model["role"] == "teacher"]
    assert teachers, "the catalog has no teacher candidate"
    for model in teachers:
        assert model["nodes"] == ["agx64"], f"{model['id']} must not be eligible on agx32"


def test_student_is_only_eligible_on_the_32gb_master(catalog: dict) -> None:
    students = [model for model in catalog["models"] if model["role"] == "student"]
    assert students, "the catalog has no student candidate"
    for model in students:
        assert model["nodes"] == ["agx32"], f"{model['id']} must not be eligible on agx64"


def test_embeddings_are_available_on_both_nodes(catalog: dict) -> None:
    embeddings = [model for model in catalog["models"] if model["role"] == "embedding"]
    assert embeddings
    for model in embeddings:
        assert set(model["nodes"]) == {"agx64", "agx32"}


def test_selecting_a_teacher_for_the_master_fails(catalog: dict) -> None:
    with pytest.raises(pull.PullError):
        pull.select_models(catalog, "agx32", ["qwen3.8-flash-next-3.84bpw"])


def test_catalog_rejects_a_teacher_backup_on_agx32(catalog: dict) -> None:
    mutated = json.loads(json.dumps(catalog))
    for model in mutated["models"]:
        if model["role"] == "teacher":
            model["nodes"] = ["agx64", "agx32"]
            break
    errors = pull.validate_catalog(mutated)
    assert any("teacher is eligible only on agx64" in error for error in errors)


def test_peer_runtime_config_matches_the_catalog(catalog: dict) -> None:
    config = json.loads((ROOT / "peer-node" / "configs" / "model-runtime" / "runtime.json").read_text())
    models = {model["id"]: model for model in catalog["models"]}
    assert runtime.validate_config(config, "peer", models) == []


def test_master_runtime_config_matches_the_catalog(catalog: dict) -> None:
    config = json.loads((ROOT / "master-node" / "configs" / "model-runtime" / "runtime.json").read_text())
    models = {model["id"]: model for model in catalog["models"]}
    assert runtime.validate_config(config, "master", models) == []


def test_master_runtime_rejects_a_teacher_profile(catalog: dict) -> None:
    config = json.loads((ROOT / "master-node" / "configs" / "model-runtime" / "runtime.json").read_text())
    config["profiles"]["teacher"] = {
        "model_id": "qwen3.8-flash-next-3.84bpw",
        "compose_file": "peer-node/configs/model-runtime/docker-compose.teacher.yml",
        "project": "sparknet-teacher",
        "profile": "teacher",
        "services": ["teacher"],
        "model_env": "TEACHER_MODEL_FILE",
        "memory_gb": 46,
        "health_url": "http://127.0.0.1:8100/health",
        "conflicts": [],
    }
    models = {model["id"]: model for model in catalog["models"]}
    errors = runtime.validate_config(config, "master", models)
    assert any("not eligible for agx32" in error for error in errors)


def test_compose_profiles_are_on_demand_and_loopback() -> None:
    yaml = pytest.importorskip("yaml")
    for path in (
        ROOT / "peer-node" / "configs" / "model-runtime" / "docker-compose.teacher.yml",
        ROOT / "master-node" / "configs" / "model-runtime" / "docker-compose.student.yml",
    ):
        data = yaml.safe_load(path.read_text())
        assert data["services"]
        for service in data["services"].values():
            assert service["restart"] == "no", f"{path.name} must not auto-restart an on-demand model"
            assert service["network_mode"] == "host"
            assert service["profiles"]
            assert any(":ro" in str(volume) for volume in service["volumes"])


def test_catalog_has_no_secret_like_values(catalog: dict) -> None:
    text = CATALOG.read_text(encoding="utf-8").lower()
    for marker in ("hf_token", "api_key", "secret", "password"):
        assert marker not in text, f"model catalog contains a secret marker: {marker}"
