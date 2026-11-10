#!/usr/bin/env python3
"""Command-line seam for the Understand core.

The Go service and the opencode skills call this CLI with JSON on stdout. It
never opens a socket and never writes outside the requested output path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .algebra import diff_graphs, normalize_graph, validate_graph
from .build import build_from_fragments, build_graph
from .domain import extract_domain_context
from .figma import scan_figma
from .knowledge import build_knowledge_graph, parse_knowledge_base
from .production import scan


def _emit(value: Any, out: str | None) -> None:
    text = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if out:
        destination = Path(out)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def _excludes(values: list[str] | None) -> list[str]:
    return list(values or [])


def cmd_scan(args: argparse.Namespace) -> int:
    result = scan(args.root, excludes=_excludes(args.exclude))
    _emit(result.as_dict(), args.out)
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    graph, issues = build_graph(
        args.root,
        excludes=_excludes(args.exclude),
        analyzed_at=args.analyzed_at,
        description=args.description,
        kind=args.kind,
    )
    _emit(graph, args.out)
    if issues:
        for issue in issues:
            print(f"{issue['level']}: {issue['message']}", file=sys.stderr)
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if isinstance(payload, list):
        fragments = payload
        project = {
            "name": args.name,
            "languages": [],
            "frameworks": [],
            "description": "",
            "analyzedAt": args.analyzed_at or "",
            "gitCommitHash": "",
        }
    else:
        fragments = payload.get("fragments", [])
        project = payload.get("project", {})
    graph, issues = build_from_fragments(fragments, project, kind=args.kind)
    _emit(graph, args.out)
    for issue in issues:
        print(f"{issue['level']}: {issue['message']}", file=sys.stderr)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    graph = json.loads(Path(args.input).read_text(encoding="utf-8"))
    issues = validate_graph(graph)
    _emit({"valid": not any(issue["level"] == "fatal" for issue in issues), "issues": issues}, args.out)
    return 0 if not any(issue["level"] == "fatal" for issue in issues) else 1


def cmd_knowledge(args: argparse.Namespace) -> int:
    if args.manifest:
        _emit(parse_knowledge_base(args.root, excludes=_excludes(args.exclude)), args.out)
        return 0
    graph, issues = build_knowledge_graph(args.root, excludes=_excludes(args.exclude), analyzed_at=args.analyzed_at)
    _emit(graph, args.out)
    for issue in issues:
        print(f"{issue['level']}: {issue['message']}", file=sys.stderr)
    return 0


def cmd_domain(args: argparse.Namespace) -> int:
    _emit(extract_domain_context(args.root, excludes=_excludes(args.exclude)), args.out)
    return 0


def cmd_figma(args: argparse.Namespace) -> int:
    graph, issues = scan_figma(args.input)
    _emit(graph, args.out)
    for issue in issues:
        print(f"{issue['level']}: {issue['message']}", file=sys.stderr)
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    old = json.loads(Path(args.old).read_text(encoding="utf-8"))
    new = json.loads(Path(args.new).read_text(encoding="utf-8"))
    _emit(diff_graphs(old, new), args.out)
    return 0


def cmd_normalize(args: argparse.Namespace) -> int:
    graph = json.loads(Path(args.input).read_text(encoding="utf-8"))
    _emit(normalize_graph(graph), args.out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sparknet-understand", description="code-understanding graph")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_parser = sub.add_parser("scan", help="fingerprint a tree")
    scan_parser.add_argument("--root", default=".")
    scan_parser.add_argument("--exclude", action="append")
    scan_parser.add_argument("--out")
    scan_parser.set_defaults(func=cmd_scan)

    build = sub.add_parser("build", help="build a code graph")
    build.add_argument("--root", default=".")
    build.add_argument("--out")
    build.add_argument("--exclude", action="append")
    build.add_argument("--analyzed-at")
    build.add_argument("--description", default="")
    build.add_argument("--kind", default="codebase", choices=("codebase", "knowledge", "design"))
    build.set_defaults(func=cmd_build)

    merge = sub.add_parser("merge", help="merge fragments supplied by the Go service")
    merge.add_argument("--input", required=True)
    merge.add_argument("--out")
    merge.add_argument("--name", default="project")
    merge.add_argument("--analyzed-at")
    merge.add_argument("--kind", default="codebase", choices=("codebase", "knowledge", "design"))
    merge.set_defaults(func=cmd_merge)

    validate = sub.add_parser("validate", help="validate a graph")
    validate.add_argument("--input", default=".ua/knowledge-graph.json")
    validate.add_argument("--out")
    validate.set_defaults(func=cmd_validate)

    knowledge = sub.add_parser("knowledge", help="build a knowledge-base graph")
    knowledge.add_argument("--root", default=".")
    knowledge.add_argument("--out")
    knowledge.add_argument("--exclude", action="append")
    knowledge.add_argument("--analyzed-at")
    knowledge.add_argument("--manifest", action="store_true", help="emit the deterministic scan instead of a graph")
    knowledge.set_defaults(func=cmd_knowledge)

    domain = sub.add_parser("domain", help="extract domain context")
    domain.add_argument("--root", default=".")
    domain.add_argument("--out")
    domain.add_argument("--exclude", action="append")
    domain.set_defaults(func=cmd_domain)

    figma = sub.add_parser("figma", help="turn a Figma document into a design graph")
    figma.add_argument("--input", required=True)
    figma.add_argument("--out")
    figma.set_defaults(func=cmd_figma)

    diff = sub.add_parser("diff", help="diff two graphs")
    diff.add_argument("--old", required=True)
    diff.add_argument("--new", required=True)
    diff.add_argument("--out")
    diff.set_defaults(func=cmd_diff)

    normalize = sub.add_parser("normalize", help="normalize a graph")
    normalize.add_argument("--input", required=True)
    normalize.add_argument("--out")
    normalize.set_defaults(func=cmd_normalize)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"sparknet-understand: {exc}", file=sys.stderr)
        return 2
