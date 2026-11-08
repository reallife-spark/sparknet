#!/usr/bin/env python3
"""Read-only Sparknet WebUI console.

Serves the Mesh, Vectors and Learning pages behind the Open WebUI
origin. On a peer, Learning is a signed read-only fetch of the Master's
sanitized snapshot over 4221. It is a view over existing state: it does not
sign, grant, train or write. The browser never receives the console token or the Qdrant API key; the
same-origin proxy injects the token header.

Usage::

    scripts/sparknet-console.py --role peer
    scripts/sparknet-console.py --role master --bind 127.0.0.1 --port 8098
"""

from __future__ import annotations

import argparse
import base64
import fnmatch
import hashlib
import hmac
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

ROOT = Path(__file__).resolve().parent.parent
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


def qdrant_key(config: dict[str, Any], role_root: Path) -> str | None:
    explicit = os.environ.get("SPARKNET_QDRANT_API_KEY") or os.environ.get("QDRANT_API_KEY")
    if explicit:
        return explicit
    path = resolve(role_root, (config.get("qdrant") or {}).get("api_key_file"))
    if path and path.is_file():
        try:
            return path.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None
    return None


def allowed_collection(name: str, config: dict[str, Any]) -> bool:
    qdrant = config.get("qdrant") or {}
    excluded = [str(prefix) for prefix in qdrant.get("excluded_prefixes", [])]
    if any(name.startswith(prefix) for prefix in excluded):
        return False
    return any(fnmatch.fnmatch(name, str(pattern)) for pattern in qdrant.get("allowed_collections", []))


def qdrant_request(
    config: dict[str, Any],
    role_root: Path,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    timeout: float = 15,
) -> Any:
    qdrant = config.get("qdrant") or {}
    base = str(qdrant.get("uri") or "http://127.0.0.1:6333").rstrip("/")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    key = qdrant_key(config, role_root)
    if key:
        request.add_header("api-key", key)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8")) if raw else None


def project_points(points: list[dict[str, Any]], node: str) -> list[dict[str, Any]]:
    """A deterministic 3D random projection for the pilot cloud.

    It is not UMAP. It preserves rough neighbourhoods and lets the canvas show
    real sampled vectors without adding a second ML runtime. The label in the
    response says so.
    """
    pairs: list[tuple[dict[str, Any], list[float]]] = []
    for point in points:
        vector = point.get("vector")
        if isinstance(vector, dict):
            vector = next((value for value in vector.values() if isinstance(value, list)), None)
        if not isinstance(vector, list):
            continue
        try:
            pairs.append((point, [float(value) for value in vector]))
        except (TypeError, ValueError):
            continue
    if not pairs:
        return []
    dim = len(pairs[0][1])
    axes = []
    for axis in range(3):
        axes.append(
            [
                int.from_bytes(hashlib.sha256(f"{dim}:{axis}:{index}".encode()).digest()[:4], "big") / 2**32 - 0.5
                for index in range(dim)
            ]
        )
    projected = [
        [sum(value * coeff for value, coeff in zip(vector, axis, strict=True)) for axis in axes] for _, vector in pairs
    ]
    max_abs = [max(abs(row[axis]) for row in projected) or 1.0 for axis in range(3)]
    rows: list[dict[str, Any]] = []
    for (point, _vector), xyz in zip(pairs, projected, strict=True):
        payload = point.get("payload") if isinstance(point.get("payload"), dict) else {}
        label = (
            payload.get("label")
            or payload.get("doc_id")
            or payload.get("path")
            or payload.get("trace_id")
            or str(point.get("id"))
        )
        rows.append(
            {
                "x": round(xyz[0] / max_abs[0], 4),
                "y": round(xyz[1] / max_abs[1], 4),
                "z": round(xyz[2] / max_abs[2], 4),
                "role": str(payload.get("role") or payload.get("kind") or "knowledge"),
                "label": str(label)[:160],
                "node": str(payload.get("node_id") or node),
                "run_id": payload.get("run_id"),
            }
        )
    return rows


def api_surface(config: dict[str, Any]) -> dict[str, Any]:
    catalog = read_json(ROOT / "contracts" / "model-catalog.json")
    models = []
    if isinstance(catalog, dict):
        models = [
            {"id": model.get("id"), "role": model.get("role"), "status": model.get("status")}
            for model in catalog.get("models", [])
            if model.get("status") == "active"
        ]
    return {
        "ok": True,
        "role": config.get("role"),
        "node": config.get("node"),
        "title": config.get("title"),
        "menus": config.get("menus", []),
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
    runs = []
    settings = config.get("memory") or {}
    token_path = resolve(role_root, settings.get("local_token_file") or ".state/memory.local.token")
    if token_path and token_path.is_file():
        try:
            token = token_path.read_text(encoding="utf-8").strip()
            query = urllib.parse.urlencode({"limit": 50})
            request = urllib.request.Request(
                str(settings.get("gateway_url") or "http://127.0.0.1:4093").rstrip("/") + "/v1/delegates/runs?" + query
            )
            request.add_header("Accept", "application/json")
            request.add_header("X-Sparknet-Local-Token", token)
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
            runs = payload.get("runs") or []
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
            runs = []
    return {"ok": True, "projects": projects, "runs": runs[:20]}


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
            for line in read_text(spool, limit=2_000_000).splitlines():
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
    try:
        root = qdrant_request(config, role_root, "GET", "/")
        listing = qdrant_request(config, role_root, "GET", "/collections")
    except Exception as exc:
        return {"ok": False, "error": f"Qdrant unavailable: {exc}"}
    names = []
    for row in (listing or {}).get("result", {}).get("collections", []):
        if isinstance(row, dict) and row.get("name"):
            name = str(row["name"])
            if allowed_collection(name, config):
                names.append(name)
    collections = []
    for name in sorted(names)[:20]:
        try:
            info = qdrant_request(config, role_root, "GET", f"/collections/{urllib.parse.quote(name)}")
        except Exception:
            info = None
        detail = (info or {}).get("result", {}) if isinstance(info, dict) else {}
        vectors = ((detail.get("config") or {}).get("params") or {}).get("vectors")
        vector_size = None
        distance = None
        if isinstance(vectors, dict) and vectors:
            first = next(iter(vectors.values()))
            if isinstance(first, dict):
                vector_size = first.get("size")
                distance = first.get("distance")
        elif isinstance(vectors, dict):
            vector_size = vectors.get("size")
            distance = vectors.get("distance")
        collections.append(
            {
                "name": name,
                "status": detail.get("status"),
                "points_count": detail.get("points_count"),
                "vectors_count": detail.get("vectors_count"),
                "vector_size": vector_size,
                "distance": distance,
            }
        )
    return {
        "ok": True,
        "version": (root or {}).get("version") if isinstance(root, dict) else None,
        "uri": (config.get("qdrant") or {}).get("uri"),
        "api_key": "configured" if qdrant_key(config, role_root) else "not-configured",
        "collections": collections,
        "map_collections": config.get("qdrant", {}).get("map_collections", []),
        "read_only": True,
    }


def api_map(config: dict[str, Any], role_root: Path, collection: str | None) -> tuple[int, dict[str, Any]]:
    if not collection:
        return 200, {"ok": False, "error": "collection is required"}
    if not allowed_collection(collection, config):
        return 403, {"ok": False, "error": "collection is outside this surface"}
    try:
        result = qdrant_request(
            config,
            role_root,
            "POST",
            f"/collections/{urllib.parse.quote(collection)}/points/scroll",
            {"limit": MAX_POINTS, "with_payload": True, "with_vector": True},
        )
    except Exception as exc:
        return 200, {"ok": False, "error": f"Qdrant unavailable: {exc}", "points": []}
    points = (result or {}).get("result", {}).get("points", []) if isinstance(result, dict) else []
    rows = project_points([point for point in points if isinstance(point, dict)], str(config.get("node")))
    return 200, {
        "ok": True,
        "collection": collection,
        "projection": "deterministic-random-3d-pilot",
        "note": "Pilot projection, not UMAP. Replace with the UMAP pipeline in a later step.",
        "points": rows,
    }


_LEARNING_CACHE: tuple[float, dict[str, Any]] | None = None


def _load_shared_module(filename: str, name: str) -> Any:
    path = ROOT / "shared" / filename
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ConsoleError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


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
    authz = _load_shared_module("sparknet-authz.py", "sparknet_console_authz")
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
        http = _load_shared_module("sparknet-http.py", "sparknet_console_http")
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


class Handler(BaseHTTPRequestHandler):
    server_version = "sparknet-console/1"
    config: dict[str, Any]
    role_root: Path
    token: str
    static_dir: Path
    auth_cache: ClassVar[dict[str, tuple[float, str]]] = {}

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
            if not self._authorized():
                self._json(401, {"ok": False, "error": "console token required"})
                return
            if path == "/api/surface":
                self._json(200, api_surface(self.config))
            elif path == "/api/mesh":
                self._json(200, api_mesh(self.config, self.role_root))
            elif path == "/api/qdrant":
                self._json(200, api_qdrant(self.config, self.role_root))
            elif path == "/api/map":
                params = urllib.parse.parse_qs(parsed.query)
                collection = (params.get("collection") or [None])[0]
                status, payload = api_map(self.config, self.role_root, collection)
                self._json(status, payload)
            elif path == "/api/learning":
                status, payload = api_learning(self.config, self.role_root)
                self._json(status, payload)
            elif path == "/api/memory":
                self._json(200, api_memory(self.config, self.role_root))
            elif path == "/api/foundations":
                self._json(200, api_foundations(self.config, self.role_root))
            elif path == "/api/projects":
                self._json(200, api_projects(self.config, self.role_root))
            elif path == "/api/step89":
                self._json(200, api_step89(self.config, self.role_root))
            elif path in (
                "/api/nodes",
                "/api/queue",
                "/api/kb",
                "/api/users",
                "/api/lake",
                "/api/distill",
                "/api/events",
                "/api/abac",
                "/api/collab",
            ):
                key = path.removeprefix("/api/")
                view = {
                    "nodes": _step89_nodes,
                    "queue": _step89_queue,
                    "kb": _step89_kb,
                    "users": _step89_users,
                    "lake": _step89_lake,
                    "distill": _step89_distill,
                    "events": _step89_events,
                    "abac": _step89_abac,
                    "collab": _step89_collab,
                }[key](self.config, self.role_root)
                self._json(200, view)
            else:
                self._json(404, {"ok": False, "error": "unknown API path"})
            return
        if path in ("", "/", "/mesh", "/vectors", "/learning", "/memory", "/projects"):
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


def make_server(
    config: dict[str, Any], role_root: Path, token: str, static_dir: Path, bind: str, port: int
) -> ThreadingHTTPServer:
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
