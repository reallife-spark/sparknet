#!/usr/bin/env python3
"""Signed federated memory read-through.

Local applications continue to use the memory gateway (4093). This router
exposes only a scoped, read-only view to the other node: fabric/admin records
with owner and provenance, never user vault content, writes, mirrors or
cross-vault queries.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_by_path  # noqa: E402

HTTP = load_by_path("sparknet_memory_router_http", ROOT / "shared" / "sparknet-http.py")
REMOTE_SCOPES = frozenset({"fabric", "admin"})


def _json_request(url: str, payload: dict[str, Any], headers: dict[str, str]) -> tuple[int, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw[:500]}


def _keyring(registry: Path, authz: Any, master_pub: str) -> dict[str, Any]:
    keys: dict[str, Any] = {}
    if master_pub:
        keys["master"] = authz.public_key_from_b64(master_pub)
    data = json.loads(registry.read_text())
    for entry in data.get("authorizations") or []:
        node_id = (entry.get("identity") or {}).get("node_id")
        pub = entry.get("node_pubkey_b64")
        if node_id and pub:
            keys[str(node_id)] = authz.public_key_from_b64(str(pub))
    return keys


def _caps(registry: Path, key_id: str) -> set[str]:
    data = json.loads(registry.read_text())
    for entry in data.get("authorizations") or []:
        if (entry.get("identity") or {}).get("node_id") == key_id:
            return {str(c) for c in entry.get("capabilities") or []}
    return set()


def _remote_allowed(*, key_id: str, scope: str, registry: Path) -> bool:
    if scope not in REMOTE_SCOPES:
        return False
    if key_id == "master":
        return False  # Master support for user memory uses memory-supervise.
    return "memory-federate" in _caps(registry, key_id)


class MemoryRouter:
    def __init__(self, *, node_id: str, vault_path: str, local_token: str, registry: Path, master_pub: str) -> None:
        self.node_id = node_id
        self.vault_path = vault_path
        self.local_token = local_token
        self.registry = registry
        self.authz = HTTP._load_authz(ROOT / "shared")
        self.public_keys = _keyring(registry, self.authz, master_pub)

    def _read(self, scope: str, query: str, limit: int) -> tuple[int, Any]:
        if scope not in REMOTE_SCOPES:
            return 403, {"ok": False, "reason": "scope-refused", "scope": scope}
        headers = {"X-Sparknet-Local-Token": self.local_token, "X-Sparknet-Vault-Path": self.vault_path}
        status, result = _json_request(
            "http://127.0.0.1:4093/v1/memory/query",
            {"query": query, "top_k": limit, "memory_types": ["semantic", "procedural"]},
            headers,
        )
        if status != 200:
            return 502, {"ok": False, "reason": "gateway-refused", "result": result}
        return 200, {
            "ok": True,
            "schema": "sparknet-memory-route/1",
            "source_node": self.node_id,
            "scope": scope,
            "vault_id": self.vault_path,
            "result": result,
        }

    def local(self, request: Any) -> tuple[int, Any]:
        body = request.json if isinstance(request.json, dict) else {}
        return self._read(str(body.get("scope") or ""), str(body.get("query") or ""), int(body.get("limit") or 8))

    def remote(self, request: Any) -> tuple[int, Any]:
        body = request.json if isinstance(request.json, dict) else {}
        key_id = str((request.identity or {}).get("verified_key_id") or "")
        scope = str(body.get("scope") or "")
        if not key_id or not _remote_allowed(key_id=key_id, scope=scope, registry=self.registry):
            return 403, {"ok": False, "reason": "remote-memory-refused", "scope": scope}
        return self._read(scope, str(body.get("query") or ""), int(body.get("limit") or 8))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="signed federated memory read-through")
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--overlay", required=True)
    parser.add_argument("--vault-path", required=True)
    parser.add_argument("--local-token-file", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--master-pub", required=True)
    parser.add_argument("--port", type=int, default=4094)
    args = parser.parse_args(argv)
    token = args.local_token_file.read_text(encoding="utf-8").strip()
    router = MemoryRouter(
        node_id=args.node_id,
        vault_path=args.vault_path,
        local_token=token,
        registry=args.registry,
        master_pub=args.master_pub,
    )
    listener = HTTP.listen(
        [
            HTTP.Route("/v1/read", router.local, "POST", auth="plain", source="loopback"),
            HTTP.Route("/v1/route/read", router.remote, "POST", auth="signed", source="overlay"),
        ],
        name="sparknet-memory-router",
        bind=["127.0.0.1", args.overlay],
        port=args.port,
        public_keys=router.public_keys,
        loopback_only_routes=("/v1/read",),
    )
    listener.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
