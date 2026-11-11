"""Cluster-job construction, placement and reduce are deterministic and fail closed."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parent.parent
CLUSTER_PATH = REPO_ROOT / "shared" / "sparknet-cluster.py"


@pytest.fixture(scope="module")
def cluster() -> ModuleType:
    return load_by_path("sparknet_cluster_test", CLUSTER_PATH)


def _job() -> dict:
    return {
        "job_id": "job-1",
        "conversation_id": "conv-1",
        "initiator_node_id": "node-a",
        "created_at": "2026-11-04T02:00:00Z",
        "expires_at": "2026-11-04T03:00:00Z",
        "mode": "decompose",
        "prompt": "explain the fabric",
        "subtasks": [
            {"node_id": "node-b", "subtask_id": "s2", "instruction": "second"},
            {"node_id": "node-a", "subtask_id": "s1", "instruction": "first", "context_refs": []},
        ],
    }


def test_construction_is_sorted_and_never_dispatches(cluster: ModuleType) -> None:
    built = cluster.construct(_job(), ["node-b", "node-a"])
    assert built["topology"] == "peer_pair"
    assert built["placement"]["assignments"] == [
        {"node_id": "node-a", "subtask_ids": ["s1"]},
        {"node_id": "node-b", "subtask_ids": ["s2"]},
    ]
    assert [item["subtask_id"] for item in built["subtasks"]] == ["s2", "s1"]


def test_unknown_mode_and_duplicate_subtask_are_refused(cluster: ModuleType) -> None:
    bad = _job()
    bad["mode"] = "map_reduce"
    with pytest.raises(cluster.ClusterError):
        cluster.validate_job(bad)
    bad = _job()
    bad["subtasks"][1]["subtask_id"] = "s2"
    with pytest.raises(cluster.ClusterError):
        cluster.validate_job(bad)


def test_placement_refuses_a_node_outside_the_roster(cluster: ModuleType) -> None:
    with pytest.raises(cluster.ClusterError):
        cluster.construct(_job(), ["node-a", "node-c"])


def test_reduce_names_missing_subtasks_and_never_pads(cluster: ModuleType) -> None:
    merged = cluster.reduce_results(
        [
            {"subtask_id": "s1", "participant_node_id": "node-a", "output": "one", "output_sha256": "a" * 64},
        ],
        ["s1", "s2"],
    )
    assert merged["complete"] is False
    assert merged["coverage"] == {"answered": ["s1"], "missing": ["s2"]}
    assert merged["output"] == "## s1\n\none"
    assert merged["contributions"][0]["subtask_id"] == "s1"


def test_reduce_refuses_duplicates_and_unknown_subtasks(cluster: ModuleType) -> None:
    with pytest.raises(cluster.ClusterError):
        cluster.reduce_results([{"subtask_id": "s1", "output": "one"}] * 2, ["s1"])
    with pytest.raises(cluster.ClusterError):
        cluster.reduce_results([{"subtask_id": "s9", "output": "nine"}], ["s1"])
