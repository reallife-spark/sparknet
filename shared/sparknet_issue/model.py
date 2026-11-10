#!/usr/bin/env python3
"""Local issue documents and the one wire-payload builder.

An issue is operational work. This module owns local markdown parsing,
validation and redaction; ``shared/sparknet-authz.py`` remains the envelope and
signature owner. It never signs, grants authority or installs knowledge.
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SHARED_DIR = Path(__file__).resolve().parent.parent
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

from sparknet_loader import load_shared  # noqa: E402 - shared/ is added by path above


class IssueError(RuntimeError):
    """A local issue refusal with a stable reason code."""

    def __init__(self, message: str, reason: str = "invalid") -> None:
        super().__init__(message)
        self.reason = reason


authz = load_shared(
    "sparknet-authz.py",
    "sparknet_issue_authz",
    dirs=[SHARED_DIR],
    error=IssueError,
    message="cannot find shared/sparknet-authz.py; the issue module carries no local authz copy",
)
yaml = load_shared(
    "sparknet-yaml.py",
    "sparknet_issue_yaml",
    dirs=[SHARED_DIR],
    error=IssueError,
    message="cannot find shared/sparknet-yaml.py; the issue module carries no local YAML parser",
)

#: One policy table for peer and Master. A secret-shaped issue is refused, never
#: partially redacted: the peer must fix the source, and the Master re-checks.
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\b(api[_-]?key|token|password|passwd|secret|private[_-]?key)\b\s*[:=]\s*[A-Za-z0-9_./+=~-]{12,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
)

LINK_KINDS = frozenset({"file", "commit", "url", "share"})


@dataclass(frozen=True)
class IssueDocument:
    """One parsed local issue file."""

    meta: dict[str, Any]
    body: str
    path: Path | None = None


def _iso(value: datetime) -> str:
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise IssueError(f"{field} is required", "invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IssueError(f"{field} is not an ISO-8601 timestamp", "invalid") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def split_issue(text: str) -> tuple[dict[str, Any], str]:
    """Split local markdown into frontmatter mapping and body."""
    if not text.startswith("---"):
        raise IssueError("missing frontmatter", "invalid")
    end = text.find("\n---", 3)
    if end < 0:
        raise IssueError("unterminated frontmatter", "invalid")
    try:
        meta = yaml.parse_yaml_subset(text[3:end])
    except Exception as exc:
        raise IssueError(f"frontmatter: {exc}", "invalid") from exc
    if not isinstance(meta, dict):
        raise IssueError("frontmatter is not a mapping", "invalid")
    return meta, text[end + 4 :].lstrip("\n")


def _validate_links(links: Any) -> list[dict[str, Any]]:
    if links is None:
        return []
    if not isinstance(links, list):
        raise IssueError("links must be an array", "invalid")
    checked: list[dict[str, Any]] = []
    for item in links:
        if not isinstance(item, dict):
            raise IssueError("links must contain objects", "invalid")
        kind = item.get("kind")
        ref = item.get("ref")
        if kind not in LINK_KINDS or not isinstance(ref, str) or not ref.strip():
            raise IssueError("each link needs a known kind and a non-empty ref", "invalid")
        checked.append(item)
    return checked


def validate_local(meta: dict[str, Any], body: str, *, path: Path | None = None) -> IssueDocument:
    """Validate one local issue document against the local contract."""
    if not isinstance(meta, dict):
        raise IssueError("frontmatter is not a mapping", "invalid")
    if meta.get("schema") != authz.ISSUE_SCHEMA:
        raise IssueError(f"schema must be {authz.ISSUE_SCHEMA}", "invalid")
    issue_id = str(meta.get("id") or "")
    if not authz.ISSUE_ID_RE.fullmatch(issue_id):
        raise IssueError("id must be a lowercase slug of 3..80 characters", "invalid")
    if path is not None and path.stem != issue_id:
        raise IssueError(f"id must match the file stem {path.stem!r}", "invalid")
    title = meta.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > authz.ISSUE_MAX_TITLE:
        raise IssueError(f"title must be a non-empty string of at most {authz.ISSUE_MAX_TITLE} characters", "invalid")
    if "\n" in title or "\r" in title:
        raise IssueError("title must be a single line", "invalid")
    if not isinstance(body, str) or len(body.encode("utf-8")) > authz.ISSUE_MAX_BODY:
        raise IssueError(f"body must be at most {authz.ISSUE_MAX_BODY} bytes", "invalid")
    status = meta.get("status")
    if status not in authz.ISSUE_STATUSES:
        raise IssueError(f"status must be one of {sorted(authz.ISSUE_STATUSES)}", "invalid")
    labels = meta.get("labels")
    if not isinstance(labels, list) or any(not isinstance(label, str) or not label for label in labels):
        raise IssueError("labels must be an array of strings", "invalid")
    _validate_links(meta.get("links"))
    reporter = meta.get("reporter")
    if not isinstance(reporter, str) or not reporter.strip():
        raise IssueError("reporter is required", "invalid")
    if not isinstance(meta.get("source"), str) or len(str(meta.get("source"))) > 500:
        raise IssueError("source must be a string of at most 500 characters", "invalid")
    _parse_timestamp(meta.get("created_at"), "created_at")
    _parse_timestamp(meta.get("updated_at"), "updated_at")
    digest = meta.get("body_sha256")
    if not isinstance(digest, str) or digest != hashlib.sha256(body.encode("utf-8")).hexdigest():
        raise IssueError("body_sha256 does not match the body", "body_digest")
    return IssueDocument(meta=dict(meta), body=body, path=path)


def parse_issue_file(path: Path) -> IssueDocument:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise IssueError(f"cannot read {path}: {exc}", "unreadable") from exc
    meta, body = split_issue(text)
    return validate_local(meta, body, path=path)


def issue_files(root: Path) -> list[Path]:
    directory = Path(root) / ".scratch" / "issues"
    return sorted(directory.glob("*.md")) if directory.is_dir() else []


def redact(meta: dict[str, Any], body: str) -> None:
    """Refuse secret-shaped title, body or link content."""
    for pattern in SECRET_PATTERNS:
        if pattern.search(body) or pattern.search(str(meta.get("title") or "")):
            raise IssueError("secret-shaped content", "secret_shaped")
        for link in meta.get("links") or []:
            if isinstance(link, dict) and pattern.search(str(link.get("ref") or "")):
                raise IssueError("secret-shaped link", "secret_shaped")


def wire_labels(meta: dict[str, Any]) -> list[str]:
    """Carry only the closed wire vocabulary; local free-form labels stay local."""
    return [str(label) for label in (meta.get("labels") or []) if str(label) in authz.ISSUE_LABELS]


def build_payload(
    meta: dict[str, Any],
    body: str,
    *,
    authz: Any | None = None,
    node: str,
    fingerprint: str,
) -> dict[str, Any]:
    """Build the signed envelope's body; signing stays in sparknet-http."""
    envelope = authz or globals()["authz"]
    if meta.get("schema") != envelope.ISSUE_SCHEMA:
        raise IssueError(f"schema must be {envelope.ISSUE_SCHEMA}", "invalid")
    try:
        return envelope.build_issue_report(
            issue_id=str(meta.get("id") or ""),
            node_id=node,
            peer_fingerprint=fingerprint,
            title=str(meta.get("title") or ""),
            body=body,
            status=str(meta.get("status") or "open"),
            labels=wire_labels(meta),
            links=_validate_links(meta.get("links")),
            source=str(meta.get("source") or "."),
            updated_at=str(meta.get("updated_at") or "") or None,
        )
    except envelope.AuthzError as exc:
        raise IssueError(str(exc), "invalid") from exc


def prepare_payload(
    text: str,
    *,
    path: Path | None = None,
    node: str,
    fingerprint: str,
    authz: Any | None = None,
    redact_secrets: bool = True,
) -> dict[str, Any]:
    """Parse, validate, redact and build one wire payload."""
    meta, body = split_issue(text)
    document = validate_local(meta, body, path=path)
    if redact_secrets:
        redact(document.meta, document.body)
    return build_payload(document.meta, document.body, authz=authz, node=node, fingerprint=fingerprint)
