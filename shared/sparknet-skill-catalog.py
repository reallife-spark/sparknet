"""Read, merge, search and load sparknet skill catalogs.

This module is a runtime reader, not a service. It opens only the catalog JSON
and the skill files beneath its root, returns text to the caller, and has no
network, authority or vault access. The build-time writer lives in
``scripts/skill_catalog/engine.py``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA = "sparknet-skill-catalog/1"


class CatalogError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _safe_child(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise CatalogError("bad-path", f"path escapes the catalog root: {relative}") from exc
    return candidate


def read_catalog(path: Path | str) -> dict[str, Any]:
    catalog_path = Path(path)
    try:
        value = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError("malformed-catalog", f"{catalog_path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise CatalogError("malformed-catalog", f"{catalog_path}: not {SCHEMA}")
    skills = value.get("skills")
    if not isinstance(skills, dict):
        raise CatalogError("malformed-catalog", f"{catalog_path}: missing skills map")
    return value


class Catalog:
    """A merged, role-scoped view over one or more catalog files."""

    def __init__(self, paths: Iterable[Path | str], *, denied_groups: Iterable[str] = ()) -> None:
        self.paths = [Path(path) for path in paths]
        self.denied = {str(group) for group in denied_groups}
        self.entries: dict[str, dict[str, Any]] = {}
        self.roots: dict[str, Path] = {}
        self.group_order: list[str] = []
        self.group_descriptions: dict[str, str] = {}
        for path in self.paths:
            data = read_catalog(path)
            root = path.parent
            for group, meta in data.get("groups", {}).items():
                if group not in self.group_order:
                    self.group_order.append(group)
                if isinstance(meta, dict):
                    self.group_descriptions.setdefault(group, str(meta.get("description") or ""))
            for skill_id, entry in data["skills"].items():
                if not isinstance(entry, dict):
                    raise CatalogError("bad-entry", f"{path}: {skill_id} is not an object")
                group = str(entry.get("group") or "other")
                if group in self.denied:
                    continue
                merged = dict(entry)
                merged["group"] = group
                merged["id"] = str(merged.get("id") or skill_id)
                self.entries[merged["id"]] = merged
                self.roots[merged["id"]] = root

    def groups(self) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for entry in self.entries.values():
            grouped.setdefault(entry["group"], []).append(entry["id"])
        for names in grouped.values():
            names.sort()
        return dict(sorted(grouped.items(), key=lambda item: (self._order(item[0]), item[0])))

    def _order(self, group: str) -> int:
        try:
            return self.group_order.index(group)
        except ValueError:
            return len(self.group_order)

    def list(self, group: str) -> list[dict[str, Any]]:
        return [self.entries[name] for name in self.groups().get(group, [])]

    def all(self) -> list[dict[str, Any]]:
        return [self.entries[name] for names in self.groups().values() for name in names]

    def get(self, name: str) -> dict[str, Any]:
        entry = self.entries.get(name)
        if entry is None:
            raise CatalogError("missing-skill", f"unknown skill: {name}")
        return entry

    def path(self, name: str) -> Path:
        entry = self.get(name)
        root = self.roots[entry["id"]]
        return _safe_child(root, str(entry.get("path") or f"{entry['id']}/SKILL.md"))

    def load(self, name: str, reference: str = "") -> tuple[str, Path]:
        skill_dir = self.path(name).parent
        target = _safe_child(skill_dir, reference) if reference else self.path(name)
        if not target.is_file():
            raise CatalogError("missing-skill", f"missing skill file: {target}")
        body = target.read_text(encoding="utf-8", errors="replace")
        return body, skill_dir

    def search(self, query: str, limit: int = 12) -> list[dict[str, Any]]:
        q = query.lower().strip()
        tokens = [token for token in re.split(r"[^a-z0-9]+", q) if token]
        scored: list[tuple[int, str, dict[str, Any]]] = []
        for entry in self.entries.values():
            name = str(entry.get("name") or entry["id"]).lower()
            skill_id = str(entry["id"]).lower()
            description = str(entry.get("description") or "").lower()
            references = " ".join(str(item).lower() for item in entry.get("references") or [])
            score = 0
            if skill_id == q:
                score += 100
            elif q and q in skill_id:
                score += 60
            if q and q in name:
                score += 30
            for token in tokens:
                if token == skill_id:
                    score += 40
                elif token in skill_id:
                    score += 18
                if token in name:
                    score += 10
                if token in description:
                    score += 6
                if token in references:
                    score += 2
            if score:
                scored.append((score, skill_id, entry))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [entry for _score, _name, entry in scored[: max(1, limit)]]


def summarise(entry: dict[str, Any]) -> str:
    return f"{entry['id']:<36} {entry.get('description', '')}  [{entry.get('group', 'other')}]"


def render_skill(name: str, body: str, skill_dir: Path) -> str:
    return "\n".join(
        [
            f'<skill_content name="{name}">',
            body.strip(),
            "",
            f"Base directory: {skill_dir}",
            "</skill_content>",
        ]
    )


def load_by_name(paths: Iterable[Path | str], name: str, *, denied_groups: Iterable[str] = ()) -> dict[str, Any]:
    return Catalog(paths, denied_groups=denied_groups).get(name)
