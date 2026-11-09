#!/usr/bin/env python3
"""Deterministic domain context for ``/understand-domain``.

An analyzer agent may add business rules and cross-domain interactions. This
module supplies the evidence it starts from: routes, entities, entry points and
rule-shaped comments. A rule is reported only when the source says it
explicitly; the module never infers a business policy from a name.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .core import scan

ROUTE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"""@(?:app|router|bp|blueprint)\.(get|post|put|patch|delete)\(\s*['"]([^'"]+)['"]""", re.I), "http"),
    (re.compile(r"""(?:app|router|server)\.(get|post|put|patch|delete)\(\s*['"]([^'"]+)['"]""", re.I), "http"),
    (re.compile(r"""(?m)^\s*(?:r\.)?(GET|POST|PUT|PATCH|DELETE)\s+([/\w{}.:-]+)"""), "http"),
)

ENTITY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?m)^\s*class\s+([A-Za-z_]\w*)\s*\((?:[^)]*\b(?:BaseModel|Model|db\.Model|Schema)\b[^)]*)\)"),
    re.compile(r"(?m)^\s*type\s+([A-Za-z_]\w*)\s+struct\b"),
    re.compile(r"(?i)\bCREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([A-Za-z_][\w.]*)"),
)

RULE_RE = re.compile(r"(?i)(?:^|\s)(?:must|must not|never|shall|required|forbidden|only if)\b")
COMMENT_RE = re.compile(r"(?m)^\s*(?://|#|/\*|\*)\s*(.+)$")


def extract_domain_context(root: str | Path, *, excludes: Iterable[str] = ()) -> dict[str, Any]:
    root_path = Path(root).resolve()
    result = scan(root_path, excludes=excludes)
    entities: dict[str, dict[str, Any]] = {}
    routes: list[dict[str, Any]] = []
    rules: list[dict[str, str]] = []
    entry_points: list[dict[str, str]] = []
    cross: set[str] = set()
    for record in result.files:
        try:
            text = (root_path / record.path).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for pattern in ENTITY_PATTERNS:
            for match in pattern.finditer(text):
                name = match.group(1).split(".")[-1]
                entities[name] = {
                    "name": name,
                    "file": record.path,
                    "line": text.count("\n", 0, match.start()) + 1,
                }
        for pattern, kind in ROUTE_PATTERNS:
            for match in pattern.finditer(text):
                routes.append(
                    {
                        "method": match.group(1).upper(),
                        "path": match.group(2),
                        "file": record.path,
                        "line": text.count("\n", 0, match.start()) + 1,
                        "type": kind,
                    }
                )
        for match in COMMENT_RE.finditer(text):
            line = match.group(1).strip()
            if RULE_RE.search(line):
                rules.append({"file": record.path, "line": text.count("\n", 0, match.start()) + 1, "text": line[:500]})
        if record.path.endswith((".py", ".go")):
            for match in re.finditer(r"(?m)^\s*if\s+__name__\s*==\s*['\"]__main__['\"]", text):
                entry_points.append(
                    {"file": record.path, "line": text.count("\n", 0, match.start()) + 1, "type": "cli"}
                )
            for match in re.finditer(r"(?m)^\s*func\s+main\s*\(", text):
                entry_points.append(
                    {"file": record.path, "line": text.count("\n", 0, match.start()) + 1, "type": "cli"}
                )
        parts = record.path.split("/")
        if len(parts) > 1:
            cross.add(parts[0])
    return {
        "entities": sorted(entities.values(), key=lambda item: (item["file"], item["line"])),
        "routes": sorted(routes, key=lambda item: (item["file"], item["line"], item["method"], item["path"])),
        "businessRules": sorted(rules, key=lambda item: (item["file"], item["line"])),
        "entryPoints": sorted(entry_points, key=lambda item: (item["file"], item["line"])),
        "domains": sorted(cross),
        "errors": result.errors,
    }
