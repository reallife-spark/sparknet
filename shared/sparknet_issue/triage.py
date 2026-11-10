#!/usr/bin/env python3
"""Append-only triage history and its derived latest view.

A triage transition is a local Master action. The ledger is history; the JSON
view is a cache the console may read. Neither is authority, and neither is
knowledge.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .model import IssueError, authz


class TriageError(IssueError):
    """A triage transition refusal."""


def _iso(value: datetime | None = None) -> str:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class TriageStore:
    """One append-only triage ledger plus a derived latest view."""

    def __init__(self, state_dir: Path | str) -> None:
        self.state_dir = Path(state_dir)
        self.directory = self.state_dir / "issues"
        self.ledger_path = self.directory / "triage.jsonl"
        self.view_path = self.directory / "triage.json"

    def _legacy_view(self) -> dict[str, dict[str, Any]]:
        try:
            value = json.loads(self.view_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(value, dict):
            return {}
        return {str(key): item for key, item in value.items() if isinstance(item, dict)}

    def _ledger_rows(self) -> list[dict[str, Any]]:
        try:
            lines = self.ledger_path.read_text(encoding="utf-8", errors="replace").splitlines()
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

    def view(self) -> dict[str, dict[str, Any]]:
        """The latest triage state keyed by ``node_id:issue_id``.

        The existing view is the seed so an operator can migrate a hand-written
        ``triage.json`` without rewriting history. Ledger rows then apply in
        append order.
        """
        result = self._legacy_view()
        for row in self._ledger_rows():
            node_id = str(row.get("node_id") or "")
            issue_id = str(row.get("issue_id") or "")
            if not node_id or not issue_id:
                continue
            key = f"{node_id}:{issue_id}"
            current = dict(result.get(key, {}))
            for field in ("status", "labels", "actor", "note", "at"):
                if field in row:
                    current[field] = row[field]
            result[key] = current
        return result

    def transition(
        self,
        node_id: str,
        issue_id: str,
        *,
        status: str | None = None,
        labels: list[str] | None = None,
        actor: str = "operator",
        note: str = "",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Append one transition and refresh the derived view."""
        if not str(node_id or "").strip():
            raise TriageError("node_id is required", "invalid")
        if not authz.ISSUE_ID_RE.fullmatch(str(issue_id or "")):
            raise TriageError("issue_id must be a lowercase slug of 3..80 characters", "invalid")
        if status is None and labels is None:
            raise TriageError("a triage transition needs status or labels", "invalid")
        if status is not None and status not in authz.ISSUE_STATUSES:
            raise TriageError(f"status must be one of {sorted(authz.ISSUE_STATUSES)}", "invalid")
        if labels is not None:
            if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
                raise TriageError("labels must be an array of strings", "invalid")
            unknown = sorted(set(labels) - authz.ISSUE_LABELS)
            if unknown:
                raise TriageError(f"labels outside the closed triage vocabulary: {unknown}", "invalid")
        if not isinstance(actor, str) or not actor.strip():
            raise TriageError("actor is required", "invalid")
        if not isinstance(note, str) or len(note) > 2000:
            raise TriageError("note must be a string of at most 2000 characters", "invalid")
        row: dict[str, Any] = {
            "schema": "sparknet-triage/1",
            "node_id": str(node_id),
            "issue_id": str(issue_id),
            "at": _iso(now),
            "actor": actor,
            "note": note,
        }
        if status is not None:
            row["status"] = status
        if labels is not None:
            row["labels"] = sorted(set(labels))
        try:
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            with contextlib.suppress(OSError):
                os.chmod(self.directory, 0o700)
            with self.ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            with contextlib.suppress(OSError):
                os.chmod(self.ledger_path, 0o600)
            self._write_view()
        except OSError as exc:
            raise TriageError(f"triage write failed: {exc}", "write_failed") from exc
        return row

    def _write_view(self) -> None:
        view = self.view()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = json.dumps(view, indent=2, sort_keys=True) + "\n"
        with tempfile.NamedTemporaryFile(
            "w", dir=self.directory, prefix=".triage-", delete=False, encoding="utf-8"
        ) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                with contextlib.suppress(OSError):
                    os.chmod(temporary, 0o600)
                os.replace(temporary, self.view_path)
            finally:
                with contextlib.suppress(OSError):
                    temporary.unlink()
