#!/usr/bin/env python3
"""Build, verify, search and load the sparknet skill catalogs.

The catalog is a derived index over the installed ``SKILL.md`` files. It keeps
the vendored tree in place, gives every surface one deterministic order, and
lets the model search the long tail without advertising it in every prompt.

Usage::

    scripts/sparknet-skills.py index --role all
    scripts/sparknet-skills.py check
    scripts/sparknet-skills.py groups --role peer
    scripts/sparknet-skills.py search "wiki ingest" --role peer
    scripts/sparknet-skills.py show wiki-ingest --role base
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "shared"))

from skill_catalog import engine  # noqa: E402
from sparknet_loader import load_by_path  # noqa: E402

_CATALOG = load_by_path("sparknet_skill_catalog_cli", REPO_ROOT / "shared" / "sparknet-skill-catalog.py")

ROLE_DIRS = {
    "base": REPO_ROOT / ".opencode" / "skills",
    "peer": REPO_ROOT / "peer-node" / ".opencode" / "skills",
    "master": REPO_ROOT / "master-node" / ".opencode" / "skills",
}
POLICY_PATH = REPO_ROOT / "contracts" / "skill-policy.json"


def policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def group_for(name: str, source_repo: str, *, source_groups: dict[str, str]) -> str:
    """Map a skill to a stable group.

    Source provenance wins; a small name override keeps the wiki, understand,
    Spark and design families together when several repositories ship them.
    """
    if name.startswith("understand"):
        return "understand"
    if name.startswith("wiki-") or name in {"llm-wiki", "cross-linker", "tag-taxonomy", "vault-skill-factory"}:
        return "wiki"
    if name.startswith("spark-") or name in {
        "vllm",
        "gguf",
        "llama-cpp",
        "huggingface-hub",
        "lm-evaluation-harness",
        "pytorch-fsdp",
        "jupyter-live-kernel",
    }:
        return "spark"
    if name in {"frontend-design", "gpt-vis", "antv-g2-chart"} or name.startswith("chart-"):
        return "design"
    return source_groups.get(source_repo) or source_groups.get(f"farm:{source_repo}") or "other"


def base_metadata() -> dict[str, dict]:
    root = ROLE_DIRS["base"]
    manifests = (
        (".sync.json", "farm:wiki"),
        (".understand.json", "understand"),
        (".mattpocock.json", "mattpocock"),
    )
    meta: dict[str, dict] = {}
    for filename, source_repo in manifests:
        data = json.loads((root / filename).read_text(encoding="utf-8"))
        for name, row in data.get("skills", {}).items():
            meta[name] = {
                "source_repo": source_repo,
                "license": row.get("license") or data.get("license") or "MIT",
                "tier": "standard",
            }
    return meta


def role_metadata(role: str) -> dict[str, dict]:
    data = json.loads((ROLE_DIRS[role] / ".inventory.json").read_text(encoding="utf-8"))
    return {
        name: {
            "source_repo": row.get("source_repo") or row.get("source") or "local",
            "license": row.get("license") or "MIT",
            "tier": row.get("tier") or "standard",
        }
        for name, row in data.get("skills", {}).items()
    }


def build(role: str) -> dict:
    settings = policy()
    source_groups = settings.get("source_groups", {})
    meta = base_metadata() if role == "base" else role_metadata(role)
    return engine.build_catalog(
        ROLE_DIRS[role],
        role=role,
        group_for=lambda name, source: group_for(name, source, source_groups=source_groups),
        metadata_for=lambda name: meta.get(name, {}),
        group_order=settings.get("group_order", ()),
        group_descriptions=settings.get("groups", {}),
    )


def catalog_path(role: str) -> Path:
    return ROLE_DIRS[role] / ".catalog.json"


def effective_featured(role: str) -> list[str]:
    settings = policy()
    featured = settings.get("featured", {})
    base = list(featured.get("base", []))
    if role == "base":
        return base
    extra = list(featured.get(role, []))
    merged = []
    for name in [*base, *extra]:
        if name not in merged:
            merged.append(name)
    return merged[: int(settings.get("featured_limit", 35))]


def command_index(args: argparse.Namespace) -> int:
    roles = ("base", "peer", "master") if args.role == "all" else (args.role,)
    for role in roles:
        catalog = build(role)
        engine.write_catalog(catalog_path(role), catalog)
        counts = catalog["counts"]
        print(f"{role}: {counts['skills']} skills in {counts['groups']} groups -> {catalog_path(role)}")
    return 0


def command_check(args: argparse.Namespace) -> list[str]:
    problems: list[str] = []
    roles = ("base", "peer", "master") if args.role == "all" else (args.role,)
    for role in roles:
        path = catalog_path(role)
        if not path.is_file():
            problems.append(f"{role}: catalog missing ({path})")
            continue
        try:
            data = _CATALOG.read_catalog(path)
        except _CATALOG.CatalogError as exc:
            problems.append(f"{role}: {exc}")
            continue
        rows = data.get("skills", {})
        order = data.get("order", [])
        if order != sorted(order):
            # The order is group-priority then id; compare against a rebuild instead.
            pass
        expected = build(role)
        if data.get("counts") != expected.get("counts"):
            problems.append(
                f"{role}: counts differ from disk (catalog {data.get('counts')}, disk {expected.get('counts')})"
            )
        if set(rows) != set(expected.get("skills", {})):
            missing = sorted(set(expected.get("skills", {})) - set(rows))
            extra = sorted(set(rows) - set(expected.get("skills", {})))
            problems.append(f"{role}: catalog/disk mismatch missing={missing[:8]} extra={extra[:8]}")
        if data.get("order") != expected.get("order"):
            problems.append(f"{role}: order is not deterministic")
        for name, entry in sorted(rows.items()):
            try:
                skill = _CATALOG.Catalog([path]).path(name)
            except _CATALOG.CatalogError as exc:
                problems.append(f"{role}/{name}: {exc}")
                continue
            if not skill.is_file():
                problems.append(f"{role}/{name}: SKILL.md missing")
                continue
            if engine.file_digest(skill) != entry.get("sha256"):
                problems.append(f"{role}/{name}: SKILL.md hash mismatch")
    return problems


def command_groups(args: argparse.Namespace) -> int:
    catalog = _CATALOG.Catalog(args.catalog or [catalog_path(args.role)], denied_groups=args.deny_group)
    groups = catalog.groups()
    if args.json:
        print(json.dumps(groups, indent=2, sort_keys=True))
        return 0
    for group, names in groups.items():
        print(f"{group:<14} {len(names):>4}")
    return 0


def _describe(entries: list[dict]) -> None:
    for entry in entries:
        print(_CATALOG.summarise(entry))


def command_list(args: argparse.Namespace) -> int:
    catalog = _CATALOG.Catalog(args.catalog or [catalog_path(args.role)], denied_groups=args.deny_group)
    entries = catalog.list(args.group)
    if not entries:
        print(f"no skills in group {args.group}", file=sys.stderr)
        return 1
    _describe(entries)
    return 0


def command_search(args: argparse.Namespace) -> int:
    catalog = _CATALOG.Catalog(args.catalog or [catalog_path(args.role)], denied_groups=args.deny_group)
    entries = catalog.search(args.query, args.limit)
    if not entries:
        print(f'no skills matched "{args.query}"', file=sys.stderr)
        return 1
    _describe(entries)
    return 0


def command_show(args: argparse.Namespace) -> int:
    catalog = _CATALOG.Catalog(args.catalog or [catalog_path(args.role)], denied_groups=args.deny_group)
    body, skill_dir = catalog.load(args.name, args.reference)
    print(_CATALOG.render_skill(args.name, body, skill_dir))
    return 0


def command_path(args: argparse.Namespace) -> int:
    catalog = _CATALOG.Catalog(args.catalog or [catalog_path(args.role)], denied_groups=args.deny_group)
    print(catalog.path(args.name))
    return 0


def command_featured(args: argparse.Namespace) -> int:
    print("\n".join(effective_featured(args.role)))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(item: argparse.ArgumentParser, role_default: str = "base") -> None:
        item.add_argument("--role", choices=("base", "peer", "master", "all"), default=role_default)
        item.add_argument("--catalog", action="append", type=Path, default=[])
        item.add_argument("--deny-group", action="append", default=[])

    index = sub.add_parser("index", help="build the catalog files")
    common(index, "all")
    index.set_defaults(func=command_index)

    check = sub.add_parser("check", help="verify catalogs against the installed skills")
    common(check, "all")
    check.set_defaults(func=command_check)

    groups = sub.add_parser("groups", help="list groups")
    common(groups)
    groups.add_argument("--json", action="store_true")
    groups.set_defaults(func=command_groups)

    listing = sub.add_parser("list", help="list one group")
    common(listing)
    listing.add_argument("group")
    listing.set_defaults(func=command_list)

    search = sub.add_parser("search", help="search skills")
    common(search)
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=12)
    search.set_defaults(func=command_search)

    show = sub.add_parser("show", help="print one skill")
    common(show)
    show.add_argument("name")
    show.add_argument("--reference", default="")
    show.set_defaults(func=command_show)

    path = sub.add_parser("path", help="print one skill path")
    common(path)
    path.add_argument("name")
    path.set_defaults(func=command_path)

    featured = sub.add_parser("featured", help="print the effective featured ids")
    common(featured)
    featured.set_defaults(func=command_featured)

    args = parser.parse_args(argv)
    result = args.func(args)
    if isinstance(result, list):
        if result:
            for problem in result:
                print(f"sparknet-skills: {problem}", file=sys.stderr)
            return 1
        print("sparknet-skills: clean")
        return 0
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
