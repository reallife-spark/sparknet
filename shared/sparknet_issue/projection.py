#!/usr/bin/env python3
"""The one read projection for recorded issues and triage state."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .store import latest_rows, read_rows
from .triage import TriageStore


def _labels(value: Any) -> list[str]:
    return [str(label) for label in value] if isinstance(value, list) else []


def project(
    rows: Iterable[Mapping[str, Any]],
    triage: Mapping[str, Mapping[str, Any]],
    *,
    body_limit: int = 4000,
) -> dict[str, Any]:
    """Project recorded issues plus triage state into the console view."""
    issues: list[dict[str, Any]] = []
    for row in latest_rows(rows).values():
        node_id = str(row.get("node_id") or "")
        issue_id = str(row.get("issue_id") or "")
        key = f"{node_id}:{issue_id}"
        state = dict(triage.get(key, {})) if isinstance(triage.get(key), dict) else {}
        tier_labels = _labels(state.get("labels")) if "labels" in state else _labels(row.get("labels"))
        tier_status = str(state.get("status") or row.get("status") or "open")
        item = dict(row)
        item["body"] = str(item.get("body") or "")[:body_limit]
        item["triage"] = state
        item["effective_status"] = tier_status
        item["effective_labels"] = tier_labels
        issues.append(item)
    issues.sort(key=lambda item: (str(item.get("node_id") or ""), str(item.get("issue_id") or "")))
    counts = {
        "total": len(issues),
        "open": sum(1 for item in issues if item["effective_status"] not in {"done", "wontfix"}),
        "needs_triage": sum(1 for item in issues if "needs-triage" in item["effective_labels"]),
        "ready_for_agent": sum(1 for item in issues if "ready-for-agent" in item["effective_labels"]),
    }
    return {"issues": issues, "counts": counts}


def load_projection(
    issue_path: Path | str | None,
    state_dir: Path | str,
    *,
    body_limit: int = 4000,
) -> dict[str, Any]:
    """Read the ledger and triage view, then project without writing."""
    return project(read_rows(issue_path), TriageStore(state_dir).view(), body_limit=body_limit)
