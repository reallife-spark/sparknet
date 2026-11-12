#!/usr/bin/env python3
"""Read-only Sparknet WebUI console.

Serves the read-only console surfaces behind the Open WebUI origin. Dispatch,
auth and menu metadata come from one `SURFACES` table; `/api/surface` derives
`menus` and `menu_items` from it. On a peer, Learning is a signed read-only
fetch of the Master's sanitized snapshot over 4221. The console is a view over
existing state: it does not sign, grant, train or write. The browser never
receives the console token or the Qdrant API key; the same-origin proxy injects
the token header.

Usage::

    scripts/sparknet-console.py --role peer
    scripts/sparknet-console.py --role master --bind 127.0.0.1 --port 8098
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
from sparknet_loader import load_shared  # noqa: E402 - shared/ is added by path above


def load_issue_module() -> Any:
    return load_shared(
        "sparknet-issue.py",
        "sparknet_console_issue",
        dirs=[ROOT / "shared"],
        error=ConsoleError,
        message="cannot find shared/sparknet-issue.py; the console carries no issue implementation",
    )


def load_vector_view() -> Any:
    return load_shared(
        "sparknet-vector-view.py",
        "sparknet_console_vector_view",
        dirs=[ROOT / "shared"],
        error=ConsoleError,
        message="cannot find shared/sparknet-vector-view.py; the console carries no vector view",
    )


def load_skill_eval_module() -> Any:
    return load_shared(
        "sparknet-skill-eval.py",
        "sparknet_console_skill_eval",
        dirs=[ROOT / "shared"],
        error=ConsoleError,
        message="cannot find shared/sparknet-skill-eval.py; the console carries no eval implementation",
    )


def load_skill_catalog_module() -> Any:
    return load_shared(
        "sparknet-skill-catalog.py",
        "sparknet_console_skill_catalog",
        dirs=[ROOT / "shared"],
        error=ConsoleError,
        message="cannot find shared/sparknet-skill-catalog.py; the console carries no skill catalog",
    )


ROLE_ROOT = {"peer": ROOT / "peer-node", "master": ROOT / "master-node"}
ROLE_CONFIG = {
    "peer": ROOT / "peer-node" / "configs" / "webui" / "console.json",
    "master": ROOT / "master-node" / "configs" / "webui" / "console.json",
}
STATIC = ROOT / "webui" / "console"
SCHEMA = "sparknet-console/1"
MAX_POINTS = 500
TAIL_LINES = 8


class ConsoleError(RuntimeError):
    """A refusal the operator can act on."""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConsoleError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConsoleError(f"{path} is not a JSON object")
    return data


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def read_text(path: Path, limit: int = 200_000) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return None


def tail_jsonl(path: Path, limit: int = TAIL_LINES) -> list[Any]:
    text = read_text(path, limit=200_000)
    if not text:
        return []
    rows: list[Any] = []
    for line in text.splitlines()[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def resolve(role_root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else role_root / path


def token_from_file(path: Path) -> str:
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ConsoleError(f"cannot read console token {path}: {exc}") from exc
    if len(token) < 16:
        raise ConsoleError(f"console token {path} is too short")
    return token


def api_surface(config: dict[str, Any]) -> dict[str, Any]:
    catalog = read_json(ROOT / "contracts" / "model-catalog.json")
    models = []
    if isinstance(catalog, dict):
        models = [
            {"id": model.get("id"), "role": model.get("role"), "status": model.get("status")}
            for model in catalog.get("models", [])
            if model.get("status") == "active"
        ]
    configured = _configured_menu_surfaces(config)
    return {
        "ok": True,
        "role": config.get("role"),
        "node": config.get("node"),
        "title": config.get("title"),
        "menus": [surface.name for surface in configured],
        "menu_items": [_menu_item(surface) for surface in configured],
        "read_only": True,
        "models": models,
    }


def api_foundations(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    """Read-only readiness view of the Step 89 foundation modules."""
    contracts = ROOT / "contracts"
    shared = ROOT / "shared"
    contract_names = (
        "abac-schema.json",
        "event-schema.json",
        "graph-schema.json",
        "hybrid-schema.json",
        "exec-schema.json",
        "collab-schema.json",
        "package-schema.json",
        "agent-schema.json",
        "pipeline-schema.json",
        "self-improvement-schema.json",
        "release-schema.json",
        "data-lake-schema.json",
        "step89-admin-schema.json",
        "step89-matrix.json",
    )
    module_names = (
        "sparknet-abac.py",
        "sparknet-event.py",
        "sparknet-graph.py",
        "sparknet-hybrid.py",
        "sparknet-exec-rpc.py",
        "sparknet-collab.py",
        "sparknet-package.py",
        "sparknet-agent-bus.py",
        "sparknet-pipeline.py",
        "sparknet-event-bus.py",
        "sparknet-self-improve.py",
        "sparknet-release.py",
        "sparknet-data-lake.py",
    )
    contract_state = {name: (contracts / name).is_file() for name in contract_names}
    module_state = {name: (shared / name).is_file() for name in module_names}
    ready = all(contract_state.values()) and all(module_state.values())
    return {
        "ok": True,
        "schema": SCHEMA,
        "role": str(config.get("role") or role_root.name),
        "generated_at": now_iso(),
        "ready": ready,
        "contracts": contract_state,
        "modules": module_state,
    }


def api_mesh(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    paths = config.get("paths") or {}
    result: dict[str, Any] = {"ok": True, "role": config.get("role"), "node": config.get("node"), "errors": []}
    identity = read_json(resolve(role_root, paths.get("identity")) or Path("/nonexistent"))
    result["identity"] = identity if isinstance(identity, dict) else None
    registry = read_json(resolve(role_root, paths.get("registry")) or Path("/nonexistent"))
    nodes = []
    if isinstance(registry, dict):
        for entry in registry.get("authorizations", []):
            if not isinstance(entry, dict):
                continue
            node_identity = entry.get("identity") if isinstance(entry.get("identity"), dict) else {}
            nodes.append(
                {
                    "node_id": node_identity.get("node_id"),
                    "role": node_identity.get("role"),
                    "overlay_ipv4": node_identity.get("overlay_ipv4"),
                    "capabilities": entry.get("capabilities") or [],
                    "department": entry.get("department"),
                    "revoked": bool(entry.get("revoked")),
                    "expires_at": entry.get("expires_at"),
                }
            )
    else:
        result["errors"].append("registry unavailable")
    result["registry"] = {"nodes": nodes, "count": len(nodes)}
    ledger = read_json(resolve(role_root, paths.get("ledger")) or Path("/nonexistent"))
    ledger_rows = ledger.get("blocks") or ledger.get("chain") if isinstance(ledger, dict) else None
    result["ledger"] = {
        "present": isinstance(ledger_rows, list),
        "blocks": len(ledger_rows) if isinstance(ledger_rows, list) else None,
        "head": (ledger_rows[-1].get("block_hash") or ledger_rows[-1].get("hash") if ledger_rows else None),
    }
    share = read_json(resolve(role_root, paths.get("share_regime")) or Path("/nonexistent"))
    result["shares"] = {
        "present": isinstance(share, dict),
        "keys": sorted(share)[:12] if isinstance(share, dict) else [],
    }
    result["telemetry"] = tail_jsonl(resolve(role_root, paths.get("telemetry")) or Path("/nonexistent"))
    result["admin_events"] = tail_jsonl(resolve(role_root, paths.get("admin_events")) or Path("/nonexistent"))
    rfi_dir = resolve(role_root, paths.get("rfi_dir"))
    result["rfi"] = {"count": len(list(rfi_dir.glob("*"))) if rfi_dir and rfi_dir.is_dir() else 0}
    result["updated_at"] = now_iso()
    return result


def _frontmatter_value(text: str, key: str) -> str | None:
    if not text.startswith("---"):
        return None
    block = text.split("---", 2)[1] if text.count("---") >= 2 else ""
    for line in block.splitlines():
        if line.startswith(key + ":"):
            return line.split(":", 1)[1].strip().strip('"').strip("'")
    return None


def _local_gateway_runs(config: dict[str, Any], role_root: Path, limit: int) -> list[dict[str, Any]]:
    """Read this node's delegate runs through the loopback gateway.

    The console never reads the Go store directly: the gateway's owner-only
    local token scopes the request to this role vault. Any transport failure is
    an empty view, never a fallback to a second reader.
    """
    settings = config.get("memory") or {}
    token_path = resolve(role_root, settings.get("local_token_file") or ".state/memory.local.token")
    if token_path is None or not token_path.is_file():
        return []
    try:
        token = token_path.read_text(encoding="utf-8").strip()
        query = urllib.parse.urlencode({"limit": limit})
        request = urllib.request.Request(
            str(settings.get("gateway_url") or "http://127.0.0.1:4093").rstrip("/") + "/v1/delegates/runs?" + query
        )
        request.add_header("Accept", "application/json")
        request.add_header("X-Sparknet-Local-Token", token)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    runs = payload.get("runs")
    if not isinstance(runs, list):
        return []
    return [run for run in runs if isinstance(run, dict)]


def api_projects(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    """Read-only project cards and the recent delegate ledger."""
    root = role_root / "06_Projects"
    projects = []
    for path in sorted(root.glob("*/PROJECT.md")) if root.is_dir() else []:
        text = read_text(path, limit=20_000) or ""
        projects.append(
            {
                "project_id": _frontmatter_value(text, "project_id") or path.parent.name,
                "title": _frontmatter_value(text, "title") or path.parent.name,
                "status": _frontmatter_value(text, "status") or "unknown",
                "path": str(path.parent),
            }
        )
    return {"ok": True, "projects": projects, "runs": _local_gateway_runs(config, role_root, 50)[:20]}


def api_memory(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    """Read the node's typed-memory posture through the local gateway.

    The console never reads a vault or a memory store directly. It carries the
    gateway's local token, which is owner-only, and asks for counts and policy
    only. Content remains on the vault-scoped memory page.
    """
    settings = config.get("memory") or {}
    base = os.environ.get("SPARKNET_MEMORY_GATEWAY_URL") or str(settings.get("gateway_url") or "http://127.0.0.1:4093")
    token_path = resolve(role_root, settings.get("local_token_file") or ".state/memory.local.token")
    vault = resolve(role_root, settings.get("vault_path") or ".") or role_root
    if token_path is None or not token_path.is_file():
        return {"ok": False, "configured": False, "error": "memory gateway token is not present"}
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return {"ok": False, "configured": True, "error": str(exc)}
    # The local token is scoped by the gateway to its role vault. Sending the
    # host-side role path would be rejected when memory runs in a container whose
    # vault is mounted at /srv/sparknet/<role>-node.
    request = urllib.request.Request(base.rstrip("/") + "/v1/memory/status")
    request.add_header("Accept", "application/json")
    request.add_header("X-Sparknet-Local-Token", token)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=10) as response:
            status = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"ok": False, "configured": True, "error": f"gateway HTTP {exc.code}"}
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"ok": False, "configured": True, "error": str(exc)}
    result = {"ok": True, "configured": True, "vault": str(vault), "status": status}
    if config.get("role") == "master":
        spool = resolve(role_root, (config.get("paths") or {}).get("telemetry"))
        fleet: dict[str, dict[str, Any]] = {}
        if spool and spool.is_file():
            for line in (read_text(spool, limit=2_000_000) or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                payload = row.get("payload") if isinstance(row, dict) else None
                memory = payload.get("memory") if isinstance(payload, dict) else None
                node = (row.get("peer_fingerprint") or row.get("node_id") or "")[:12]
                if isinstance(memory, dict):
                    fleet[node] = {
                        "node": node,
                        "records": memory.get("records"),
                        "bytes": memory.get("bytes"),
                        "capture": memory.get("capture"),
                        "last_write": memory.get("last_write"),
                        "by_type": memory.get("by_type") or {},
                    }
        result["fleet"] = list(fleet.values())
    return result


def _step89_nodes(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    mesh = api_mesh(config, role_root)
    return {
        "ok": bool(mesh.get("ok")),
        "count": (mesh.get("registry") or {}).get("count", 0),
        "nodes": (mesh.get("registry") or {}).get("nodes", []),
        "errors": mesh.get("errors", []),
    }


def _step89_queue(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    paths = config.get("paths") or {}
    rfi_dir = resolve(role_root, paths.get("rfi_dir"))
    admin = resolve(role_root, paths.get("admin_events"))
    telemetry = resolve(role_root, paths.get("telemetry"))
    return {
        "ok": True,
        "rfi_requests": len(list(rfi_dir.glob("*"))) if rfi_dir and rfi_dir.is_dir() else 0,
        "admin_events": len(tail_jsonl(admin, limit=500)) if admin else 0,
        "telemetry_reports": len(tail_jsonl(telemetry, limit=500)) if telemetry else 0,
        "read_only": True,
    }


def _step89_kb(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    view = api_qdrant(config, role_root)
    return {
        "ok": bool(view.get("ok")),
        "collections": [row.get("name") for row in view.get("collections", []) if isinstance(row, dict)],
        "count": len(view.get("collections", [])),
        "error": view.get("error"),
        "read_only": True,
    }


def _step89_lake(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    raw = os.environ.get("SPARKNET_UPLIFT_STATE", "").strip()
    root = Path(raw) if raw else Path("/srv/sparknet/uplift")
    if not root.is_dir():
        return {"ok": True, "configured": False, "root": str(root), "records": 0}
    records = sum(1 for path in root.rglob("*") if path.is_file())
    return {"ok": True, "configured": True, "root": str(root), "records": records, "read_only": True}


def _step89_distill(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    status, payload = api_learning(config, role_root)
    if status != 200:
        return {"ok": False, "error": payload.get("error", "distill unavailable")}
    return {
        "ok": True,
        "runs": payload.get("runs", []),
        "models": payload.get("models", []),
        "read_only": True,
    }


def _step89_events(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    paths = config.get("paths") or {}
    telemetry = tail_jsonl(resolve(role_root, paths.get("telemetry")) or Path("/nonexistent"), limit=500)
    admin = tail_jsonl(resolve(role_root, paths.get("admin_events")) or Path("/nonexistent"), limit=500)
    return {
        "ok": True,
        "telemetry": {
            "count": len(telemetry),
            "kinds": sorted({str(row.get("kind")) for row in telemetry if isinstance(row, dict) and row.get("kind")}),
        },
        "admin": {"count": len(admin)},
        "read_only": True,
    }


def _step89_abac(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    schema = read_json(ROOT / "contracts" / "abac-schema.json")
    if not isinstance(schema, dict):
        return {"ok": False, "error": "ABAC contract unavailable"}
    return {
        "ok": True,
        "classifications": schema.get("classifications", []),
        "resource_classes": schema.get("resource_classes", []),
        "decision_fields": schema.get("decision_fields", []),
        "refusal_codes": schema.get("refusal_codes", []),
        "decisions_recorded": False,
        "read_only": True,
    }


def _step89_collab(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    root = role_root / "01_Inbox" / "collab"
    rooms = []
    for path in sorted(root.glob("*/room.json")) if root.is_dir() else []:
        room = read_json(path)
        if not isinstance(room, dict):
            continue
        rooms.append(
            {
                "room_id": room.get("room_id"),
                "classification": room.get("classification"),
                "department": room.get("department"),
                "status": room.get("status"),
                "participants": len(room.get("participants") or []),
                "expires_at": room.get("expires_at"),
            }
        )
    return {"ok": True, "rooms": rooms, "count": len(rooms), "read_only": True}


def _step89_users(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    return {
        "ok": True,
        "configured": False,
        "reason": (
            "user inventory stays behind the signed admin federation; "
            "the read-only console does not hold an Open WebUI admin token"
        ),
    }


def api_step89(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    return {
        "ok": True,
        "schema": "sparknet-step89/1",
        "role": str(config.get("role") or role_root.name),
        "generated_at": now_iso(),
        "read_only": True,
        "nodes": _step89_nodes(config, role_root),
        "queue": _step89_queue(config, role_root),
        "kb": _step89_kb(config, role_root),
        "users": _step89_users(config, role_root),
        "lake": _step89_lake(config, role_root),
        "distill": _step89_distill(config, role_root),
        "events": _step89_events(config, role_root),
        "abac": _step89_abac(config, role_root),
        "collab": _step89_collab(config, role_root),
    }


def api_qdrant(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    module = load_vector_view()
    try:
        view = module.VectorView.from_config(config, role_root)
        version = view.version()
        collections = view.collections()
    except Exception as exc:
        message = getattr(exc, "message", str(exc))
        return {"ok": False, "error": f"Qdrant unavailable: {message}"}
    return {
        "ok": True,
        "version": version,
        "uri": view.uri,
        "api_key": "configured" if view.api_key_configured else "not-configured",
        "collections": collections,
        "map_collections": config.get("qdrant", {}).get("map_collections", []),
        "read_only": True,
    }


def api_map(config: dict[str, Any], role_root: Path, collection: str | None) -> tuple[int, dict[str, Any]]:
    if not collection:
        return 200, {"ok": False, "error": "collection is required"}
    module = load_vector_view()
    try:
        view = module.VectorView.from_config(config, role_root)
        points = view.sample(collection, MAX_POINTS)
        stamp = view.stamp(collection)
    except module.VectorViewError as exc:
        if exc.code == "collection-not-allowed":
            return 403, {"ok": False, "error": exc.message}
        return 200, {"ok": False, "error": exc.message, "points": []}
    except Exception as exc:
        return 200, {"ok": False, "error": f"Qdrant unavailable: {exc}", "points": []}
    rows = module.project_points(points, str(config.get("node")))
    return 200, {
        "ok": True,
        "collection": collection,
        "projection": "deterministic-random-3d-pilot",
        "note": "Pilot projection, not UMAP. Replace with the UMAP pipeline in a later step.",
        "index": {"status": "stamped" if stamp else "unstamped", "stamp": stamp},
        "points": rows,
    }


_LEARNING_CACHE: tuple[float, dict[str, Any]] | None = None


def _node_private_key(role_root: Path) -> Any:
    raw_state = os.environ.get("SPARKNET_STATE_DIR", "").strip()
    if raw_state:
        state = Path(raw_state).expanduser()
        if not state.is_absolute():
            state = role_root / state
    else:
        state = role_root / ".state"
    path = state / "keys" / "ed25519-node.key.b64"
    if not path.is_file():
        raise ConsoleError(f"node key is missing: {path}")
    authz = load_shared("sparknet-authz.py", "sparknet_console_authz", dirs=[ROOT / "shared"], error=ConsoleError)
    try:
        return authz.load_private_key(path)
    except Exception as exc:
        raise ConsoleError(f"cannot load node key: {exc}") from exc


def _master_learning(config: dict[str, Any], role_root: Path) -> tuple[int, dict[str, Any]]:
    """Fetch the sanitized Master Learning snapshot over signed 4221.

    The peer console signs with its own node key; the Master file share trusts
    that key, requires p2p-sync, and has no write route. The response is
    verified against its SHA-256 before it is parsed.
    """
    global _LEARNING_CACHE
    now = time.monotonic()
    if _LEARNING_CACHE and now - _LEARNING_CACHE[0] < 30:
        return 200, _LEARNING_CACHE[1]
    settings = config.get("learning") or {}
    base = str(settings.get("master_file_share_url") or "http://10.100.0.1:4221").rstrip("/")
    path = str(settings.get("status_path") or "/v1/file/learning/status.json")
    try:
        http = load_shared("sparknet-http.py", "sparknet_console_http", dirs=[ROOT / "shared"], error=ConsoleError)
        status, payload = http.post_json(base, "GET", path, {}, _node_private_key(role_root), timeout=10)
    except Exception as exc:
        return 502, {"ok": False, "error": f"Master Learning link unavailable: {exc}"}
    if status != 200 or not payload.get("ok"):
        return 502, {
            "ok": False,
            "error": f"Master Learning link refused: HTTP {status}: {payload.get('reason') or payload.get('error')}",
        }
    try:
        raw = base64.b64decode(str(payload.get("content_b64") or ""), validate=True)
        if hashlib.sha256(raw).hexdigest() != str(payload.get("sha256") or ""):
            return 502, {"ok": False, "error": "Master Learning snapshot digest mismatch"}
        snapshot = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        return 502, {"ok": False, "error": f"Master Learning snapshot invalid: {exc}"}
    if not isinstance(snapshot, dict):
        return 502, {"ok": False, "error": "Master Learning snapshot is not an object"}
    result = {**snapshot, "ok": True, "read_only": True, "source": "master:4221"}
    _LEARNING_CACHE = (now, result)
    return 200, result


def api_learning(config: dict[str, Any], role_root: Path) -> tuple[int, dict[str, Any]]:
    if config.get("role") == "peer":
        return _master_learning(config, role_root)
    if config.get("role") != "master" or not isinstance(config.get("distill"), dict):
        return 403, {"ok": False, "error": "Learning is Master-only"}
    distill = config["distill"]
    config_path = resolve(role_root, distill.get("config")) or Path("/nonexistent")
    state = Path(str(distill.get("state") or "/srv/sparknet/distill"))
    catalog = read_json(ROOT / "contracts" / "model-catalog.json")
    models = []
    if isinstance(catalog, dict):
        models = [
            {"id": model.get("id"), "role": model.get("role"), "status": model.get("status")}
            for model in catalog.get("models", [])
            if model.get("role") in ("teacher", "student")
        ]
    status_path = resolve(role_root, distill.get("status_file"))
    if status_path and status_path.is_file():
        snapshot = read_json(status_path)
        if isinstance(snapshot, dict):
            return 200, {**snapshot, "ok": True, "models": models, "read_only": True}
    cfg = read_json(config_path)
    runs = []
    errors: list[str] = []
    runs_dir = state / "runs"
    try:
        run_dirs = sorted(runs_dir.glob("*"))[-20:] if runs_dir.is_dir() else []
    except OSError as exc:
        run_dirs = []
        errors.append(f"distill state is not readable: {exc}")
    for run_dir in run_dirs:
        plan = read_json(run_dir / "plan.json")
        run = read_json(run_dir / "run.json")
        evaluation = read_json(run_dir / "eval.json")
        card = read_json(run_dir / "model-card.json")
        runs.append(
            {
                "run_id": run_dir.name,
                "state": (plan or {}).get("state") if isinstance(plan, dict) else None,
                "approved": (run or {}).get("approved") if isinstance(run, dict) else None,
                "eval": (evaluation or {}).get("metrics") if isinstance(evaluation, dict) else None,
                "artifact_sha256": (run or {}).get("artifact_sha256") if isinstance(run, dict) else None,
                "signed": bool((run or {}).get("signature_b64")) if isinstance(run, dict) else False,
                "model_card": bool(card),
            }
        )
    return 200, {
        "ok": True,
        "node": config.get("node"),
        "config": cfg if isinstance(cfg, dict) else None,
        "runs": runs,
        "models": models,
        "state_dir": str(state),
        "read_only": True,
        "errors": errors,
    }


UNDERSTAND_MAX_BYTES = 20_000_000


def _understand_candidates(config: dict[str, Any], role_root: Path) -> list[Path]:
    configured = (config.get("paths") or {}).get("understand")
    candidates: list[Path] = []
    if configured:
        resolved = resolve(role_root, configured)
        if resolved:
            candidates.append(resolved)
    for base in (role_root, role_root.parent):
        candidates.append(base / ".understand-anything" / "knowledge-graph.json")
        candidates.append(base / ".ua" / "knowledge-graph.json")
    seen: set[Path] = set()
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in seen:
            unique.append(candidate)
            seen.add(candidate)
    return unique


def api_issues(config: dict[str, Any], role_root: Path) -> tuple[int, dict[str, Any]]:
    """Read the Master's recorded peer work items. Master-only, read-only."""
    if config.get("role") != "master":
        return 403, {"ok": False, "error": "Issues are Master-only"}
    configured = (config.get("paths") or {}).get("issues")
    path = resolve(role_root, configured) if configured else Path("/mnt/log/sparknet-issues.jsonl")
    state_env = os.environ.get("SPARKNET_STATE_DIR", "").strip()
    state_dir = Path(state_env) if state_env else role_root / ".state"
    issue = load_issue_module()
    try:
        projection = issue.load_projection(path, state_dir)
    except Exception as exc:
        return 500, {"ok": False, "error": f"issues: {exc}"}
    return 200, {
        "ok": True,
        "store": str(path) if path else "",
        **projection,
        "read_only": True,
        "note": "Operational work items, not knowledge and not authority.",
    }


def api_skills(config: dict[str, Any], role_root: Path, query: dict[str, list[str]]) -> tuple[int, dict[str, Any]]:
    """Read this role's sorted skill catalog. Read-only: no load, no write."""
    role = str(config.get("role") or "")
    paths = [
        ROOT / ".opencode" / "skills" / ".catalog.json",
        role_root / ".opencode" / "skills" / ".catalog.json",
    ]
    paths = [path for path in paths if path.is_file()]
    if not paths:
        return 404, {"ok": False, "error": "no skill catalog on this node"}
    module = load_skill_catalog_module()
    try:
        catalog = module.Catalog(paths)
    except module.CatalogError as exc:
        return 500, {"ok": False, "error": f"skill catalog: {exc}"}
    q = (query.get("q") or [""])[0].strip()
    group = (query.get("group") or [""])[0].strip()
    try:
        limit = max(1, min(int((query.get("limit") or ["200"])[0]), 2000))
    except ValueError:
        return 400, {"ok": False, "error": "limit must be an integer"}
    if q:
        entries = catalog.search(q, limit)
    elif group:
        entries = catalog.list(group)[:limit]
    else:
        entries = catalog.all()[:limit]
    groups = catalog.groups()
    return 200, {
        "ok": True,
        "role": role,
        "counts": {"skills": len(catalog.entries), "groups": len(groups), "shown": len(entries)},
        "groups": [
            {
                "name": name,
                "count": len(names),
                "description": catalog.group_descriptions.get(name, ""),
            }
            for name, names in groups.items()
        ],
        "skills": [
            {
                "id": entry["id"],
                "name": entry.get("name", entry["id"]),
                "description": entry.get("description", ""),
                "group": entry.get("group", "other"),
                "source_repo": entry.get("source_repo", ""),
                "license": entry.get("license", ""),
                "tier": entry.get("tier", "standard"),
            }
            for entry in entries
        ],
        "read_only": True,
        "note": "Skill instructions; not knowledge and not authority.",
    }


EVAL_FINDINGS_LIMIT = 20


def _project_eval(record: dict[str, Any], *, node: str, run_id: str) -> dict[str, Any]:
    findings = record.get("findings") or []
    return {
        "eval_id": record.get("eval_id", ""),
        "node": node,
        "run_id": run_id,
        "skill": (record.get("skill") or {}).get("name", ""),
        "verdict": record.get("verdict", ""),
        "subject": record.get("subject") or {},
        "evaluator": record.get("evaluator") or {},
        "created_at": record.get("created_at", ""),
        "findings": findings[:EVAL_FINDINGS_LIMIT],
        "findings_total": len(findings),
    }


def api_evals(config: dict[str, Any], role_root: Path) -> dict[str, Any]:
    """Read this node's skill-eval verdicts from its delegate runs.

    A record is audit evidence: it never grants authority and never enters a
    knowledge or KB path. Invalid or tampered records are counted, never shown.
    """
    skill_eval = load_skill_eval_module()
    node = str(config.get("node") or config.get("role") or "local")
    records = []
    invalid = 0
    for run in _local_gateway_runs(config, role_root, 100):
        result = run.get("result") if isinstance(run.get("result"), dict) else {}
        record = result.get("skill_eval")
        if not isinstance(record, dict):
            continue
        try:
            skill_eval.validate_record(record)
        except skill_eval.SkillEvalError:
            invalid += 1
            continue
        records.append(_project_eval(record, node=node, run_id=str(run.get("run_id") or "")))
    reported_path = resolve(role_root, (config.get("evals") or {}).get("reported")) or Path(
        "/mnt/log/sparknet-evals.jsonl"
    )
    for row in tail_jsonl(reported_path):
        report = row.get("report") if isinstance(row, dict) else None
        if not isinstance(report, dict):
            continue
        reported_node = str(report.get("node_id") or "remote")
        report_ref = str(report.get("report_id") or "")
        for record in report.get("records") or []:
            if not isinstance(record, dict):
                continue
            try:
                skill_eval.validate_record(record)
            except skill_eval.SkillEvalError:
                invalid += 1
                continue
            records.append(_project_eval(record, node=reported_node, run_id=report_ref))
    counts = {"total": len(records), "pass": 0, "warn": 0, "fail": 0, "invalid": invalid}
    for item in records:
        if item["verdict"] in ("pass", "warn", "fail"):
            counts[item["verdict"]] += 1
    records.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return {
        "ok": True,
        "node": node,
        "records": records,
        "counts": counts,
        "read_only": True,
        "note": "Audit evidence, not knowledge and not authority.",
    }


def api_understand(config: dict[str, Any], role_root: Path, *, summary: bool = False) -> tuple[int, dict[str, Any]]:
    """Read the derived graph from the role or fabric root.

    The graph is a build artifact, not knowledge and not authority. The route
    is read-only, capped and path-controlled by the console config; it never
    accepts a caller-supplied path.
    """
    candidates = _understand_candidates(config, role_root)
    for path in candidates:
        if not path.is_file():
            continue
        try:
            if path.stat().st_size > UNDERSTAND_MAX_BYTES:
                return 413, {"ok": False, "error": "graph is larger than the read cap", "path": str(path)}
            graph = read_json(path)
        except OSError as exc:
            return 422, {"ok": False, "error": f"cannot read graph: {exc}", "path": str(path)}
        if graph is None:
            return 422, {"ok": False, "error": "cannot read graph", "path": str(path)}
        if (
            not isinstance(graph, dict)
            or not isinstance(graph.get("nodes"), list)
            or not isinstance(graph.get("edges"), list)
        ):
            return 422, {"ok": False, "error": "graph has no nodes/edges arrays", "path": str(path)}
        try:
            label = path.relative_to(role_root).as_posix()
        except ValueError:
            label = str(path)
        if summary:
            return 200, {
                "ok": True,
                "available": True,
                "path": label,
                "project": graph.get("project"),
                "counts": {
                    "nodes": len(graph["nodes"]),
                    "edges": len(graph["edges"]),
                    "layers": len(graph.get("layers") or []),
                    "tour": len(graph.get("tour") or []),
                },
            }
        return 200, {"ok": True, "available": True, "path": label, "graph": graph}
    return 200, {
        "ok": True,
        "available": False,
        "path": str(candidates[0]) if candidates else "",
        "error": "no graph found; run /understand to build it",
    }


@dataclass(frozen=True)
class Endpoint:
    path: str
    handler: Callable[[dict[str, Any], Path, dict[str, list[str]]], Any]
    auth: str = "session"


@dataclass(frozen=True)
class MenuSpec:
    label: str
    href: str
    icon: str


@dataclass(frozen=True)
class Surface:
    name: str
    endpoints: tuple[Endpoint, ...]
    menu: MenuSpec | None = None


def _bind(
    handler: Callable[[dict[str, Any], Path], Any],
) -> Callable[[dict[str, Any], Path, dict[str, list[str]]], Any]:
    def call(config: dict[str, Any], role_root: Path, query: dict[str, list[str]]) -> Any:
        return handler(config, role_root)

    return call


def _bound_map(config: dict[str, Any], role_root: Path, query: dict[str, list[str]]) -> Any:
    return api_map(config, role_root, (query.get("collection") or [None])[0])


def _bound_understand(config: dict[str, Any], role_root: Path, query: dict[str, list[str]]) -> Any:
    return api_understand(config, role_root, summary=(query.get("summary") or [""])[0] == "1")


def _bound_skills(config: dict[str, Any], role_root: Path, query: dict[str, list[str]]) -> Any:
    return api_skills(config, role_root, query)


def _bound_surface(config: dict[str, Any], role_root: Path, query: dict[str, list[str]]) -> Any:
    return api_surface(config)


def _step89(
    handler: Callable[[dict[str, Any], Path], Any],
) -> Callable[[dict[str, Any], Path, dict[str, list[str]]], Any]:
    def call(config: dict[str, Any], role_root: Path, query: dict[str, list[str]]) -> Any:
        return handler(config, role_root)

    return call


#: The one console surface table. A surface may expose several endpoints; its
#: menu metadata is declared once. Every API path is an Endpoint row, so adding
#: a route cannot bypass the auth check or the menu source.
SURFACES: tuple[Surface, ...] = (
    Surface("surface", (Endpoint("/api/surface", _bound_surface),)),
    Surface("foundations", (Endpoint("/api/foundations", _bind(api_foundations)),)),
    Surface(
        "mesh",
        (Endpoint("/api/mesh", _bind(api_mesh), auth="admin"),),
        MenuSpec("Mesh", "#mesh", "mesh"),
    ),
    Surface(
        "vectors",
        (
            Endpoint("/api/qdrant", _bind(api_qdrant), auth="admin"),
            Endpoint("/api/map", _bound_map, auth="admin"),
        ),
        MenuSpec("Vectors", "#vectors", "vectors"),
    ),
    Surface(
        "learning", (Endpoint("/api/learning", _bind(api_learning)),), MenuSpec("Learning", "#learning", "learning")
    ),
    Surface("memory", (Endpoint("/api/memory", _bind(api_memory)),), MenuSpec("Memory", "#memory", "memory")),
    Surface(
        "projects",
        (Endpoint("/api/projects", _bind(api_projects), auth="admin"),),
        MenuSpec("Projects", "#projects", "projects"),
    ),
    Surface(
        "understand",
        (Endpoint("/api/understand", _bound_understand),),
        MenuSpec("Understand", "#understand", "understand"),
    ),
    Surface(
        "issues",
        (Endpoint("/api/issues", _bind(api_issues), auth="admin"),),
        MenuSpec("Issues", "#issues", "issues"),
    ),
    Surface(
        "evals",
        (Endpoint("/api/evals", _bind(api_evals), auth="admin"),),
        MenuSpec("Evals", "#evals", "evals"),
    ),
    Surface(
        "skills",
        (Endpoint("/api/skills", _bound_skills),),
        MenuSpec("Skills", "#skills", "skills"),
    ),
    Surface(
        "step89",
        (
            Endpoint("/api/step89", _step89(api_step89)),
            Endpoint("/api/nodes", _step89(_step89_nodes)),
            Endpoint("/api/queue", _step89(_step89_queue)),
            Endpoint("/api/kb", _step89(_step89_kb)),
            Endpoint("/api/users", _step89(_step89_users)),
            Endpoint("/api/lake", _step89(_step89_lake)),
            Endpoint("/api/distill", _step89(_step89_distill)),
            Endpoint("/api/events", _step89(_step89_events)),
            Endpoint("/api/abac", _step89(_step89_abac)),
            Endpoint("/api/collab", _step89(_step89_collab)),
        ),
    ),
)

MENU_SURFACES = tuple(surface for surface in SURFACES if surface.menu is not None)
API_BY_PATH = {endpoint.path: endpoint for surface in SURFACES for endpoint in surface.endpoints}
PAGE_PATHS = {"", "/"} | {"/" + surface.name for surface in MENU_SURFACES}


def _configured_menu_surfaces(config: dict[str, Any]) -> list[Surface]:
    configured = config.get("menus")
    if configured is None:
        return list(MENU_SURFACES)
    if not isinstance(configured, list) or not all(isinstance(name, str) for name in configured):
        raise ConsoleError("console menus must be a list of surface names")
    known = {surface.name for surface in MENU_SURFACES}
    unknown = sorted(set(configured) - known)
    if unknown:
        raise ConsoleError(f"unknown console menu(s): {', '.join(unknown)}")
    wanted = set(configured)
    return [surface for surface in MENU_SURFACES if surface.name in wanted]


def _menu_item(surface: Surface) -> dict[str, str]:
    if surface.menu is None:
        raise ConsoleError(f"surface {surface.name} has no menu metadata")
    return {
        "id": surface.name,
        "label": surface.menu.label,
        "href": surface.menu.href,
        "icon": surface.menu.icon,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "sparknet-console/1"
    config: dict[str, Any]
    role_root: Path
    token: str
    static_dir: Path
    auth_cache: ClassVar[dict[str, tuple[float, str]]] = {}
    _auth_role: str = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[console] {self.address_string()} {fmt % args}", file=sys.stderr, flush=True)

    def _authorized(self) -> bool:
        supplied = self.headers.get("X-Sparknet-Console-Token") or ""
        if not supplied:
            cookie = self.headers.get("Cookie") or ""
            for part in cookie.split(";"):
                name, _, value = part.strip().partition("=")
                if name == "sparknet_console":
                    supplied = value
                    break
        if supplied and hmac.compare_digest(supplied, self.token):
            self._auth_role = "owner"
            return True
        authorization = self.headers.get("Authorization") or ""
        if authorization.startswith("Bearer "):
            return self._openwebui_allows(authorization[7:].strip())
        return False

    def _openwebui_allows(self, token: str) -> bool:
        """Validate the caller's Open WebUI session token against this role's role."""
        base = str((self.config or {}).get("openwebui_url") or "").rstrip("/")
        if not base or not token:
            return False
        now = time.monotonic()
        cached = self.auth_cache.get(token)
        if cached and now - cached[0] < 30:
            return cached[1] == "allow"
        allowed = False
        try:
            request = urllib.request.Request(f"{base}/api/v1/auths/", headers={"Authorization": f"Bearer {token}"})
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=5) as response:
                data = json.loads(response.read().decode("utf-8"))
            role = str((data or {}).get("role") or "")
            # The console is read-only. Authenticated users may see it on both
            # roles; the Master's Learning snapshot is sanitized and read-only.
            self._auth_role = role
            allowed = role in ("admin", "user")
        except Exception:
            allowed = False
        self.auth_cache[token] = (now, "allow" if allowed else "deny")
        if len(self.auth_cache) > 256:
            self.auth_cache.clear()
        return allowed

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: Any) -> None:
        self._send(status, (json.dumps(value, sort_keys=True) + "\n").encode(), "application/json")

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/"):
            endpoint = API_BY_PATH.get(path)
            if endpoint is None:
                self._json(404, {"ok": False, "error": "unknown API path"})
                return
            if not self._authorized():
                self._json(401, {"ok": False, "error": "console token required"})
                return
            if endpoint.auth == "admin" and self._auth_role not in {"admin", "owner"}:
                self._json(403, {"ok": False, "error": "admin role required for this surface"})
                return
            result = endpoint.handler(self.config, self.role_root, urllib.parse.parse_qs(parsed.query))
            if isinstance(result, tuple):
                status, payload = result
            else:
                status, payload = 200, result
            self._json(status, payload)
            return
        if path in PAGE_PATHS:
            target = self.static_dir / "index.html"
        else:
            target = (self.static_dir / path.lstrip("/")).resolve()
            try:
                target.relative_to(self.static_dir.resolve())
            except ValueError:
                self._send(403, b"forbidden\n", "text/plain")
                return
        if not target.is_file():
            self._send(404, b"not found\n", "text/plain")
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
        }.get(target.suffix, "application/octet-stream")
        self._send(200, target.read_bytes(), content_type)


def _validate_surfaces(config: dict[str, Any]) -> None:
    if len(API_BY_PATH) != sum(len(surface.endpoints) for surface in SURFACES):
        raise ConsoleError("duplicate API path in the console surface table")
    for endpoint in API_BY_PATH.values():
        if endpoint.auth not in {"session", "admin"}:
            raise ConsoleError(f"unknown auth class for {endpoint.path}: {endpoint.auth!r}")
    _configured_menu_surfaces(config)


def make_server(
    config: dict[str, Any], role_root: Path, token: str, static_dir: Path, bind: str, port: int
) -> ThreadingHTTPServer:
    _validate_surfaces(config)
    handler = type(
        "ConsoleHandler",
        (Handler,),
        {"config": config, "role_root": role_root, "token": token, "static_dir": static_dir, "auth_cache": {}},
    )
    return ThreadingHTTPServer((bind, port), handler)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="read-only Sparknet WebUI console")
    parser.add_argument("--role", choices=("peer", "master"), default=os.environ.get("SPARKNET_ROLE", "peer"))
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--static-dir", type=Path, default=STATIC)
    parser.add_argument("--bind", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--token-file", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    role_root = ROLE_ROOT[args.role]
    config_path = args.config or ROLE_CONFIG[args.role]
    try:
        config = load_json(config_path)
        if config.get("schema") != SCHEMA or config.get("role") != args.role:
            raise ConsoleError(f"{config_path} is not a {SCHEMA} for {args.role}")
        token_file = args.token_file or resolve(role_root, config.get("token_file"))
        if token_file is None:
            raise ConsoleError("no token_file in config and no --token-file")
        token = token_from_file(token_file)
        bind = args.bind or str(config.get("bind") or "127.0.0.1")
        port = args.port if args.port is not None else int(config.get("port") or 8099)
        server = make_server(config, role_root, token, args.static_dir, bind, port)
        print(
            f"sparknet-console: {config.get('title')} on http://{bind}:{port}/ (read-only)", file=sys.stderr, flush=True
        )
        server.serve_forever()
    except ConsoleError as exc:
        print(f"sparknet-console: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
