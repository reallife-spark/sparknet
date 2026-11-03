#!/usr/bin/env python3
"""The authority front door for the node's Go memory service.

The Go service (`sparknet-memory`, loopback 4110) stores typed records and
delegate runs. It deliberately verifies no signature and holds no key. This
gateway does the part that must remain in the fabric's one authorization
implementation:

* a signed session grant names the user, node and vault scope;
* an Open WebUI token names the user, whose vault is resolved locally;
* a 0600 local control token serves the console and the OpenCode plugin.

Every request is narrowed to one vault before it reaches the Go store. There is
no cross-vault query path and no second Ed25519 implementation.

Usage::

    shared/sparknet-memory-gateway.py --vault-root /srv/sparknet/peer-node
    shared/sparknet-memory-gateway.py --role master --vault-root /srv/sparknet/master-node
"""

from __future__ import annotations

import argparse
import hmac
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
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sparknet_loader import load_shared

HERE = Path(__file__).resolve().parent
SCHEMA = "sparknet-memory-gateway/1"
DEFAULT_MEMORY_URL = "http://127.0.0.1:4110"
DEFAULT_LISTEN = "127.0.0.1:4093"
MAX_BODY = 4 << 20
MUTATING = {
    "/v1/memory/remember",
    "/v1/memory/forget",
    "/v1/memory/import",
    "/v1/memory/prune",
    "/v1/delegates/plan",
}


class GatewayError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"[{stamp}] {message}", file=sys.stderr, flush=True)


def _default_state_dir() -> Path:
    explicit = os.environ.get("SPARKNET_STATE_DIR", "").strip()
    if explicit:
        return Path(explicit)
    return HERE.parent / "peer-node" / ".state"


def _read_token(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise GatewayError(503, "token-unavailable", f"cannot read {path}") from exc
    if len(value) < 16:
        raise GatewayError(503, "token-invalid", f"{path} is too short")
    return value


class Gateway:
    def __init__(
        self,
        *,
        memory_url: str = DEFAULT_MEMORY_URL,
        memory_token: str = "",
        local_token: str = "",
        webui_token: str = "",
        role: str = "peer",
        vault_roots: list[str] | None = None,
        user_vault_root: str = "",
        webui_url: str = "",
        state_dir: Path | None = None,
        registry_path: Path | None = None,
        identity_path: Path | None = None,
    ) -> None:
        self.memory_url = memory_url.rstrip("/")
        self.memory_token = memory_token
        self.local_token = local_token
        self.webui_token = webui_token
        self.role = role
        self.vault_roots = [str(Path(item).resolve()) for item in (vault_roots or [])]
        if not self.vault_roots:
            raise GatewayError(500, "configuration", "at least one vault root is required")
        self.user_vault_root = user_vault_root
        self.webui_url = webui_url.rstrip("/")
        self.state_dir = Path(state_dir or _default_state_dir())
        self.registry_path = Path(
            registry_path or (HERE.parent / "peer-node" / "manifests" / "node-authorizations.json")
        )
        self.identity_path = Path(identity_path or (HERE.parent / "peer-node" / "manifests" / "node-identity.json"))
        self.authz = load_shared("sparknet-authz.py", "sparknet_authz_gateway")
        self._webui_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    # -- authority ---------------------------------------------------------

    def _inside_roots(self, path: str) -> bool:
        try:
            candidate = Path(path).expanduser().resolve()
        except OSError:
            return False
        for root in self.vault_roots:
            try:
                candidate.relative_to(Path(root))
                return True
            except ValueError:
                continue
        return False

    def _role_vault(self) -> str:
        return self.vault_roots[0]

    def _user_vault(self, user_id: str) -> str:
        if not self.user_vault_root:
            raise GatewayError(403, "no-user-vault", "this node has no per-user vault root")
        candidate = Path(self.user_vault_root) / f"peer-{_slug(user_id)}"
        if not candidate.is_dir():
            raise GatewayError(403, "no-user-vault", f"no provisioned vault for user {user_id}")
        if not self._inside_roots(str(candidate)):
            raise GatewayError(403, "vault-forbidden", "user vault is outside the allowed roots")
        return str(candidate)

    def _registry(self) -> tuple[dict[str, Any], Any]:
        try:
            registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GatewayError(503, "registry-unavailable", str(exc)) from exc
        if not isinstance(registry, dict):
            raise GatewayError(503, "registry-invalid", "registry is not an object")
        encoded = registry.get("master_public_key_b64")
        if not isinstance(encoded, str) or not encoded:
            raise GatewayError(503, "registry-invalid", "registry has no master key")
        return registry, self.authz.public_key_from_b64(encoded)

    def _identity(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.identity_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _grant(self, token: str) -> dict[str, Any] | None:
        try:
            raw = self.authz.decode_b64_strict(token, what="grant", urlsafe=True)
            grant = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
        if not isinstance(grant, dict) or not grant.get("grant_id"):
            return None
        registry, master_key = self._registry()
        decision = self.authz.verify_grant(
            grant,
            master_public_key=master_key,
            registry=registry,
            node_identity=self._identity(),
            consumed_nonces=frozenset(),
        )
        if not decision.allowed:
            raise GatewayError(403, "grant-refused", decision.reason)
        return grant

    def _webui_user(self, token: str) -> dict[str, Any]:
        cached = self._webui_cache.get(token)
        now = time.monotonic()
        if cached and now - cached[0] < 60:
            return cached[1]
        if not self.webui_url:
            raise GatewayError(503, "webui-unavailable", "SPARKNET_WEBUI_URL is not configured")
        request = urllib.request.Request(
            f"{self.webui_url}/api/v1/auths/",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=10) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise GatewayError(401, "webui-unauthorized", f"Open WebUI refused the session ({exc.code})") from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise GatewayError(503, "webui-unavailable", str(exc)) from exc
        user = payload.get("user") if isinstance(payload.get("user"), dict) else payload
        if not isinstance(user, dict) or not user.get("id"):
            raise GatewayError(401, "webui-unauthorized", "Open WebUI returned no user")
        self._webui_cache[token] = (time.monotonic(), user)
        return user

    def _local(self, token: str) -> bool:
        return bool(self.local_token) and hmac.compare_digest(token.encode(), self.local_token.encode())

    def actor(self, headers: dict[str, str], body: dict[str, Any]) -> tuple[str, str, str, dict[str, Any]]:
        """Return ``(kind, actor_id, vault_path, constraints)``.

        ``constraints`` is merged into every request: the surface chooses a
        vault, never the caller. This is the scope-narrowing point.
        """
        webui_service = headers.get("x-sparknet-webui-token", "")
        if webui_service:
            if not self.webui_token or not hmac.compare_digest(webui_service.encode(), self.webui_token.encode()):
                raise GatewayError(401, "webui-service-unauthorized", "bad WebUI service token")
            user_id = headers.get("x-sparknet-user", "").strip()
            if not user_id:
                raise GatewayError(401, "webui-service-unauthorized", "the WebUI service token needs a user")
            vault_path = self._user_vault(user_id)
            return "webui", user_id, vault_path, {"vault_path": vault_path, "scope": {"user_id": user_id}}

        local = headers.get("x-sparknet-local-token", "")
        if local:
            if not self._local(local):
                raise GatewayError(401, "local-unauthorized", "bad local control token")
            vault_path = headers.get("x-sparknet-vault-path", "").strip()
            if not vault_path:
                vault_path = self._role_vault()
            if not self._inside_roots(vault_path):
                raise GatewayError(403, "vault-forbidden", "vault is outside the allowed roots")
            user = headers.get("x-sparknet-user", "").strip()
            constraints = {"vault_path": vault_path}
            if user:
                constraints["scope"] = {"user_id": user}
            return "local", user or "local", vault_path, constraints

        authorization = headers.get("authorization", "")
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if not token:
            raise GatewayError(401, "unauthorized", "a signed grant, WebUI token or local token is required")

        grant = self._grant(token)
        if grant is not None:
            user_id = str(grant.get("user_identity") or "")
            if not user_id:
                raise GatewayError(403, "grant-refused", "grant names no user")
            # A signed session grant is bound to the role vault. A caller cannot
            # use it to read a sibling user's vault by naming another path.
            vault_path = self._role_vault()
            requested = str(body.get("vault_path") or "").strip()
            if requested and Path(requested).expanduser().resolve() != Path(vault_path).resolve():
                raise GatewayError(403, "vault-forbidden", "a session grant is bound to the role vault")
            constraints = {"vault_path": vault_path, "scope": {"user_id": user_id}}
            return "grant", user_id, vault_path, constraints

        user = self._webui_user(token)
        user_id = str(user["id"])
        vault_path = self._user_vault(user_id)
        constraints = {"vault_path": vault_path, "scope": {"user_id": user_id}}
        return "webui", user_id, vault_path, constraints

    # -- forwarding --------------------------------------------------------

    def forward(self, method: str, path: str, body: dict[str, Any] | None, query: str = "") -> tuple[int, Any]:
        url = self.memory_url + path + (("?" + query) if query else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("X-Sparknet-Memory-Token", self.memory_token)
        if data is not None:
            request.add_header("Content-Type", "application/json")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=60) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw.decode("utf-8"))
            except Exception:
                payload = {"ok": False, "code": "memory-error", "error": raw.decode("utf-8", "replace")}
            return exc.code, payload
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise GatewayError(503, "memory-unavailable", str(exc)) from exc

    def audit(self, actor_kind: str, actor_id: str, action: str, vault_path: str, detail: dict[str, Any]) -> None:
        row = {
            "schema": SCHEMA,
            "at": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "actor_kind": actor_kind,
            "actor_id": actor_id,
            "action": action,
            "vault_path": vault_path,
            "detail": detail,
        }
        try:
            directory = self.state_dir / "memory"
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = directory / "audit.jsonl"
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(descriptor, (json.dumps(row, sort_keys=True) + "\n").encode("utf-8"))
            finally:
                os.close(descriptor)
        except OSError as exc:
            log(f"audit write failed: {exc}")

    def handle(self, method: str, raw_path: str, headers: dict[str, str], body: dict[str, Any]) -> tuple[int, Any]:
        parsed = urllib.parse.urlsplit(raw_path)
        path = parsed.path.rstrip("/")
        query = parsed.query
        if path in ("/healthz", "/readyz"):
            return 200, {"ok": True, "service": "sparknet-memory-gateway", "schema": SCHEMA}
        if not path.startswith("/v1/"):
            raise GatewayError(404, "not-found", "unknown gateway route")
        kind, actor_id, vault_path, constraints = self.actor(headers, body)
        merged = dict(body)
        merged.update(constraints)
        if isinstance(merged.get("scope"), dict) and isinstance(constraints.get("scope"), dict):
            merged["scope"] = {**constraints["scope"], **merged["scope"]}
            merged["scope"]["user_id"] = constraints["scope"]["user_id"]
        if path.startswith("/v1/delegates/"):
            if isinstance(merged.get("plan"), dict):
                merged["plan"].setdefault("user_id", actor_id)
            if method == "POST" and path == "/v1/delegates/plan":
                self.audit(
                    kind, actor_id, "delegate.plan", vault_path, {"plan_id": merged.get("plan", {}).get("plan_id")}
                )
            if method == "GET":
                query = urllib.parse.urlencode(_flat(merged))
                status, payload = self.forward(method, path, None, query)
            else:
                status, payload = self.forward(method, path, merged, query)
            return status, payload
        if path.startswith("/v1/memory/"):
            if method == "POST" and (path in MUTATING or path == "/v1/memory/inspect"):
                self.audit(kind, actor_id, path.rsplit("/", 1)[-1], vault_path, {"types": merged.get("memory_types")})
            if method == "GET":
                query = urllib.parse.urlencode(_flat(merged))
                status, payload = self.forward(method, path, None, query)
            else:
                status, payload = self.forward(method, path, merged, query)
            return status, payload
        if path == "/v1/admin/inspect":
            if kind not in ("local",):
                raise GatewayError(403, "admin-refused", "inspection requires the local control token")
            self.audit(kind, actor_id, "memory.inspect", vault_path, {"types": merged.get("memory_types")})
            status, payload = self.forward("POST", "/v1/memory/inspect", merged)
            return status, payload
        raise GatewayError(404, "not-found", "unknown gateway route")


def _flat(value: dict[str, Any], prefix: str = "") -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for key, item in value.items():
        name = f"{prefix}{key}"
        if isinstance(item, dict):
            out.extend(_flat(item, name + "."))
        elif isinstance(item, list):
            for entry in item:
                out.append((name, str(entry)))
        elif item is not None:
            out.append((name, str(item)))
    return out


def _slug(value: str) -> str:
    safe = "".join(char for char in value if char.isalnum() or char in "-_")
    return safe[:64] or "user"


class Handler(BaseHTTPRequestHandler):
    server_version = "sparknet-memory-gateway/1"
    gateway: Gateway

    def log_message(self, fmt: str, *args: Any) -> None:
        log(fmt % args)

    def _headers(self) -> dict[str, str]:
        return {key.lower(): value for key, value in self.headers.items()}

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise GatewayError(413, "too-large", "request body exceeds the limit")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GatewayError(400, "malformed", str(exc)) from exc
        if not isinstance(value, dict):
            raise GatewayError(400, "malformed", "body must be a JSON object")
        return value

    def _dispatch(self, method: str) -> None:
        try:
            body = self._body() if method in ("POST", "PUT", "PATCH") else {}
            status, payload = self.gateway.handle(method, self.path, self._headers(), body)
        except GatewayError as exc:
            status, payload = exc.status, {"ok": False, "code": exc.code, "error": exc.message}
        except Exception as exc:  # fail closed, never leak a traceback to a client
            log(f"unhandled: {exc}")
            status, payload = 500, {"ok": False, "code": "internal", "error": "memory gateway failed"}
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")


def build_gateway(args: argparse.Namespace) -> Gateway:
    state = Path(args.state_dir or _default_state_dir())
    memory_token = os.environ.get("GOSPARK_MEMORY_GATEWAY_TOKEN", "").strip()
    if not memory_token:
        memory_token = _read_token(Path(args.memory_token_file or (state / "memory.gateway.token")))
    local_token = os.environ.get("SPARKNET_MEMORY_LOCAL_TOKEN", "").strip()
    if not local_token:
        local_token = _read_token(Path(args.local_token_file or (state / "memory.local.token")))
    webui_token = os.environ.get("SPARKNET_MEMORY_WEBUI_TOKEN", "").strip()
    return Gateway(
        memory_url=args.memory_url,
        memory_token=memory_token,
        local_token=local_token,
        webui_token=webui_token,
        role=args.role,
        vault_roots=args.vault_root,
        user_vault_root=args.user_vault_root,
        webui_url=args.webui_url,
        state_dir=state,
        registry_path=Path(args.registry) if args.registry else None,
        identity_path=Path(args.identity) if args.identity else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="authority front door for the Go memory service")
    parser.add_argument("--bind", default=os.environ.get("SPARKNET_MEMORY_GATEWAY_BIND", DEFAULT_LISTEN))
    parser.add_argument("--memory-url", default=os.environ.get("SPARKNET_MEMORY_URL", DEFAULT_MEMORY_URL))
    parser.add_argument("--state-dir", default=os.environ.get("SPARKNET_STATE_DIR", ""))
    parser.add_argument("--memory-token-file", default="")
    parser.add_argument("--local-token-file", default="")
    parser.add_argument("--role", choices=("peer", "master"), default=os.environ.get("SPARKNET_ROLE", "peer"))
    parser.add_argument("--vault-root", action="append", required=True)
    parser.add_argument(
        "--user-vault-root", default=os.environ.get("SPARKNET_USER_VAULT_ROOT", "/srv/sparknet/knowledge")
    )
    parser.add_argument("--webui-url", default=os.environ.get("SPARKNET_WEBUI_URL", "http://127.0.0.1:8181"))
    parser.add_argument("--registry", default="")
    parser.add_argument("--identity", default="")
    args = parser.parse_args(argv)
    gateway = build_gateway(args)
    host, _, port = args.bind.rpartition(":")
    if not host:
        host, port = "127.0.0.1", args.bind
    Handler.gateway = gateway
    server = ThreadingHTTPServer((host, int(port)), Handler)
    log(f"memory gateway on {args.bind} -> {args.memory_url} role={args.role} vaults={args.vault_root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
