#!/usr/bin/env python3
"""Semantic + agentic retrieval as one explicit bundle.

The two result sets are different evidence. The bundle returns both, with
provenance, and never silently merges them into a single answer. It is data for
the agent, not an answer and not authority.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import PurePosixPath
from typing import Any

BUNDLE_SCHEMA = "sparknet-hybrid/1"
SEMANTIC_SCHEMA = "sparknet-hybrid-semantic/1"
AGENTIC_SCHEMA = "sparknet-hybrid-agentic/1"
CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")
_RANK = {name: index for index, name in enumerate(CLASSIFICATIONS)}


class HybridError(Exception):
    """A fail-closed bundle refusal."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise HybridError(code, message)


def _nonempty(value: Any, field: str, code: str = "bad-result") -> str:
    _require(isinstance(value, str) and bool(value.strip()), code, f"{field} must be a non-empty string")
    return value.strip()


def _path(value: Any) -> str:
    _require(isinstance(value, str) and bool(value.strip()), "bad-result", "path must be a non-empty string")
    _require("\\" not in value and "\x00" not in value, "bad-result", "path contains an unsafe character")
    candidate = PurePosixPath(value.strip())
    _require(
        not candidate.is_absolute() and not any(part in ("..", "", ".") for part in candidate.parts),
        "bad-result",
        "path escapes its vault",
    )
    return candidate.as_posix()


def _classification(value: Any) -> str:
    _require(
        isinstance(value, str) and value in CLASSIFICATIONS,
        "unknown-classification",
        "classification is not in the closed vocabulary",
    )
    return value


def _provenance(value: Any) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "missing-provenance", "provenance must be an object")
    source = _nonempty(value.get("source"), "provenance.source", "missing-provenance")
    digest = value.get("digest")
    _require(
        digest is None or isinstance(digest, str), "missing-provenance", "provenance.digest must be a string or null"
    )
    return {"source": source, "digest": digest}


def _json_value(value: Any, field: str) -> Any:
    _require(value is not None, "bad-result", f"{field} is missing")
    try:
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise HybridError("bad-result", f"{field} is not strict JSON") from exc
    return value


def _timestamp(value: Any) -> datetime:
    _require(isinstance(value, str) and bool(value.strip()), "malformed-bundle", "generated_at must be ISO-8601")
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise HybridError("malformed-bundle", "generated_at is not valid") from exc
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def semantic_result(
    *,
    result_id: str,
    source: str,
    path: str,
    score: float,
    text: str,
    provenance: Mapping[str, Any],
    classification: str,
) -> dict[str, Any]:
    return validate_semantic_result(
        {
            "schema_version": SEMANTIC_SCHEMA,
            "result_id": result_id,
            "source": source,
            "path": path,
            "score": score,
            "text": text,
            "classification": classification,
            "provenance": provenance,
        }
    )


def validate_semantic_result(row: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(row, Mapping), "bad-result", "semantic result must be an object")
    _require(row.get("schema_version") == SEMANTIC_SCHEMA, "bad-result", "unknown semantic result schema")
    score = row.get("score")
    _require(
        isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(float(score)),
        "bad-score",
        "score must be a finite number",
    )
    return {
        "schema_version": SEMANTIC_SCHEMA,
        "result_id": _nonempty(row.get("result_id"), "result_id"),
        "source": _nonempty(row.get("source"), "source"),
        "path": _path(row.get("path")),
        "score": float(score),
        "text": str(row.get("text") or ""),
        "classification": _classification(row.get("classification")),
        "provenance": _provenance(row.get("provenance")),
    }


def agentic_result(
    *,
    result_id: str,
    tool: str,
    action: str,
    result: Any,
    provenance: Mapping[str, Any],
    classification: str,
) -> dict[str, Any]:
    return validate_agentic_result(
        {
            "schema_version": AGENTIC_SCHEMA,
            "result_id": result_id,
            "tool": tool,
            "action": action,
            "result": result,
            "classification": classification,
            "provenance": provenance,
        }
    )


def validate_agentic_result(row: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(row, Mapping), "bad-result", "agentic result must be an object")
    _require(row.get("schema_version") == AGENTIC_SCHEMA, "bad-result", "unknown agentic result schema")
    return {
        "schema_version": AGENTIC_SCHEMA,
        "result_id": _nonempty(row.get("result_id"), "result_id"),
        "tool": _nonempty(row.get("tool"), "tool"),
        "action": _nonempty(row.get("action"), "action"),
        "result": _json_value(row.get("result"), "result"),
        "classification": _classification(row.get("classification")),
        "provenance": _provenance(row.get("provenance")),
    }


def _highest(rows: Sequence[Mapping[str, Any]]) -> str:
    if not rows:
        return "internal"
    names = [_classification(row.get("classification")) for row in rows]
    return max(names, key=lambda name: _RANK[name])


def bundle(
    *,
    query: str,
    semantic: Sequence[Mapping[str, Any]],
    agentic: Sequence[Mapping[str, Any]],
    classification: str | None = None,
    department: str | None = None,
    vault_id: str = "",
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Validate both result sets and return them; the bundle never merges them."""
    _require(isinstance(semantic, (list, tuple)), "malformed-bundle", "semantic must be a list")
    _require(isinstance(agentic, (list, tuple)), "malformed-bundle", "agentic must be a list")
    semantic_rows = [validate_semantic_result(row) for row in semantic]
    agentic_rows = [validate_agentic_result(row) for row in agentic]
    highest = _highest([*semantic_rows, *agentic_rows])
    declared = _classification(classification) if classification is not None else highest
    _require(_RANK[declared] >= _RANK[highest], "classification-downgrade", "bundle classification lowers a result")
    moment = generated_at or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    semantic_rows.sort(key=lambda row: str(row["result_id"]))
    agentic_rows.sort(key=lambda row: str(row["result_id"]))
    return {
        "schema_version": BUNDLE_SCHEMA,
        "query": _nonempty(query, "query", "malformed-bundle"),
        "semantic": semantic_rows,
        "agentic": agentic_rows,
        "generated_at": _iso(moment),
        "classification": declared,
        "department": department,
        "vault_id": vault_id,
    }


def validate_bundle(payload: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(payload, Mapping), "malformed-bundle", "bundle must be an object")
    _require(payload.get("schema_version") == BUNDLE_SCHEMA, "malformed-bundle", "unknown hybrid bundle")
    semantic = payload.get("semantic")
    agentic = payload.get("agentic")
    _require(isinstance(semantic, (list, tuple)), "malformed-bundle", "semantic must be a list")
    _require(isinstance(agentic, (list, tuple)), "malformed-bundle", "agentic must be a list")
    semantic_rows = [validate_semantic_result(row) for row in semantic]
    agentic_rows = [validate_agentic_result(row) for row in agentic]
    highest = _highest([*semantic_rows, *agentic_rows])
    declared = _classification(payload.get("classification"))
    _require(_RANK[declared] >= _RANK[highest], "classification-downgrade", "bundle classification lowers a result")
    _timestamp(payload.get("generated_at"))
    return {
        "schema_version": BUNDLE_SCHEMA,
        "query": _nonempty(payload.get("query"), "query", "malformed-bundle"),
        "semantic": semantic_rows,
        "agentic": agentic_rows,
        "generated_at": str(payload.get("generated_at")),
        "classification": declared,
        "department": payload.get("department"),
        "vault_id": payload.get("vault_id", ""),
    }


def bundle_message(payload: Mapping[str, Any]) -> bytes:
    """Canonical bytes of the validated bundle; a cross-language vector target."""
    normalised = validate_bundle(payload)
    return json.dumps(normalised, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False).encode(
        "utf-8"
    )


def render_for_agent(payload: Mapping[str, Any]) -> str:
    """Render both validated sets with provenance; never a merged answer."""
    normalised = validate_bundle(payload)
    lines = [f"# Retrieval bundle: {normalised['query']}", ""]
    for heading, key in (("Semantic results", "semantic"), ("Agentic results", "agentic")):
        lines.append(f"## {heading}")
        rows = normalised[key]
        if not rows:
            lines.append("(none)")
        for row in rows:
            lines.append(
                "- `{}` — source `{}` — provenance `{}`".format(
                    row["result_id"],
                    row["provenance"].get("source", ""),
                    json.dumps(row["provenance"], sort_keys=True),
                )
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
