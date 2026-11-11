#!/usr/bin/env python3
"""Project memory lifecycle for 06_Projects.

A project is a signed `PROJECT.md` plus notes, decisions, reports and citations.
The project's machine memory (delegate runs, shared blackboard) lives in the
vault's memory store, not in the vault pages. This CLI is the operator's path:

    sparknet-project.py new my-project --title "My project" --vault .
    sparknet-project.py list --vault .
    sparknet-project.py run my-project --task "Compare three options"
    sparknet-project.py report my-project --run-id <id> --title "Option memo"

A report is written only after the operator invokes `report`; the delegate
drafts in its workspace and never writes the vault. The report is signed with
the user key through the one provenance implementation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "shared"
sys.path.insert(0, str(SHARED))
from sparknet_loader import load_shared  # noqa: E402 - path-loaded shared implementation

prov = load_shared("sparknet-provenance.py", "sparknet_provenance_project")
SKILL_EVAL = load_shared("sparknet-skill-eval.py", "sparknet_skill_eval_project")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def vault(arg: str) -> Path:
    path = Path(arg or os.environ.get("SPARKNET_VAULT") or ".").expanduser().resolve()
    if not (path / "00_System" / "user.md").is_file():
        raise SystemExit(f"not a role vault: {path}")
    return path


def projects_root(root: Path) -> Path:
    path = root / "06_Projects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise SystemExit("project slug is empty")
    return slug[:64]


def frontmatter(path: Path) -> dict[str, Any]:
    try:
        fm, _body = prov.split_note(path.read_bytes())
    except Exception:
        return {}
    return fm if isinstance(fm, dict) else {}


def project_dir(root: Path, slug: str) -> Path:
    return projects_root(root) / slugify(slug)


def find_project(root: Path, slug: str) -> Path:
    path = project_dir(root, slug)
    if not (path / "PROJECT.md").is_file():
        raise SystemExit(f"no project {slug!r} under {projects_root(root)}")
    return path


def tracking_block(root: Path) -> str:
    record = prov.parse_user_record(root)
    if not prov.user_is_filled(record):
        raise SystemExit("user record is unfilled; run `make user-init` first")
    return f"""tracking:
  schema: sparknet-tracking/1
  owner_id: {record.get("owner_id")}
  owner_node: {record.get("owner_node")}
  owner_ref: 00_System/user.md
  validity:
    state: unsigned
  conversation: []
  shares: []
  agent: project
  model: local
  approvals: []
"""


def sign_in_vault(root: Path, path: Path, agent: str = "project") -> None:
    path.write_bytes(prov.sign_note(path.read_bytes(), root, agent=agent))


def cmd_new(args: argparse.Namespace) -> int:
    root = vault(args.vault)
    slug = slugify(args.slug)
    directory = project_dir(root, slug)
    if (directory / "PROJECT.md").exists() and not args.force:
        raise SystemExit(f"project already exists: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("NOTES", "DECISIONS", "REPORTS", "SOURCES"):
        (directory / name).mkdir(exist_ok=True)
        keep = directory / name / ".gitkeep"
        if not keep.exists():
            keep.write_text("", encoding="utf-8")
    delegates = args.delegates or "project-orchestrator,project-researcher,project-reviewer,report-writer"
    project = f"""---
title: {args.title or slug}
project_id: {slug}
status: active
owner: {args.owner or "owner"}
scope: {args.scope or "06_Projects/" + slug}
updated: {now()}
memory_policy:
  capture: true
  share: false
  retention_days: {args.retention_days}
delegates: [{delegates}]
{tracking_block(root)}---

# {args.title or slug}

## Goal

{args.goal or "Describe the outcome this project should produce."}

## Boundaries

- Project pages live under `06_Projects/{slug}/`.
- Delegate workspaces are outside the vault; raw traces never enter it.
- A report enters `REPORTS/` only after an operator runs `report`.
- Sharing and forgetting are explicit owner controls.

## Delegates

- `project-orchestrator` decomposes the request.
- `project-researcher` gathers evidence.
- `project-reviewer` applies the code-review, tdd and impl-validator rubrics
  (`.opencode/skills/<name>/SKILL.md`) and returns one
  `sparknet-skill-eval/1` record (`contracts/skill-eval-schema.json`).
- `report-writer` drafts the report.
"""
    (directory / "PROJECT.md").write_text(project, encoding="utf-8")
    sign_in_vault(root, directory / "PROJECT.md")
    plan = f"""---
title: {args.title or slug} — plan
project_id: {slug}
updated: {now()}
{tracking_block(root)}---

# Plan

- [ ] Define the deliverable and its evidence.
- [ ] Run the bounded delegate plan.
- [ ] Review the result against the code-review/tdd/impl-validator rubrics and
      record a `sparknet-skill-eval/1` verdict.
- [ ] Approve and file the report (blocked unless the verdict is `pass` when
      `--require-review` is used).
"""
    (directory / "PLAN.md").write_text(plan, encoding="utf-8")
    sign_in_vault(root, directory / "PLAN.md")
    print(json.dumps({"ok": True, "project": str(directory), "project_id": slug}, indent=2))
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    root = vault(args.vault)
    rows = []
    for path in sorted(projects_root(root).glob("*/PROJECT.md")):
        fm = frontmatter(path)
        rows.append(
            {
                "project_id": fm.get("project_id") or path.parent.name,
                "title": fm.get("title") or path.parent.name,
                "status": fm.get("status") or "unknown",
                "path": str(path.parent),
            }
        )
    print(json.dumps({"ok": True, "projects": rows}, indent=2))
    return 0


def _state_dir(root: Path) -> Path:
    explicit = os.environ.get("SPARKNET_STATE_DIR", "").strip()
    return Path(explicit) if explicit else root / ".state"


def _local_token(root: Path) -> str:
    path = _state_dir(root) / "memory.local.token"
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def gateway(root: Path) -> str:
    return os.environ.get("SPARKNET_MEMORY_GATEWAY_URL", "http://127.0.0.1:4093").rstrip("/")


def call(root: Path, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    token = _local_token(root)
    if not token:
        raise SystemExit("missing memory.local.token; run the node setup first")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(gateway(root) + path, data=data, method=method)
    request.add_header("Accept", "application/json")
    request.add_header("X-Sparknet-Local-Token", token)
    request.add_header("X-Sparknet-Vault-Path", str(root))
    request.add_header("X-Sparknet-User", os.environ.get("SPARKNET_OWNER_ID", "local"))
    if data is not None:
        request.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode("utf-8"))
        except Exception:
            return exc.code, {"ok": False, "error": raw.decode("utf-8", "replace")}
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return 503, {"ok": False, "error": str(exc)}


def cmd_run(args: argparse.Namespace) -> int:
    root = vault(args.vault)
    directory = find_project(root, args.slug)
    fm = frontmatter(directory / "PROJECT.md")
    harness = args.harness or "opencode"
    plan = {
        "project_id": fm.get("project_id") or directory.name,
        "user_id": os.environ.get("SPARKNET_OWNER_ID", "local"),
        "tasks": [
            {
                "task_id": f"task-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                "description": args.task,
                "harness": harness,
                "assigned_agent": args.agent or "project-orchestrator",
                "workspace": str(root),
                "permissions": {"workspace_mode": "read_only", "network": "none"},
                "budget": {"max_wall_time_seconds": args.timeout, "max_steps": args.steps},
            }
        ],
    }
    status, payload = call(root, "POST", "/v1/delegates/plan", {"plan": plan})
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if status < 400 else 2


def _run_view(root: Path, run_id: str) -> dict[str, Any]:
    status, payload = call(
        root,
        "GET",
        "/v1/delegates/runs/" + urllib.parse.quote(run_id) + "?" + urllib.parse.urlencode({"vault_path": str(root)}),
    )
    if status >= 400 or not isinstance(payload, dict):
        raise SystemExit(f"run {run_id} is not available: {payload}")
    return payload.get("run") or payload


def cmd_report(args: argparse.Namespace) -> int:
    root = vault(args.vault)
    directory = find_project(root, args.slug)
    run = _run_view(root, args.run_id)
    result = run.get("result") or {}
    task = run.get("task") or {}
    if args.require_review:
        record = None
        if args.skill_eval:
            try:
                record = json.loads(Path(args.skill_eval).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SystemExit(f"cannot read the skill-eval record: {exc}") from exc
        else:
            record = result.get("skill_eval")
        if record is None:
            raise SystemExit("review required but no skill-eval record was supplied or returned")
        try:
            SKILL_EVAL.validate_record(record)
        except SKILL_EVAL.SkillEvalError as exc:
            raise SystemExit(f"invalid skill-eval record: {exc}") from exc
        if record["verdict"] != "pass":
            raise SystemExit(f"review verdict is {record['verdict']}; a report needs a pass")
    slug = re.sub(r"[^a-z0-9]+", "-", (args.title or "report").lower()).strip("-") or "report"
    destination = directory / "REPORTS" / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d')}-{slug}.md"
    if destination.exists() and not args.force:
        raise SystemExit(f"report exists: {destination}")
    body = f"""---
title: {args.title or "Report"} — {directory.name}
project_id: {directory.name}
run_id: {run.get("run_id", args.run_id)}
updated: {now()}
{tracking_block(root)}---

# {args.title or "Report"}

## Task

{task.get("description", "")}

## Outcome

{result.get("summary") or result.get("output") or run.get("error") or "No summary returned."}

## Evidence

- run: `{run.get("run_id", args.run_id)}`
- status: `{run.get("status", "unknown")}`
- harness: `{run.get("harness", "unknown")}`

## Files changed

{os.linesep.join(f"- `{path}`" for path in (result.get("files_changed") or [])) or "- none reported"}

## Verification

{result.get("verification") or "No host verification command was configured."}
"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(body, encoding="utf-8")
    destination.write_bytes(prov.sign_note(destination.read_bytes(), root, agent="report-writer", model="local"))
    print(json.dumps({"ok": True, "report": str(destination)}, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = vault(args.vault)
    directory = find_project(root, args.slug)
    fm = frontmatter(directory / "PROJECT.md")
    status, payload = call(
        root, "GET", "/v1/delegates/runs?" + urllib.parse.urlencode({"vault_path": str(root), "limit": 100})
    )
    runs = payload.get("runs") if isinstance(payload, dict) else []
    print(
        json.dumps(
            {
                "ok": True,
                "project_id": fm.get("project_id") or directory.name,
                "title": fm.get("title") or directory.name,
                "status": fm.get("status"),
                "runs": [
                    {
                        "run_id": r.get("run_id"),
                        "status": r.get("status"),
                        "task": (r.get("task") or {}).get("description"),
                    }
                    for r in runs
                    if (r.get("project_id") or "") in ("", fm.get("project_id") or directory.name)
                ][:20],
            },
            indent=2,
        )
    )
    return 0 if status < 400 else 2


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="manage 06_Projects memory, delegates and reports")
    p.add_argument("--vault", default=".", help="role vault root (default: .)")
    sub = p.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="create a project")
    new.add_argument("slug")
    new.add_argument("--title", default="")
    new.add_argument("--goal", default="")
    new.add_argument("--owner", default="")
    new.add_argument("--scope", default="")
    new.add_argument("--delegates", default="")
    new.add_argument("--retention-days", type=int, default=90)
    new.add_argument("--force", action="store_true")
    new.set_defaults(func=cmd_new)

    listing = sub.add_parser("list", help="list projects")
    listing.set_defaults(func=cmd_list)

    run = sub.add_parser("run", help="hand a bounded task to a delegate")
    run.add_argument("slug")
    run.add_argument("--task", required=True)
    run.add_argument("--harness", default="opencode")
    run.add_argument("--agent", default="")
    run.add_argument("--timeout", type=int, default=900)
    run.add_argument("--steps", type=int, default=80)
    run.set_defaults(func=cmd_run)

    report = sub.add_parser("report", help="file a signed report from a run")
    report.add_argument("slug")
    report.add_argument("--run-id", required=True)
    report.add_argument("--title", default="")
    report.add_argument("--force", action="store_true")
    report.add_argument(
        "--require-review",
        action="store_true",
        help="refuse to file the report without a valid, passing skill-eval record",
    )
    report.add_argument(
        "--skill-eval",
        default="",
        help="path to a sparknet-skill-eval/1 JSON record (default: the run result's skill_eval field)",
    )
    report.set_defaults(func=cmd_report)

    status = sub.add_parser("status", help="show project and run status")
    status.add_argument("slug")
    status.set_defaults(func=cmd_status)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
