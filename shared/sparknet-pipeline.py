#!/usr/bin/env python3
"""O1→O2→O5 knowledge pipeline.

O1 is an accepted, signed/sanitized inbox note. O2 is an append to the dated
daily log. O5 is a staged candidate that a human promotes into 05_Knowledge/.
The pipeline never deletes the O1 source, never lowers classification and never
promotes without an explicit confirmation.
"""

from __future__ import annotations

import hashlib
import re
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

ABAC = load_shared("sparknet-abac.py", "sparknet_pipeline_abac")
PROV = load_shared("sparknet-provenance.py", "sparknet_pipeline_provenance")
SLUG_RE = re.compile(r"[^a-z0-9]+")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
O5_CATEGORIES = ("concepts", "entities", "skills", "synthesis", "projects", "references")
ELIGIBLE_STATES = ("signed", "sanitized")


class PipelineError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _slug(text: str) -> str:
    value = SLUG_RE.sub("-", text.lower()).strip("-")[:80]
    return value or "item"


def _today(value: str | None = None) -> str:
    if value:
        if not DATE_RE.fullmatch(value):
            raise PipelineError("bad-date", "--today must be YYYY-MM-DD")
        return value
    return datetime.now(timezone.utc).date().isoformat()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _note(vault: Path, path: Path) -> tuple[dict[str, Any], bytes]:
    try:
        return PROV.split_note(path.read_bytes())
    except (OSError, PROV.ProvenanceError) as exc:
        raise PipelineError("unreadable-source", f"{path}: {exc}") from exc


def _attributes(meta: Mapping[str, Any], rel: str) -> tuple[str, str | None]:
    classification = meta.get("classification")
    if not isinstance(classification, str) or classification not in ABAC.CLASSIFICATIONS:
        raise PipelineError("missing-classification", f"{rel} has no valid O1 classification")
    department = meta.get("department")
    if department is not None and not isinstance(department, str):
        raise PipelineError("bad-department", f"{rel} department must be a string")
    return classification, (department.strip() or None if isinstance(department, str) else None)


def _captured(meta: Mapping[str, Any], fallback: str) -> str:
    value = meta.get("captured")
    if isinstance(value, str) and DATE_RE.fullmatch(value):
        return value
    return fallback


def _source_title(meta: Mapping[str, Any], body: bytes, rel: str) -> str:
    title = meta.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    for line in body.decode("utf-8", "replace").splitlines():
        if line.startswith("# "):
            return line[2:].strip() or Path(rel).stem
    return Path(rel).stem


def _o2_target(vault: Path, day: str) -> tuple[Path, str]:
    primary = vault / "02_Daily" / f"{day}.md"
    if not primary.exists():
        return primary, "create"
    try:
        frontmatter, _body = PROV.split_note(primary.read_bytes())
    except (OSError, PROV.ProvenanceError):
        return vault / "02_Daily" / f"{day}-o2.md", "create-companion"
    if "tracking" not in frontmatter:
        return vault / "02_Daily" / f"{day}-o2.md", "create-companion"
    return primary, "append"


def plan(vault: Path, *, today: str | None = None) -> dict[str, Any]:
    """Return a deterministic O1→O2→O5 plan; writes nothing."""
    root = Path(vault).resolve()
    day = _today(today)
    inbox = root / "01_Inbox"
    if not inbox.is_dir():
        raise PipelineError("missing-inbox", f"{inbox} does not exist")
    entries = []
    for path in sorted(inbox.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        if "collab" in Path(rel).parts:
            continue
        try:
            frontmatter, body = _note(root, path)
            tracking = frontmatter.get("tracking")
            validity = tracking.get("validity") if isinstance(tracking, dict) else None
            state = validity.get("state") if isinstance(validity, dict) else None
            if state not in ELIGIBLE_STATES:
                entries.append({"source": rel, "status": "skipped", "reason": f"validity={state or 'missing'}"})
                continue
            meta = {key: value for key, value in frontmatter.items() if key != "tracking"}
            classification, department = _attributes(meta, rel)
            raw = path.read_bytes()
            digest = _digest(raw)
            title = _source_title(meta, body, rel)
            captured = _captured(meta, day)
            slug = _slug(title)
            o2, action = _o2_target(root, captured)
            o5 = root / "_staging" / "o5" / f"{captured}-{slug}.md"
            status = "ready"
            reason = ""
            if o2.exists():
                try:
                    text = o2.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    text = ""
                if f"o2-source: {digest}" in text:
                    status, reason = "already-applied", "digest already in O2"
            if o5.exists():
                try:
                    candidate_meta, _ = PROV.split_note(o5.read_bytes())
                except (OSError, PROV.ProvenanceError):
                    candidate_meta = {}
                if candidate_meta.get("source_sha256") == digest:
                    if status == "ready":
                        status, reason = "already-staged", "candidate already staged"
                else:
                    status, reason = "conflict", "O5 staging path exists with another digest"
            entries.append(
                {
                    "source": rel,
                    "title": title,
                    "source_sha256": digest,
                    "classification": classification,
                    "department": department,
                    "captured": captured,
                    "o2_target": o2.relative_to(root).as_posix(),
                    "o2_action": action,
                    "o5_target": o5.relative_to(root).as_posix(),
                    "status": status,
                    "reason": reason,
                }
            )
        except PipelineError as exc:
            entries.append({"source": rel, "status": "skipped", "reason": exc.code})
    return {"ok": True, "today": day, "entries": entries}


def _tracking(record: Mapping[str, Any], node: str) -> dict[str, Any]:
    return {
        "schema": "sparknet-tracking/1",
        "owner_id": str(record.get("owner_id") or ""),
        "owner_node": str(record.get("owner_node") or node),
        "owner_ref": PROV.USER_RECORD_REF,
        "validity": {"state": "unsigned"},
        "conversation": [],
        "shares": [],
        "agent": "pipeline",
        "model": "local",
        "approvals": [],
    }


def _write_signed(
    vault: Path, target: Path, meta: dict[str, Any], body: bytes, *, record: Mapping[str, Any], node: str
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = PROV.emit_note({**meta, "tracking": _tracking(record, node)}, body)
    signed = PROV.sign_note(raw, vault, agent="pipeline", model="local")
    target.write_bytes(signed)


def _section(entry: Mapping[str, Any], body: bytes) -> bytes:
    text = body.decode("utf-8", "replace").rstrip()
    return (
        f"## {entry['title']}\n\n"
        f"<!-- o2-source: {entry['source_sha256']} -->\n"
        f"- source: `{entry['source']}`\n"
        f"- sha256: `{entry['source_sha256']}`\n"
        f"- classification: `{entry['classification']}`\n\n"
        f"{text}\n"
    ).encode()


def apply_plan(vault: Path, entries: list[Mapping[str, Any]], *, confirm: bool = False) -> dict[str, Any]:
    """Apply ready entries; O5 is staged, never promoted."""
    if not confirm:
        raise PipelineError("confirmation-required", "apply requires --confirm")
    root = Path(vault).resolve()
    record = PROV.parse_user_record(root)
    if not PROV.user_is_filled(record):
        raise PipelineError("user-record-unfilled", "run `make user-init` before applying the pipeline")
    node = PROV._node_id(root)
    applied = []
    conflicts = [entry for entry in entries if entry.get("status") == "conflict"]
    if conflicts:
        raise PipelineError("conflict", f"{len(conflicts)} O5 staging conflict(s); resolve them before applying")
    for entry in entries:
        if entry.get("status") not in ("ready",):
            continue
        source = root / str(entry["source"])
        _frontmatter, body = _note(root, source)
        day = str(entry["captured"])
        o2 = root / str(entry["o2_target"])
        section = _section(entry, body)
        if entry["o2_action"] == "append":
            o2_frontmatter, o2_body = PROV.split_note(o2.read_bytes())
            o2_meta = {key: value for key, value in o2_frontmatter.items() if key != "tracking"}
            o2_meta["updated"] = day
            o2_body = o2_body.rstrip() + b"\n\n" + section
            o2_frontmatter["tracking"] = o2_frontmatter.get("tracking", _tracking(record, node))
            raw = PROV.emit_note({**o2_meta, "tracking": o2_frontmatter["tracking"]}, o2_body)
            o2.write_bytes(PROV.sign_note(raw, root, agent="pipeline", model="local"))
        else:
            _write_signed(
                root,
                o2,
                {
                    "title": f"O2 daily log — {day}",
                    "type": "o2-log",
                    "updated": day,
                    "captured": day,
                    "classification": entry["classification"],
                    **({"department": entry["department"]} if entry.get("department") else {}),
                    "source_path": entry["source"],
                    "source_sha256": entry["source_sha256"],
                },
                b"# O2 daily log\n\n" + section,
                record=record,
                node=node,
            )
        o5 = root / str(entry["o5_target"])
        _write_signed(
            root,
            o5,
            {
                "title": entry["title"],
                "type": "o5-candidate",
                "updated": day,
                "captured": day,
                "classification": entry["classification"],
                **({"department": entry["department"]} if entry.get("department") else {}),
                "source_path": entry["source"],
                "source_sha256": entry["source_sha256"],
                "stage": "o5",
            },
            body,
            record=record,
            node=node,
        )
        applied.append({"source": entry["source"], "o2": entry["o2_target"], "o5": entry["o5_target"]})
    return {"ok": True, "applied": applied}


def promote(vault: Path, candidate: str, category: str, *, confirm: bool = False) -> dict[str, Any]:
    """Promote one staged O5 candidate into 05_Knowledge/<category>/."""
    if not confirm:
        raise PipelineError("confirmation-required", "promote requires --confirm")
    if category not in O5_CATEGORIES:
        raise PipelineError("bad-category", f"category must be one of {', '.join(O5_CATEGORIES)}")
    root = Path(vault).resolve()
    source = (root / candidate).resolve()
    staging = (root / "_staging" / "o5").resolve()
    try:
        source.relative_to(staging)
    except ValueError as exc:
        raise PipelineError("bad-candidate", "candidate must be under _staging/o5/") from exc
    if not source.is_file():
        raise PipelineError("missing-candidate", f"{candidate} does not exist")
    frontmatter, body = _note(root, source)
    meta = {key: value for key, value in frontmatter.items() if key != "tracking"}
    if meta.get("type") != "o5-candidate":
        raise PipelineError("bad-candidate", "candidate is not an o5-candidate note")
    tracking = frontmatter.get("tracking")
    validity = tracking.get("validity") if isinstance(tracking, dict) else None
    if (validity or {}).get("state") not in ELIGIBLE_STATES:
        raise PipelineError("unsigned-candidate", "candidate must be signed or sanitized")
    target = root / "05_Knowledge" / category / source.name
    if target.exists():
        raise PipelineError("target-exists", f"{target.relative_to(root)} already exists")
    PROV.parse_user_record(root)
    meta["type"] = "knowledge"
    meta["updated"] = _today(meta.get("captured") if isinstance(meta.get("captured"), str) else None)
    meta["promoted_from"] = source.relative_to(root).as_posix()
    raw = PROV.emit_note({**meta, "tracking": tracking}, body)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(PROV.sign_note(raw, root, agent="pipeline", model="local"))
    source.unlink()
    return {"ok": True, "target": target.relative_to(root).as_posix()}
