#!/usr/bin/env python3
"""The Master issue ledger and its latest-view index.

The ledger is append-only evidence. A reported issue is operational work, never
knowledge and never authority; this module stores records and derives a view.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def bare_address(address: str) -> str:
    return str(address or "").split("/", 1)[0].strip()


def default_issue_store() -> Path:
    env = os.environ.get("SPARKNET_ISSUE_STORE", "").strip()
    return Path(env) if env else Path("/mnt/log/sparknet-issues.jsonl")


def read_rows(path: Path | str | None) -> list[dict[str, Any]]:
    if not path:
        return []
    source = Path(path)
    if not source.is_file():
        return []
    try:
        lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def latest_rows(rows: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("node_id") or ""), str(row.get("issue_id") or ""))
        if not all(key):
            continue
        current = latest.get(key)
        if current is None or str(row.get("updated_at") or "") >= str(current.get("updated_at") or ""):
            latest[key] = dict(row)
    return latest


class IssueStore:
    """Append-only issue evidence with a latest view and nonce replay set."""

    def __init__(self, path: Path | str, *, state_dir: Path | str | None = None) -> None:
        self.path = Path(path)
        self.state_dir = Path(state_dir) if state_dir else self.path.parent / "issues"
        self.seen_nonces: set[str] = set()
        self.latest: dict[tuple[str, str], dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        self.seen_nonces.clear()
        self.latest.clear()
        for row in read_rows(self.path):
            nonce = row.get("nonce")
            if isinstance(nonce, str) and nonce:
                self.seen_nonces.add(nonce)
            key = (str(row.get("node_id") or ""), str(row.get("issue_id") or ""))
            if not all(key):
                continue
            current = self.latest.get(key)
            if current is None or str(row.get("updated_at") or "") >= str(current.get("updated_at") or ""):
                self.latest[key] = row

    def record(self, report: dict[str, Any], *, source: str) -> str:
        key = (str(report["node_id"]), str(report["issue_id"]))
        current = self.latest.get(key)
        if current is not None and str(report["updated_at"]) <= str(current.get("updated_at") or ""):
            self.seen_nonces.add(str(report["nonce"]))
            return "duplicate"
        row = {
            "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "received_from": bare_address(source),
            **report,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            os.chmod(self.path, 0o600)
        self.latest[key] = row
        self.seen_nonces.add(str(report["nonce"]))
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        return "recorded"

    def listing(self) -> list[dict[str, Any]]:
        return sorted(
            self.latest.values(),
            key=lambda row: (
                str(row.get("received_at") or ""),
                str(row.get("node_id") or ""),
                str(row.get("issue_id") or ""),
            ),
        )
