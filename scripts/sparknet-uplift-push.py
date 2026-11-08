#!/usr/bin/env python3
"""Push consented uplift artifacts from a peer to the Master's 8091 intake.

The peer keeps a durable outbox: a failed push is written under
``$SPARKNET_STATE_DIR/uplift/outbox`` and retried until the Master accepts it.
Every request is signed with the node identity key; the Master verifies the
signature, the overlay source and the peer-held ``model-uplift`` capability.

Usage::

    scripts/sparknet-uplift-push.py inventory --file inventory.json
    scripts/sparknet-uplift-push.py trace --file traces.jsonl
    scripts/sparknet-uplift-push.py snapshot --collection sparknet-peer
    scripts/sparknet-uplift-push.py snapshot --file local.snapshot --collection sparknet-peer
    scripts/sparknet-uplift-push.py kv --file kv.safetensors.zst --model Qwen/Qwen2.5-32B-Instruct
    scripts/sparknet-uplift-push.py drain
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SERVICE_DIR = Path(__file__).resolve().parent
ROLE_ROOT = SERVICE_DIR.parent
REPO_ROOT = ROLE_ROOT
DEFAULT_ENDPOINT = os.environ.get("SPARKNET_UPLIFT_ENDPOINT", "http://10.100.0.1:8091")
DEFAULT_QDRANT = os.environ.get("SPARKNET_QDRANT_URL", "http://127.0.0.1:6333")
TIMEOUT = float(os.environ.get("SPARKNET_UPLIFT_TIMEOUT", "60"))


class PushError(RuntimeError):
    pass


def _load(name: str, path: Path) -> Any:
    if name in sys.modules:
        return sys.modules[name]
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _shared_dir() -> Path:
    explicit = os.environ.get("SPARKNET_SHARED_DIR", "").strip()
    if explicit:
        return Path(explicit)
    for candidate in (REPO_ROOT / "shared", ROLE_ROOT / "shared"):
        if (candidate / "sparknet-http.py").is_file():
            return candidate
    return REPO_ROOT / "shared"


def authz() -> Any:
    return _load("sparknet_uplift_push_authz", _shared_dir() / "sparknet-authz.py")


def http() -> Any:
    return _load("sparknet_uplift_push_http", _shared_dir() / "sparknet-http.py")


def state_dir() -> Path:
    value = os.environ.get("SPARKNET_STATE_DIR", "").strip()
    if value:
        return Path(value)
    peer = ROLE_ROOT / "peer-node" / ".state"
    return peer if (ROLE_ROOT / "peer-node").is_dir() else ROLE_ROOT / ".state"


def node_id() -> str:
    return os.environ.get("SPARKNET_NODE_ID", "").strip() or "sparknet-node-unknown"


def _key() -> Any:
    explicit = os.environ.get("SPARKNET_NODE_KEY", "").strip()
    candidates = (
        [Path(explicit)]
        if explicit
        else [
            state_dir() / "keys" / "node.ed25519",
            state_dir() / "keys" / "ed25519-node.key.b64",
            state_dir() / "keys" / "identity.ed25519",
        ]
    )
    path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
    impl = authz()
    if impl is None:
        raise PushError("shared/sparknet-authz.py not found")
    if not path.is_file():
        raise PushError(f"node key not found: {path}")
    return impl.load_private_key(path)


def _headers(path: str, body: bytes, extra: dict[str, str] | None = None) -> dict[str, str]:
    impl = authz()
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    nonce = uuid.uuid4().hex
    signature = impl.sign_bytes(
        _key(), http().request_message("POST", path, body, stamp, nonce=nonce, node_id=node_id())
    )
    headers = {
        "Content-Type": "application/octet-stream",
        "X-Sparknet-Node-Id": node_id(),
        "X-Sparknet-Timestamp": stamp,
        "X-Sparknet-Nonce": nonce,
        "X-Sparknet-Signature": signature,
        "User-Agent": "sparknet-uplift/1",
    }
    headers.update(extra or {})
    return headers


def post(path: str, body: bytes, *, endpoint: str, extra: dict[str, str] | None = None) -> tuple[int, Any]:
    request = urllib.request.Request(
        endpoint.rstrip("/") + path, data=body, method="POST", headers=_headers(path, body, extra)
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except Exception:
            return exc.code, {"detail": raw.decode("utf-8", "replace")[:500]}
    except (urllib.error.URLError, OSError) as exc:
        return 0, {"ok": False, "reason": "transport-error", "detail": str(exc)}


def _manifest(extra: dict[str, Any]) -> str:
    return base64.b64encode(json.dumps(extra, sort_keys=True).encode()).decode()


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def qdrant_collections(*, qdrant: str = DEFAULT_QDRANT) -> list[str]:
    key = os.environ.get("SPARKNET_QDRANT_API_KEY", "").strip()
    headers = {"api-key": key} if key else {}
    request = urllib.request.Request(f"{qdrant.rstrip('/')}/collections", headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = payload.get("result", {}).get("collections") if isinstance(payload, dict) else None
    collections = []
    for row in rows or []:
        name = row.get("name") if isinstance(row, dict) else None
        if name and name != "sparknet-meta":
            collections.append(str(name))
    return sorted(collections)


def qdrant_snapshot(collection: str, *, qdrant: str = DEFAULT_QDRANT) -> tuple[bytes, dict[str, Any]]:
    key = os.environ.get("SPARKNET_QDRANT_API_KEY", "").strip()
    headers = {"Content-Type": "application/json"}
    if key:
        headers["api-key"] = key
    request = urllib.request.Request(
        f"{qdrant.rstrip('/')}/collections/{collection}/snapshots", data=b"{}", method="POST", headers=headers
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8"))
    name = payload.get("result", {}).get("name") if isinstance(payload, dict) else None
    if not name:
        raise PushError(f"Qdrant did not return a snapshot name: {payload}")
    download = urllib.request.Request(
        f"{qdrant.rstrip('/')}/collections/{collection}/snapshots/{name}", headers={"api-key": key} if key else {}
    )
    with opener.open(download, timeout=TIMEOUT) as response:
        body = response.read()
    return body, {"collection": collection, "snapshot_name": name}


def _outbox() -> Path:
    path = state_dir() / "uplift" / "outbox"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def spool(kind: str, body: bytes, manifest: dict[str, Any], endpoint: str) -> Path:
    row = {
        "kind": kind,
        "endpoint": endpoint,
        "manifest": manifest,
        "sha256": _sha256(body),
        "size": len(body),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = _outbox() / f"{kind}-{int(time.time() * 1000)}-{os.getpid()}.json"
    payload = path.with_suffix(".bin")
    payload.write_bytes(body)
    os.chmod(payload, 0o600)
    row["payload"] = str(payload)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(row, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    return path


def send(kind: str, body: bytes, manifest: dict[str, Any], *, endpoint: str = DEFAULT_ENDPOINT) -> bool:
    route = {
        "inventory": "/api/v1/inventory",
        "trace": "/api/v1/trace-batch",
        "snapshot": "/api/v1/vector-snapshot",
        "kv": "/api/v1/kv-artifact",
    }[kind]
    extra = {"X-Sparknet-Manifest": _manifest(manifest)} if kind in ("snapshot", "kv") else {}
    status, result = post(route, body, endpoint=endpoint, extra=extra)
    if 200 <= status < 300:
        return True
    spool(kind, body, manifest, endpoint)
    print(f"uplift: push failed HTTP {status}: {result}; spooled", file=sys.stderr)
    return False


def drain(*, endpoint: str = DEFAULT_ENDPOINT) -> int:
    pushed = 0
    for job in sorted(_outbox().glob("*.json")):
        try:
            row = json.loads(job.read_text(encoding="utf-8"))
            body = Path(row["payload"]).read_bytes()
            if send(str(row["kind"]), body, dict(row.get("manifest") or {}), endpoint=endpoint):
                Path(row["payload"]).unlink(missing_ok=True)
                job.unlink(missing_ok=True)
                pushed += 1
        except (OSError, ValueError, KeyError) as exc:
            print(f"uplift: unreadable outbox row {job.name}: {exc}", file=sys.stderr)
            job.unlink(missing_ok=True)
    return pushed


def _read_traces(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        payload = json.loads(text)
        rows = payload.get("traces") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise PushError("trace JSON must be a list or {traces: [...]}")
        return [row for row in rows if isinstance(row, dict)]
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Push consented uplift data to the Master (8091)")
    parser.add_argument("kind", choices=("inventory", "trace", "snapshot", "kv", "drain"))
    parser.add_argument("--file", type=Path)
    parser.add_argument("--collection", default="sparknet-peer")
    parser.add_argument("--all", action="store_true", help="snapshot every non-meta Qdrant collection")
    parser.add_argument("--model", default="")
    parser.add_argument("--architecture", default="")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--qdrant", default=DEFAULT_QDRANT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.kind == "drain":
            count = drain(endpoint=args.endpoint)
            print(f"uplift: drained {count} outbox rows")
            return 0
        if args.kind == "snapshot":
            if args.all:
                pushed = 0
                for collection in qdrant_collections(qdrant=args.qdrant):
                    body, info = qdrant_snapshot(collection, qdrant=args.qdrant)
                    manifest = {
                        **info,
                        "sha256": _sha256(body),
                        "size": len(body),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                    if args.dry_run:
                        print(
                            json.dumps({"kind": "snapshot", "manifest": manifest, "bytes": len(body)}, sort_keys=True)
                        )
                    elif send("snapshot", body, manifest, endpoint=args.endpoint):
                        pushed += 1
                print(f"uplift: pushed {pushed} collection snapshots")
                return 0
            if args.file:
                body = args.file.read_bytes()
                info = {"collection": args.collection, "snapshot_name": args.file.name}
            else:
                body, info = qdrant_snapshot(args.collection, qdrant=args.qdrant)
            manifest = {
                **info,
                "sha256": _sha256(body),
                "size": len(body),
                "compression": "gzip",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        elif args.kind == "trace":
            if not args.file:
                raise SystemExit("trace needs --file")
            rows = _read_traces(args.file)
            body = json.dumps(
                {"schema": "sparknet-uplift/1", "node_id": node_id(), "traces": rows}, sort_keys=True
            ).encode()
            manifest = {
                "rows": len(rows),
                "sha256": _sha256(body),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        elif args.kind == "inventory":
            if not args.file:
                raise SystemExit("inventory needs --file")
            payload = json.loads(args.file.read_text(encoding="utf-8"))
            if isinstance(payload, list):
                payload = {"schema": "sparknet-uplift/1", "node_id": node_id(), "inventory": payload}
            body = json.dumps(payload, sort_keys=True).encode()
            manifest = {"rows": len(payload.get("inventory") or []), "sha256": _sha256(body)}
        else:
            if not args.file:
                raise SystemExit("kv needs --file")
            body = args.file.read_bytes()
            manifest = {
                "artifact_id": _sha256(body)[:16],
                "model_id": args.model,
                "architecture": args.architecture,
                "sha256": _sha256(body),
                "size": len(body),
                "compression": "gzip",
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        if args.dry_run:
            print(json.dumps({"kind": args.kind, "manifest": manifest, "bytes": len(body)}, indent=2, sort_keys=True))
            return 0
        ok = send(args.kind, body, manifest, endpoint=args.endpoint)
        return 0 if ok else 1
    except (OSError, ValueError, PushError) as exc:
        print(f"uplift: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
