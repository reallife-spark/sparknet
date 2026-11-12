#!/usr/bin/env python3
"""Read-only MCP server for the local sparknet skill catalog.

OpenCode starts this process over stdio. It exposes search and load over the
same catalog the CLI reads; it does not write, sign, grant or fetch anything.

Usage::

    sparknet-skills-mcp.py --catalog .opencode/skills/.catalog.json
    sparknet-skills-mcp.py --catalog ../.opencode/skills/.catalog.json \
        --catalog .opencode/skills/.catalog.json --deny-group security
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# shared/ is not on sys.path; load the reader beside this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_by_path

_CATALOG = load_by_path("sparknet_skill_catalog_mcp", Path(__file__).with_name("sparknet-skill-catalog.py"))

TOOLS = [
    {
        "name": "skills_groups",
        "description": "List skill groups available on this node, with counts and descriptions.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "skills_list",
        "description": "List the skills in one group, sorted by id.",
        "inputSchema": {
            "type": "object",
            "properties": {"group": {"type": "string"}},
            "required": ["group"],
            "additionalProperties": False,
        },
    },
    {
        "name": "skills_search",
        "description": "Search skill ids, names, descriptions and references. Use this before guessing a skill name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "number", "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "skills_load",
        "description": "Load one skill's SKILL.md, or one supporting reference file, by exact id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "reference": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "skills_path",
        "description": "Return the absolute path of one skill's SKILL.md by exact id.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
]


def _text(value: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": value}]}


def _catalog(args: argparse.Namespace) -> Any:
    return _CATALOG.Catalog(args.catalog, denied_groups=args.deny_group)


def _call(args: argparse.Namespace, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    catalog = _catalog(args)
    if name == "skills_groups":
        groups = catalog.groups()
        descriptions: dict[str, str] = {}
        for path in catalog.paths:
            for group, meta in _CATALOG.read_catalog(path).get("groups", {}).items():
                descriptions.setdefault(group, str(meta.get("description") or ""))
        lines = [f"{group:<14} {len(names):>4}  {descriptions.get(group, '')}" for group, names in groups.items()]
        return _text("\n".join(["Groups:", "", *lines]))
    if name == "skills_list":
        group = str(arguments.get("group") or "")
        if not group:
            raise _CATALOG.CatalogError("bad-entry", "group is required")
        entries = catalog.list(group)
        if not entries:
            return _text(f"No skills in group {group}.")
        lines = [f"Group {group} ({len(entries)} skills):", ""]
        lines.extend(_CATALOG.summarise(entry) for entry in entries)
        return _text("\n".join(lines))
    if name == "skills_search":
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise _CATALOG.CatalogError("bad-entry", "query is required")
        limit = int(arguments.get("limit") or 12)
        entries = catalog.search(query, limit)
        if not entries:
            return _text(f'No skills matched "{query}".')
        return _text("\n".join(_CATALOG.summarise(e) for e in entries))
    if name == "skills_path":
        return _text(str(catalog.path(str(arguments.get("name") or ""))))
    if name == "skills_load":
        skill = str(arguments.get("name") or "")
        reference = str(arguments.get("reference") or "")
        body, skill_dir = catalog.load(skill, reference)
        label = f"{skill}/{reference}" if reference else skill
        return _text(_CATALOG.render_skill(label, body, skill_dir))
    raise _CATALOG.CatalogError("bad-entry", f"unknown tool: {name}")


def _send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", action="append", type=Path, required=True)
    parser.add_argument("--deny-group", action="append", default=[])
    args = parser.parse_args(argv)
    for path in args.catalog:
        if not path.is_file():
            print(f"sparknet-skills-mcp: missing catalog: {path}", file=sys.stderr)
            return 1
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = request.get("method")
        request_id = request.get("id")
        if request_id is None:
            continue
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "sparknet-skills", "version": "1"},
                }
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = request.get("params") or {}
                result = _call(args, str(params.get("name") or ""), params.get("arguments") or {})
            elif method == "ping":
                result = {}
            else:
                _send(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": f"unknown method: {method}"},
                    }
                )
                continue
            _send({"jsonrpc": "2.0", "id": request_id, "result": result})
        except _CATALOG.CatalogError as exc:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32000, "message": str(exc), "data": {"code": exc.code}},
                }
            )
        except Exception as exc:  # fail closed, never crash the stdio loop
            _send({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32603, "message": str(exc)}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
