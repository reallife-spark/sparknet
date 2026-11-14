#!/usr/bin/env python3
"""Signed local-first model router.

Local applications call the loopback routes without a node signature. The
overlay routes are signed by the shared transport and admit only explicit
support/fabric/contract inference; user-class content never crosses the bridge.
The router is transport and policy only: it holds no key, reads no vault and
does not sign anything.
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

HTTP = load_by_path("sparknet_model_router_http", ROOT / "shared" / "sparknet-http.py")
REMOTE_DATA_CLASSES = frozenset({"support", "fabric", "contract"})
LOCAL_DATA_CLASS = "user"
DEFAULT_PORTS = {
    "master": {
        "qwen3-4b": ("chat", "http://127.0.0.1:8000/v1/chat/completions"),
        "qwen3-embedding-0.6b": ("embed", "http://127.0.0.1:8001/v1/embeddings"),
    },
    "peer": {
        "qwen3-30b": ("chat", "http://127.0.0.1:8000/v1/chat/completions"),
        "qwen3-coder-30b-65k": ("chat", "http://127.0.0.1:11434/v1/chat/completions"),
        "qwen3-vl-4b-65k": ("chat", "http://127.0.0.1:11434/v1/chat/completions"),
        "qwen3-embedding-0.6b": ("embed", "http://127.0.0.1:8001/v1/embeddings"),
    },
}


def _json_request(url: str, payload: dict[str, Any], timeout: float = 300.0) -> tuple[int, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST"
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw[:500]}


def _load_keyring(registry_path: Path, authz: Any, master_pub: str) -> dict[str, Any]:
    keys: dict[str, Any] = {}
    if master_pub:
        keys["master"] = authz.public_key_from_b64(master_pub)
    document = json.loads(registry_path.read_text())
    for entry in document.get("authorizations") or []:
        node_id = (entry.get("identity") or {}).get("node_id")
        pub = entry.get("node_pubkey_b64")
        if node_id and pub:
            keys[str(node_id)] = authz.public_key_from_b64(str(pub))
    return keys


def _capabilities(registry_path: Path, key_id: str) -> set[str]:
    document = json.loads(registry_path.read_text())
    for entry in document.get("authorizations") or []:
        if (entry.get("identity") or {}).get("node_id") == key_id:
            return {str(value) for value in entry.get("capabilities") or []}
    return set()


def _alias(routes: dict[str, dict[str, tuple[str, str]]], model: str, kind: str) -> str | None:
    value = routes.get(model)
    if not value or value[0] != kind:
        return None
    return value[1]


def _remote_allowed(*, key_id: str, data_class: str, registry_path: Path | None) -> bool:
    if data_class not in REMOTE_DATA_CLASSES:
        return False
    if key_id == "master":
        return data_class in {"support", "fabric"}
    if registry_path is None:
        return False
    return "model-route" in _capabilities(registry_path, key_id)


class Router:
    def __init__(
        self,
        *,
        role: str,
        node_id: str,
        overlay: str,
        registry_path: Path,
        master_pub: str,
        routes: dict[str, dict[str, tuple[str, str]]] | None = None,
    ) -> None:
        self.role = role
        self.node_id = node_id
        self.overlay = overlay
        self.registry_path = registry_path
        self.routes = routes or DEFAULT_PORTS[role]
        self.authz = HTTP._load_authz(ROOT / "shared")
        self.public_keys = _load_keyring(registry_path, self.authz, master_pub)

    def local_models(self) -> tuple[int, Any]:
        return 200, {
            "object": "list",
            "data": [{"id": model, "object": "model", "owned_by": self.node_id} for model in sorted(self.routes)],
        }

    def _local_forward(self, model: str, kind: str, payload: dict[str, Any]) -> tuple[int, Any]:
        target = _alias(self.routes, model, kind)
        if target is None:
            return 404, {"ok": False, "reason": "unknown-local-model", "model": model}
        return _json_request(target, payload)

    def _remote_forward(self, request: Any, kind: str) -> tuple[int, Any]:
        identity = request.identity or {}
        key_id = str(identity.get("verified_key_id") or "")
        if not key_id:
            return 403, {"ok": False, "reason": "unverified-caller"}
        body = request.json if isinstance(request.json, dict) else {}
        data_class = str(body.get("data_class") or "")
        if not _remote_allowed(key_id=key_id, data_class=data_class, registry_path=self.registry_path):
            return 403, {"ok": False, "reason": "remote-policy-refused", "data_class": data_class}
        model = str(body.get("model") or "")
        target = _alias(self.routes, model, kind)
        if target is None:
            return 404, {"ok": False, "reason": "unknown-local-model", "model": model}
        payload = body.get("payload")
        if not isinstance(payload, dict):
            return 400, {"ok": False, "reason": "payload-required"}
        status, result = _json_request(target, payload)
        if status != 200:
            return status, {
                "ok": False,
                "reason": "upstream-refused",
                "source_node": self.node_id,
                "model": model,
                "result": result,
            }
        return 200, {
            "ok": True,
            "schema": "sparknet-model-route-response/1",
            "source_node": self.node_id,
            "model": model,
            "data_class": data_class,
            "result": result,
        }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="signed local-first model router")
    parser.add_argument("--role", choices=("master", "peer"), required=True)
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--overlay", required=True)
    parser.add_argument("--port", type=int, default=8101)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--master-pub", required=True)
    parser.add_argument("--bind-local", default="127.0.0.1")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    router = Router(
        role=args.role,
        node_id=args.node_id,
        overlay=args.overlay,
        registry_path=args.registry,
        master_pub=args.master_pub,
    )
    routes = [
        HTTP.Route("/v1/models", lambda request: router.local_models(), "GET", auth="plain", source="loopback"),
        HTTP.Route(
            "/v1/chat/completions",
            lambda request: router._local_forward(
                str((request.json or {}).get("model") or ""), "chat", request.json or {}
            ),
            "POST",
            auth="plain",
            source="loopback",
        ),
        HTTP.Route(
            "/v1/embeddings",
            lambda request: router._local_forward(
                str((request.json or {}).get("model") or ""), "embed", request.json or {}
            ),
            "POST",
            auth="plain",
            source="loopback",
        ),
        HTTP.Route(
            "/v1/route/chat",
            lambda request: router._remote_forward(request, "chat"),
            "POST",
            auth="signed",
            source="overlay",
            max_body=4 << 20,
        ),
        HTTP.Route(
            "/v1/route/embeddings",
            lambda request: router._remote_forward(request, "embed"),
            "POST",
            auth="signed",
            source="overlay",
            max_body=4 << 20,
        ),
    ]
    listener = HTTP.listen(
        routes,
        name="sparknet-model-router",
        bind=[args.bind_local, args.overlay],
        port=args.port,
        public_keys=router.public_keys,
        loopback_only_routes=("/v1/models", "/v1/chat/completions", "/v1/embeddings"),
    )
    listener.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
