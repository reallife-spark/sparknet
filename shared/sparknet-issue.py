#!/usr/bin/env python3
"""Path-stable facade for the one local issue model.

Callers load this file by path. The implementation lives in
``shared/sparknet_issue/``; the facade only re-exports the same objects, so the
peer, Master, console and triage CLI never carry a second parser, redaction
table or latest-view rule.

An issue is operational work, not knowledge and not authority. This module does
not sign, verify a signature, grant a capability or install a vault page.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sparknet_issue import (
    IssueDocument,
    IssueError,
    IssueStore,
    TriageError,
    TriageStore,
    authz,
    build_payload,
    default_issue_store,
    issue_files,
    latest_rows,
    load_projection,
    parse_issue_file,
    prepare_payload,
    project,
    read_rows,
    redact,
    split_issue,
    validate_local,
    wire_labels,
)

__all__ = [
    "IssueDocument",
    "IssueError",
    "IssueStore",
    "TriageError",
    "TriageStore",
    "authz",
    "build_payload",
    "default_issue_store",
    "issue_files",
    "latest_rows",
    "load_projection",
    "parse_issue_file",
    "prepare_payload",
    "project",
    "read_rows",
    "redact",
    "split_issue",
    "validate_local",
    "wire_labels",
]
