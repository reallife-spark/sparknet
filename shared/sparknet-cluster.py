#!/usr/bin/env python3
"""Deterministic cluster-job construction, placement and reduce.

One shared implementation used by the Master scheduler and the peer ingress.
It never dispatches, signs or executes anything; it only validates the job shape
and returns the placement/reduction it is given.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

MODES = ("decompose", "shard", "best_of_n", "mixture")
REQUIRED_JOB_FIELDS = (
    "job_id",
    "conversation_id",
    "initiator_node_id",
    "created_at",
    "expires_at",
    "mode",
    "prompt",
)
SUBTASK_FIELDS = ("node_id", "subtask_id", "instruction", "context_refs", "mode")
SUBTASK_MODES = ("model", "skill-eval")


class ClusterError(Exception):
    """A fail-closed refusal; never a partially constructed job."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ClusterError(message)


def _nonempty(value: Any, field: str) -> str:
    _require(isinstance(value, str) and value.strip(), f"{field} must be a non-empty string")
    return value.strip()


def _subtask(item: Any, index: int) -> dict[str, Any]:
    _require(isinstance(item, dict), f"subtasks[{index}] must be an object")
    node_id = _nonempty(item.get("node_id"), f"subtasks[{index}].node_id")
    subtask_id = _nonempty(item.get("subtask_id"), f"subtasks[{index}].subtask_id")
    instruction = _nonempty(item.get("instruction"), f"subtasks[{index}].instruction")
    refs = item.get("context_refs", [])
    _require(
        isinstance(refs, list) and all(isinstance(ref, str) for ref in refs),
        f"subtasks[{index}].context_refs must be a list of strings",
    )
    mode = item.get("mode", "model")
    _require(
        isinstance(mode, str) and mode in SUBTASK_MODES,
        f"subtasks[{index}].mode must be one of {', '.join(SUBTASK_MODES)}",
    )
    return {
        "node_id": node_id,
        "subtask_id": subtask_id,
        "instruction": instruction,
        "context_refs": list(refs),
        "mode": mode,
    }


def validate_job(job: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(job, dict), "cluster job must be an object")
    for field in REQUIRED_JOB_FIELDS:
        _nonempty(job.get(field), field)
    _require(job["mode"] in MODES, f"unknown cluster job mode {job['mode']!r}; expected one of {', '.join(MODES)}")
    subtasks = job.get("subtasks")
    _require(isinstance(subtasks, list) and subtasks, "subtasks must be a non-empty list")
    normalised = [_subtask(item, index) for index, item in enumerate(subtasks)]
    ids = [item["subtask_id"] for item in normalised]
    _require(len(ids) == len(set(ids)), "subtask ids must be unique")
    modes = {item["mode"] for item in normalised}
    _require(len(modes) == 1, "a job must not mix model and skill-eval subtasks")
    budget = job.get("budget")
    if budget is not None:
        _require(isinstance(budget, dict), "budget must be an object")
        max_nodes = budget.get("max_nodes")
        _require(
            max_nodes is None or (isinstance(max_nodes, int) and max_nodes > 0),
            "budget.max_nodes must be a positive integer",
        )
        max_rounds = budget.get("max_rounds")
        _require(
            max_rounds is None or (isinstance(max_rounds, int) and max_rounds >= 1),
            "budget.max_rounds must be a positive integer",
        )
        tokens = budget.get("tokens_per_node")
        _require(
            tokens is None or (isinstance(tokens, int) and tokens > 0),
            "budget.tokens_per_node must be a positive integer",
        )
    return {**job, "subtasks": normalised}


def construct(job: dict[str, Any], roster: Iterable[str], *, governance_mode: str | None = None) -> dict[str, Any]:
    """Return deterministic subtasks and placement; never dispatches."""
    normalised = validate_job(job)
    nodes = sorted({_nonempty(node, "roster node") for node in roster})
    _require(len(nodes) >= 2, "a cluster job needs at least two roster nodes")
    if governance_mode is None:
        governance_mode = "peer_pair" if len(nodes) == 2 else "master_governed"
    _require(governance_mode in ("peer_pair", "master_governed"), f"unknown governance mode {governance_mode!r}")
    _require(
        governance_mode != "peer_pair" or len(nodes) == 2,
        "peer_pair placement requires exactly two roster nodes",
    )
    _require(
        governance_mode != "master_governed" or len(nodes) >= 3,
        "master_governed placement requires at least three roster nodes",
    )
    for item in normalised["subtasks"]:
        _require(
            item["node_id"] in nodes, f"subtask {item['subtask_id']} names node {item['node_id']} outside the roster"
        )
    assignments: dict[str, list[str]] = {node: [] for node in nodes}
    for item in normalised["subtasks"]:
        assignments[item["node_id"]].append(item["subtask_id"])
    budget = normalised.get("budget") or {}
    max_nodes = budget.get("max_nodes")
    if isinstance(max_nodes, int):
        used = {node for node, ids in assignments.items() if ids}
        _require(len(used) <= max_nodes, "placement uses more nodes than budget.max_nodes")
    return {
        "schema_version": "sparknet-cluster-construction/1",
        "job_id": normalised["job_id"],
        "mode": normalised["mode"],
        "topology": governance_mode,
        "roster": nodes,
        "subtasks": normalised["subtasks"],
        "placement": {
            "topology": governance_mode,
            "assignments": [{"node_id": node, "subtask_ids": ids} for node, ids in sorted(assignments.items()) if ids],
        },
        "truncated": False,
    }


def result_digest(result: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(result, sort_keys=True, indent=2).encode() + b"\n").hexdigest()


def reduce_results(results: Iterable[dict[str, Any]], expected_subtask_ids: Iterable[str]) -> dict[str, Any]:
    """Merge verified partials in subtask order and name every missing subtask."""
    expected = list(dict.fromkeys(expected_subtask_ids))
    by_id: dict[str, dict[str, Any]] = {}
    for result in results:
        subtask_id = result.get("subtask_id")
        _require(isinstance(subtask_id, str) and subtask_id, "result has no subtask_id")
        _require(subtask_id in expected, f"result names unexpected subtask {subtask_id}")
        _require(subtask_id not in by_id, f"duplicate result for subtask {subtask_id}")
        by_id[subtask_id] = result
    sections = []
    contributions = []
    for subtask_id in expected:
        result = by_id.get(subtask_id)
        if result is None:
            continue
        output = result.get("output")
        _require(isinstance(output, str), f"result {subtask_id} has no output")
        sections.append(f"## {subtask_id}\n\n{output}")
        contributions.append(
            {
                "subtask_id": subtask_id,
                "participant_node_id": result.get("participant_node_id"),
                "output_sha256": result.get("output_sha256"),
            }
        )
    missing = [subtask_id for subtask_id in expected if subtask_id not in by_id]
    return {
        "schema_version": "sparknet-cluster-reduce/1",
        "output": "\n\n".join(sections),
        "coverage": {"answered": [subtask_id for subtask_id in expected if subtask_id in by_id], "missing": missing},
        "complete": not missing,
        "contributions": contributions,
        "contradictions": [],
    }
