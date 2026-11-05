"""The model survey inventories catalog and live tags without changing them."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
SURVEY = ROOT / "scripts" / "sparknet-model-survey.py"


@pytest.fixture(scope="module")
def survey() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sparknet_model_survey_test", SURVEY)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _catalog() -> dict:
    return {
        "models": [
            {
                "id": "qwen3.5-9b-q8",
                "role": "student",
                "nodes": ["agx32"],
                "size_gb": 9,
                "fast_memory_gb": 9,
                "runtime": "llama.cpp",
                "license": "Apache-2.0",
                "status": "active",
            },
            {
                "id": "blocked-teacher",
                "role": "teacher",
                "nodes": ["agx64"],
                "size_gb": 85,
                "fast_memory_gb": 46,
                "runtime": "llama.cpp",
                "runtime_note": "Blocked on the current stack.",
                "status": "candidate",
            },
        ]
    }


def test_tag_aliases_and_eligibility(survey: ModuleType, monkeypatch) -> None:
    monkeypatch.setattr(
        survey,
        "live_tags",
        lambda _url: [{"name": "qwen3.5-9b-q8:latest", "digest": "d", "size_gb": 9.0, "modified_at": None}],
    )
    doc = survey.survey(_catalog(), Path("/nonexistent"), "agx32", "http://127.0.0.1:1")
    student = doc["catalog"][0]
    assert student["live_tag"] == "qwen3.5-9b-q8:latest"
    assert student["skip"] is None
    blocked = doc["catalog"][1]
    assert blocked["skip"] == "not_eligible_for_node" or blocked["skip"] == "runtime_unsupported"


def test_plan_marks_skips_and_actions(survey: ModuleType, monkeypatch) -> None:
    monkeypatch.setattr(
        survey,
        "live_tags",
        lambda _url: [{"name": "qwen3.5-9b-q8:latest", "digest": "d", "size_gb": 9.0, "modified_at": None}],
    )
    doc = survey.survey(_catalog(), Path("/nonexistent"), "agx32", "http://127.0.0.1:1")
    planned = survey.plan(doc)
    assert planned["counts"]["benchmark"] == 1
    assert planned["rows"][0]["action"] == "benchmark"


def test_dry_run_never_starts_a_model(survey: ModuleType, monkeypatch) -> None:
    monkeypatch.setattr(
        survey,
        "live_tags",
        lambda _url: [{"name": "qwen3.5-9b-q8:latest", "digest": "d", "size_gb": 9.0, "modified_at": None}],
    )
    doc = survey.survey(_catalog(), Path("/nonexistent"), "agx32", "http://127.0.0.1:1")
    result = survey.run(doc, "agx32", "http://127.0.0.1:1", dry_run=True, only=None)
    assert result["results"][0]["dry_run"] is True
