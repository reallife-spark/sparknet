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
import contextlib
import hmac
import json
import os
import re
import sys
import threading
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

ABAC = load_shared("sparknet-abac.py", "sparknet_abac_memory_gateway")
GRAPH = load_shared("sparknet-graph.py", "sparknet_graph_memory_gateway")
HYBRID = load_shared("sparknet-hybrid.py", "sparknet_hybrid_memory_gateway")
COLLAB = load_shared("sparknet-collab.py", "sparknet_collab_memory_gateway")
EXEC = load_shared("sparknet-exec-rpc.py", "sparknet_exec_memory_gateway")
YAML = load_shared("sparknet-yaml.py", "sparknet_yaml_memory_gateway")

HERE = Path(__file__).resolve().parent
SCHEMA = "sparknet-memory-gateway/1"
DEFAULT_MEMORY_URL = "http://127.0.0.1:4110"
DEFAULT_LISTEN = "127.0.0.1:4093"
MAX_BODY = 4 << 20
MAX_VAULT_FILE = 1 << 20
VAULT_SUFFIXES = {".md", ".markdown", ".txt", ".yaml", ".yml"}
VAULT_SKIP_PARTS = {
    ".git",
    ".state",
    ".cache",
    "__pycache__",
    ".opencode",
    ".pytest_cache",
    ".ruff_cache",
    "keys",
    "blockchain",
    "manifests",
}
VAULT_SKIP_NAMES = {"secrets-index.json", "user-env-manifest.json", "MEMORY.md", ".env"}
VAULT_CAPTURE_PREFIXES = ("01_Inbox", "_raw", "04_Evergreen", "05_Knowledge", "06_Projects")
RFI_ALLOWED_SCOPE = {
    "contracts",
    "docs",
    "04_Evergreen",
    "05_Knowledge",
    "06_Projects",
    "AGENTS.md",
    "CONTEXT.md",
    "INTENT.md",
    "MISSION.md",
    "README.md",
}
MUTATING = {
    "/v1/memory/remember",
    "/v1/memory/forget",
    "/v1/memory/import",
    "/v1/memory/prune",
    "/v1/delegates/plan",
}
ROOM_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
GRANT_MUTATING = frozenset(
    {
        "/v1/collab/room",
        "/v1/collab/message",
        "/v1/vault/capture",
        "/v1/rfi",
        *MUTATING,
    }
)


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
        self._nonce_lock = threading.Lock()

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

    def _identity(self) -> dict[str, Any]:
        try:
            value = json.loads(self.identity_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GatewayError(503, "identity-unavailable", str(exc)) from exc
        if not isinstance(value, dict):
            raise GatewayError(503, "identity-invalid", "identity is not an object")
        return value

    @property
    def _nonce_path(self) -> Path:
        return self.state_dir / "consumed-grant-nonces.json"

    def _read_nonces(self) -> set[str]:
        path = self._nonce_path
        if not path.is_file():
            return set()
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GatewayError(503, "nonce-store-unavailable", str(exc)) from exc
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise GatewayError(503, "nonce-store-invalid", "consumed nonce store is malformed")
        return set(value)

    def _write_nonces(self, nonces: set[str]) -> None:
        path = self._nonce_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temp = path.with_name(path.name + ".tmp")
            temp.write_text(json.dumps(sorted(nonces)) + "\n", encoding="utf-8")
            os.chmod(temp, 0o600)
            os.replace(temp, path)
        except OSError as exc:
            raise GatewayError(503, "nonce-store-unavailable", str(exc)) from exc

    def _grant(self, token: str) -> dict[str, Any] | None:
        try:
            raw = self.authz.decode_b64_strict(token, what="grant", urlsafe=True)
            grant = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
        if not isinstance(grant, dict) or not grant.get("grant_id"):
            return None
        nonce = grant.get("nonce")
        if not isinstance(nonce, str) or not nonce:
            raise GatewayError(403, "grant-refused", "grant names no nonce")
        registry, master_key = self._registry()
        with self._nonce_lock:
            consumed = self._read_nonces()
            decision = self.authz.verify_grant(
                grant,
                master_public_key=master_key,
                registry=registry,
                node_identity=self._identity(),
                consumed_nonces=frozenset(consumed),
            )
            if not decision.allowed:
                raise GatewayError(403, "grant-refused", decision.reason)
        return grant

    def _consume_grant_nonce(self, nonce: str | None) -> None:
        if not nonce:
            return
        with self._nonce_lock:
            consumed = self._read_nonces()
            if nonce in consumed:
                raise GatewayError(403, "grant-refused", "grant nonce was already used")
            self._write_nonces(consumed | {nonce})

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
            try:
                subject = ABAC.subject_from_grant(grant, Path(vault_path).name, verified=True)
            except ABAC.AbacError as exc:
                raise GatewayError(403, exc.code, exc.message) from exc
            constraints = {
                "vault_path": vault_path,
                "scope": {"user_id": user_id},
                "scope_paths": list(subject["scope"]),
                "grant_nonce": str(grant.get("nonce") or ""),
            }
            return "grant", user_id, vault_path, constraints

        user = self._webui_user(token)
        user_id = str(user["id"])
        vault_path = self._user_vault(user_id)
        constraints = {"vault_path": vault_path, "scope": {"user_id": user_id}}
        return "webui", user_id, vault_path, constraints

    # -- user vault tools --------------------------------------------------

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
        return slug[:80] or "note"

    @staticmethod
    def _authority(rel: str) -> bool:
        try:
            return ABAC.resource_class_for(rel) == "authority"
        except ABAC.AbacError:
            return True

    @staticmethod
    def _scope_row(rel: str, scope_paths: list[str] | None) -> bool:
        if scope_paths is None:
            return True
        rel = rel.strip("/")
        return any(
            rel == str(prefix).strip("/") or rel.startswith(str(prefix).strip("/") + "/") for prefix in scope_paths
        )

    def _vault_candidate(self, vault_path: str, rel: str) -> Path:
        root = Path(vault_path).expanduser().resolve()
        cleaned = (rel or "").replace("\\", "/").strip().lstrip("/")
        if not cleaned:
            return root
        candidate = (root / cleaned).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            raise GatewayError(403, "vault-forbidden", "path escapes the user vault") from None
        rel_parts = candidate.relative_to(root).parts
        if any(part in VAULT_SKIP_PARTS for part in rel_parts):
            raise GatewayError(403, "vault-forbidden", "path names runtime state")
        if candidate.name in VAULT_SKIP_NAMES:
            raise GatewayError(403, "vault-forbidden", "path names a secret index")
        if self._authority(candidate.relative_to(root).as_posix()):
            raise GatewayError(403, "authority-surface", "path names an authority surface")
        return candidate

    def _vault_files(self, vault_path: str) -> list[Path]:
        root = Path(vault_path)
        files = []
        for path in root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(root)
            if any(part in VAULT_SKIP_PARTS for part in rel.parts):
                continue
            if path.name in VAULT_SKIP_NAMES:
                continue
            if self._authority(rel.as_posix()):
                continue
            if path.suffix.lower() not in VAULT_SUFFIXES:
                continue
            files.append(path)
        return sorted(files)

    @staticmethod
    def _page_classification(rel: str) -> str:
        """Legacy fallback only; the O1 field is authoritative when present."""
        for prefix, classification in ABAC.LEGACY_PATH_CLASSIFICATION.items():
            if rel.startswith(prefix):
                return classification
        return ABAC.DEFAULT_LEGACY_CLASSIFICATION

    def _page_attributes(self, rel: str, text: str) -> tuple[str, str | None]:
        """Read classification and department from the note, fail-closed.

        A page with no frontmatter is legacy and uses the path fallback. A page
        that has frontmatter but an unknown classification is refused rather
        than silently lowered to a path-derived label.
        """
        fallback = self._page_classification(rel)
        if not text.startswith("---\n"):
            return fallback, None
        end = text.find("\n---\n", 4)
        if end == -1:
            raise GatewayError(400, "malformed-frontmatter", f"{rel} has an unclosed frontmatter fence")
        try:
            meta = YAML.parse_yaml_subset(text[4:end])
        except YAML.ProvenanceError as exc:
            raise GatewayError(400, "malformed-frontmatter", f"{rel}: {exc}") from exc
        if not isinstance(meta, dict):
            raise GatewayError(400, "malformed-frontmatter", f"{rel} frontmatter is not a mapping")
        classification = meta.get("classification", fallback)
        if not isinstance(classification, str) or classification not in ABAC.CLASSIFICATIONS:
            raise GatewayError(400, "unknown-classification", f"{rel} has an unknown classification")
        department = meta.get("department")
        if department is not None and not isinstance(department, str):
            raise GatewayError(400, "malformed-frontmatter", f"{rel} department must be a string")
        return classification, (department.strip() or None if isinstance(department, str) else None)

    @staticmethod
    def _page_title(text: str, rel: str) -> str:
        for line in text.splitlines():
            if line.startswith("# "):
                return line[2:].strip() or Path(rel).stem
        return Path(rel).stem

    def vault_graph(self, vault_path: str, scope_paths: list[str] | None = None) -> dict[str, Any]:
        root = Path(vault_path).resolve()
        if not root.is_dir():
            raise GatewayError(404, "not-found", "vault path is not a directory")
        pages = []
        for path in self._vault_files(vault_path):
            rel = path.relative_to(root).as_posix()
            if not self._scope_row(rel, scope_paths):
                continue
            if len(pages) >= 500:
                break
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            classification, department = self._page_attributes(rel, text)
            pages.append(
                {
                    "vault_id": root.name,
                    "path": rel,
                    "title": self._page_title(text, rel),
                    "classification": classification,
                    "department": department,
                    "text": text,
                }
            )
        try:
            graph = GRAPH.build_graph(pages)
        except GRAPH.GraphError as exc:
            raise GatewayError(400, exc.code, exc.message) from exc
        return {"ok": True, "graph": graph}

    @staticmethod
    def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp = path.with_name(path.name + ".tmp")
        temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(temp, 0o600)
        os.replace(temp, path)

    def _collab_root(self, vault_path: str) -> Path:
        root = Path(vault_path).resolve()
        path = root / "01_Inbox" / "collab"
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def _room_path(self, vault_path: str, room_id: str) -> Path:
        if not isinstance(room_id, str) or not ROOM_ID_RE.fullmatch(room_id):
            raise GatewayError(400, "bad-room-id", "room_id must be a single safe path component")
        root = self._collab_root(vault_path).resolve()
        candidate = (root / room_id).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise GatewayError(403, "vault-forbidden", "room_id escapes the collaboration root") from exc
        return candidate

    def collab_create_room(self, vault_path: str, actor_id: str, body: dict[str, Any]) -> dict[str, Any]:
        participants = body.get("participants")
        if not isinstance(participants, list) or not participants:
            participants = [{"node_id": actor_id, "user_id": actor_id, "department": None}]
        cleaned = []
        for item in participants:
            if isinstance(item, dict):
                cleaned.append(
                    {
                        "node_id": str(item.get("node_id") or actor_id),
                        "user_id": str(item.get("user_id") or actor_id),
                        "department": None,
                        "role": str(item.get("role") or "participant"),
                    }
                )
        if not any(item["node_id"] == actor_id and item["user_id"] == actor_id for item in cleaned):
            cleaned.append({"node_id": actor_id, "user_id": actor_id, "department": None, "role": "owner"})
        room_id = str(body.get("room_id") or "").strip()
        room = COLLAB.make_room(
            owner_node_id=actor_id,
            participants=cleaned,
            classification=str(body.get("classification") or "internal"),
            department=None,
            room_id=room_id or None,
            verified=True,
        )
        path = self._room_path(vault_path, str(room["room_id"])) / "room.json"
        self._write_json_atomic(path, room)
        return {"ok": True, "room": room}

    def collab_list_rooms(self, vault_path: str) -> dict[str, Any]:
        root = self._collab_root(vault_path)
        rooms = []
        for room_file in sorted(root.glob("*/room.json")):
            try:
                room = COLLAB.validate_room(json.loads(room_file.read_text(encoding="utf-8")))
            except (OSError, ValueError, COLLAB.CollabError):
                continue
            rooms.append(room)
        return {"ok": True, "rooms": rooms}

    def collab_post_message(self, vault_path: str, actor_id: str, body: dict[str, Any]) -> dict[str, Any]:
        room_id = str(body.get("room_id") or "").strip()
        if not room_id:
            raise GatewayError(400, "malformed", "room_id is required")
        room_file = self._room_path(vault_path, room_id) / "room.json"
        try:
            room = COLLAB.validate_room(json.loads(room_file.read_text(encoding="utf-8")))
        except (OSError, ValueError, COLLAB.CollabError) as exc:
            raise GatewayError(404, "not-found", "collaboration room not found") from exc
        message = COLLAB.make_message(
            room,
            sender_node_id=actor_id,
            sender_user_id=actor_id,
            text=str(body.get("text") or ""),
            provenance={"source": "local"},
            classification=str(body.get("classification") or room["classification"]),
        )
        path = self._room_path(vault_path, room_id) / "messages" / f"{message['message_id']}.json"
        self._write_json_atomic(path, message)
        return {"ok": True, "message": message}

    def collab_list_messages(self, vault_path: str, room_id: str) -> dict[str, Any]:
        if not room_id:
            raise GatewayError(400, "malformed", "room_id is required")
        room_file = self._collab_root(vault_path) / room_id / "room.json"
        try:
            room = COLLAB.validate_room(json.loads(room_file.read_text(encoding="utf-8")))
        except (OSError, ValueError, COLLAB.CollabError) as exc:
            raise GatewayError(404, "not-found", "collaboration room not found") from exc
        messages = []
        for message_file in sorted((room_file.parent / "messages").glob("*.json")):
            try:
                messages.append(COLLAB.validate_message(json.loads(message_file.read_text(encoding="utf-8")), room))
            except (OSError, ValueError, COLLAB.CollabError):
                continue
        messages.sort(key=lambda item: (item["created_at"], item["message_id"]))
        return {"ok": True, "room": room, "messages": messages}

    def vault_hybrid(
        self, vault_path: str, query: str, top_k: int = 8, scope_paths: list[str] | None = None
    ) -> dict[str, Any]:
        search = self.vault_search(vault_path, query, top_k, scope_paths)
        root = Path(vault_path).resolve()
        graph = self.vault_graph(vault_path, scope_paths)["graph"]
        by_path = {node["path"]: node for node in graph["nodes"]}

        def attributes(rel: str) -> tuple[str, str | None]:
            node = by_path.get(rel)
            if node is not None:
                return str(node["classification"]), node.get("department")
            try:
                text = (root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return self._page_classification(rel), None
            return self._page_attributes(rel, text)

        semantic = []
        semantic_departments = set()
        for index, hit in enumerate(search["hits"]):
            rel = hit["path"]
            classification, department = attributes(rel)
            if department:
                semantic_departments.add(department)
            semantic.append(
                HYBRID.semantic_result(
                    result_id=f"sem-{index + 1}",
                    source="vault_search",
                    path=rel,
                    score=float(hit["score"]),
                    text=hit["snippet"],
                    classification=classification,
                    provenance={"source": rel},
                )
            )
        agentic = []
        for index, hit in enumerate(search["hits"][:3]):
            rel = hit["path"]
            classification, department = attributes(rel)
            if department:
                semantic_departments.add(department)
            neighbours = [node.split(":", 1)[-1] for node in GRAPH.neighbors(graph, f"{root.name}:{rel}")]
            agentic.append(
                HYBRID.agentic_result(
                    result_id=f"agt-{index + 1}",
                    tool="vault_graph",
                    action="neighbors",
                    result={"path": rel, "neighbors": neighbours},
                    classification=classification,
                    provenance={"source": rel},
                )
            )
        bundle = HYBRID.bundle(
            query=query,
            semantic=semantic,
            agentic=agentic,
            department=next(iter(semantic_departments)) if len(semantic_departments) == 1 else None,
            vault_id=root.name,
        )
        return {"ok": True, "query": query, "bundle": bundle, "rendered": HYBRID.render_for_agent(bundle)}

    def vault_list(
        self, vault_path: str, prefix: str = "", limit: int = 500, scope_paths: list[str] | None = None
    ) -> dict[str, Any]:
        base = self._vault_candidate(vault_path, prefix)
        rows = []
        if base.is_dir():
            for path in sorted(base.rglob("*")):
                if not path.is_file() or path.is_symlink():
                    continue
                rel = path.relative_to(Path(vault_path).resolve()).as_posix()
                if any(part in VAULT_SKIP_PARTS for part in Path(rel).parts):
                    continue
                if path.name in VAULT_SKIP_NAMES:
                    continue
                if self._authority(rel):
                    continue
                if not self._scope_row(rel, scope_paths):
                    continue
                if path.suffix.lower() not in VAULT_SUFFIXES:
                    continue
                rows.append(rel)
                if len(rows) >= max(1, min(int(limit), 2000)):
                    break
        elif base.is_file():
            rel = base.relative_to(Path(vault_path).resolve()).as_posix()
            if base.name not in VAULT_SKIP_NAMES and self._scope_row(rel, scope_paths):
                rows = [rel]
        return {"ok": True, "vault": Path(vault_path).name, "paths": rows}

    def vault_read(self, vault_path: str, rel: str, scope_paths: list[str] | None = None) -> dict[str, Any]:
        path = self._vault_candidate(vault_path, rel)
        if not path.is_file() or path.is_symlink():
            raise GatewayError(404, "not-found", "vault page not found")
        relative = path.relative_to(Path(vault_path).resolve()).as_posix()
        if not self._scope_row(relative, scope_paths):
            raise GatewayError(403, "scope-refused", "page is outside the signed grant scope")
        size = path.stat().st_size
        if size > MAX_VAULT_FILE:
            raise GatewayError(413, "too-large", "vault page exceeds the read limit")
        return {
            "ok": True,
            "path": relative,
            "content": path.read_text(encoding="utf-8", errors="replace"),
            "bytes": size,
        }

    def vault_search(
        self, vault_path: str, query: str, top_k: int = 8, scope_paths: list[str] | None = None
    ) -> dict[str, Any]:
        terms = [term.lower() for term in re.split(r"\s+", query.strip()) if len(term) > 1][:8]
        if not terms:
            raise GatewayError(400, "malformed", "query must contain at least one word")
        scored = []
        root = Path(vault_path).resolve()
        for path in self._vault_files(vault_path):
            rel = path.relative_to(root).as_posix()
            if not self._scope_row(rel, scope_paths):
                continue
            try:
                if path.stat().st_size > MAX_VAULT_FILE:
                    continue
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            lowered = text.lower()
            score = sum(lowered.count(term) for term in terms)
            if score <= 0:
                continue
            first = min((lowered.find(term) for term in terms if lowered.find(term) >= 0), default=0)
            snippet = text[max(0, first - 180) : first + 420].replace("\n", " ").strip()
            scored.append(
                {
                    "path": rel,
                    "score": score,
                    "snippet": snippet,
                }
            )
        scored.sort(key=lambda row: (-row["score"], row["path"]))
        return {"ok": True, "query": query, "hits": scored[: max(1, min(int(top_k), 20))]}

    def vault_capture(
        self, vault_path: str, body: dict[str, Any], scope_paths: list[str] | None = None
    ) -> dict[str, Any]:
        title = str(body.get("title") or "").strip()
        text = str(body.get("body") or "").strip()
        if not title or not text:
            raise GatewayError(400, "malformed", "title and body are required")
        target = str(body.get("target") or "").strip()
        if not target:
            stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            target = f"01_Inbox/{stamp}-{self._slug(title)}.md"
        if not target.endswith(".md"):
            target += ".md"
        target_parts = Path(target).parts
        if not target_parts or target_parts[0] not in VAULT_CAPTURE_PREFIXES:
            raise GatewayError(
                403,
                "vault-forbidden",
                "capture target must be under 01_Inbox/, _raw/, 04_Evergreen/, 05_Knowledge/ or 06_Projects/",
            )
        path = self._vault_candidate(vault_path, target)
        relative = path.relative_to(Path(vault_path).resolve())
        if not relative.parts or relative.parts[0] not in VAULT_CAPTURE_PREFIXES:
            raise GatewayError(403, "vault-forbidden", "capture target must be under an allowed prefix")
        if not self._scope_row(relative.as_posix(), scope_paths):
            raise GatewayError(403, "scope-refused", "capture target is outside the grant's vault scope")
        if path.exists():
            stem = path.with_suffix("")
            for index in range(2, 100):
                candidate = Path(f"{stem}-{index}.md")
                if not candidate.exists():
                    path = candidate
                    break
            else:
                raise GatewayError(409, "exists", "target already exists")
        path.parent.mkdir(parents=True, exist_ok=True)
        created = datetime.now(timezone.utc).isoformat(timespec="seconds")
        front = (
            "---\n"
            f"title: {json.dumps(title, ensure_ascii=False)}\n"
            f"created: {created}\n"
            "source: open-webui\nsigned: false\n---\n\n"
        )
        path.write_text(front + text.rstrip() + "\n", encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(path, 0o640)
        return {
            "ok": True,
            "path": path.relative_to(Path(vault_path).resolve()).as_posix(),
            "title": title,
            "signed": False,
        }

    def rfi(self, question: str, scope: list[str]) -> dict[str, Any]:
        question = question.strip()
        if not question:
            raise GatewayError(400, "malformed", "question is required")
        scopes = [str(item).strip() for item in scope if str(item).strip()]
        if not scopes or len(scopes) > 8:
            raise GatewayError(400, "malformed", "scope must name 1-8 categories")
        bad = [item for item in scopes if item not in RFI_ALLOWED_SCOPE and not item.startswith("contracts/")]
        if bad:
            raise GatewayError(
                403, "scope-refused", "scope names a category the node may not request: {}".format(", ".join(bad))
            )
        client_path = Path(self._role_vault()) / "services" / "sparknet-rfi-client.py"
        if not client_path.is_file():
            raise GatewayError(503, "rfi-unavailable", "RFI client is not installed on this node")
        import subprocess

        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(client_path),
                    "--vault-root",
                    self._role_vault(),
                    "--question",
                    question,
                    "--scope",
                    ",".join(scopes),
                    "--json",
                ],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except Exception as exc:
            raise GatewayError(503, "rfi-unavailable", str(exc)) from exc
        if completed.returncode != 0:
            detail = (
                completed.stderr.decode("utf-8", "replace").strip()
                or completed.stdout.decode("utf-8", "replace").strip()
            )
            raise GatewayError(503, "rfi-unavailable", detail or "RFI client failed")
        try:
            return json.loads(completed.stdout.decode("utf-8"))
        except Exception as exc:
            raise GatewayError(503, "rfi-unavailable", f"RFI client returned malformed JSON: {exc}") from exc

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
        if method == "GET" and query:
            merged.update({key: values[0] for key, values in urllib.parse.parse_qs(query).items() if values})
        merged.update(constraints)
        if isinstance(merged.get("scope"), dict) and isinstance(constraints.get("scope"), dict):
            merged["scope"] = {**constraints["scope"], **merged["scope"]}
            merged["scope"]["user_id"] = constraints["scope"]["user_id"]
        if kind == "grant" and method == "POST" and path in GRANT_MUTATING:
            # Reserve before any mutation. A failed request burns its grant (a
            # retry needs a fresh grant), which is safer than a concurrent
            # double-write followed by a refusal.
            self._consume_grant_nonce(constraints.get("grant_nonce"))
        if path == "/v1/exec/validate":
            if method != "POST":
                raise GatewayError(405, "method-not-allowed", "execution validation requires POST")
            if kind != "local":
                raise GatewayError(403, "local-only", "execution validation is a local operator action")
            request = merged.get("request")
            if not isinstance(request, dict):
                raise GatewayError(400, "malformed", "request must be an object")
            normalised = EXEC.validate_request(request, verified=True)
            self.audit(kind, actor_id, "exec.validate", vault_path, {"request_id": normalised.get("request_id")})
            return 200, {"ok": True, "executed": False, "request": normalised}
        if path.startswith("/v1/collab/"):
            if path == "/v1/collab/rooms":
                if method != "GET":
                    raise GatewayError(405, "method-not-allowed", "room listing requires GET")
                payload = self.collab_list_rooms(vault_path)
                self.audit(kind, actor_id, "collab.rooms", vault_path, {"rooms": len(payload["rooms"])})
                return 200, payload
            if path == "/v1/collab/messages":
                if method != "GET":
                    raise GatewayError(405, "method-not-allowed", "message listing requires GET")
                payload = self.collab_list_messages(vault_path, str(merged.get("room_id") or ""))
                self.audit(kind, actor_id, "collab.messages", vault_path, {"room_id": merged.get("room_id")})
                return 200, payload
            if path == "/v1/collab/room":
                if method != "POST":
                    raise GatewayError(405, "method-not-allowed", "room creation requires POST")
                payload = self.collab_create_room(vault_path, actor_id, merged)
                self.audit(kind, actor_id, "collab.room.create", vault_path, {"room_id": payload["room"]["room_id"]})
                return 200, payload
            if path == "/v1/collab/message":
                if method != "POST":
                    raise GatewayError(405, "method-not-allowed", "messages require POST")
                payload = self.collab_post_message(vault_path, actor_id, merged)
                self.audit(kind, actor_id, "collab.message", vault_path, {"room_id": merged.get("room_id")})
                return 200, payload
            raise GatewayError(404, "not-found", "unknown collaboration route")
        if path.startswith("/v1/vault/"):
            if path == "/v1/vault/capture" and method != "POST":
                raise GatewayError(405, "method-not-allowed", "vault capture requires POST")
            if path == "/v1/vault/list":
                payload = self.vault_list(
                    vault_path,
                    prefix=str(merged.get("prefix") or ""),
                    limit=int(merged.get("limit") or 500),
                    scope_paths=constraints.get("scope_paths"),
                )
                self.audit(kind, actor_id, "vault.list", vault_path, {"prefix": merged.get("prefix")})
                return 200, payload
            if path == "/v1/vault/read":
                payload = self.vault_read(
                    vault_path, str(merged.get("path") or ""), scope_paths=constraints.get("scope_paths")
                )
                self.audit(kind, actor_id, "vault.read", vault_path, {"path": payload.get("path")})
                return 200, payload
            if path == "/v1/vault/search":
                payload = self.vault_search(
                    vault_path,
                    str(merged.get("query") or ""),
                    int(merged.get("top_k") or 8),
                    scope_paths=constraints.get("scope_paths"),
                )
                self.audit(kind, actor_id, "vault.search", vault_path, {"query": merged.get("query")})
                return 200, payload
            if path == "/v1/vault/graph":
                payload = self.vault_graph(vault_path, constraints.get("scope_paths"))
                self.audit(kind, actor_id, "vault.graph", vault_path, {"nodes": len(payload["graph"]["nodes"])})
                return 200, payload
            if path == "/v1/vault/hybrid":
                payload = self.vault_hybrid(
                    vault_path,
                    str(merged.get("query") or ""),
                    int(merged.get("top_k") or 8),
                    constraints.get("scope_paths"),
                )
                self.audit(kind, actor_id, "vault.hybrid", vault_path, {"query": merged.get("query")})
                return 200, payload
            if path == "/v1/vault/capture":
                payload = self.vault_capture(vault_path, merged, constraints.get("scope_paths"))
                self.audit(kind, actor_id, "vault.capture", vault_path, {"path": payload.get("path")})
                return 200, payload
            raise GatewayError(404, "not-found", "unknown vault route")
        if path == "/v1/rfi":
            if method != "POST":
                raise GatewayError(405, "method-not-allowed", "RFI requests require POST")
            payload = self.rfi(str(merged.get("question") or ""), list(merged.get("scope") or []))
            self.audit(
                kind,
                actor_id,
                "rfi.request",
                vault_path,
                {"scope": merged.get("scope"), "request": payload.get("request", {}).get("request_id")},
            )
            return 200, payload
        if path in MUTATING and method != "POST":
            raise GatewayError(405, "method-not-allowed", f"{path} requires POST")
        if path == "/v1/memory/remember":
            # The Go remember envelope is {vault_path, record}; the scope belongs
            # inside the record. A top-level scope is an unknown field there.
            record = merged.get("record")
            extra_scope = merged.pop("scope", None)
            if isinstance(record, dict):
                record_scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
                if isinstance(extra_scope, dict):
                    record_scope = {**extra_scope, **record_scope}
                    record_scope["user_id"] = extra_scope.get("user_id") or record_scope.get("user_id")
                record["scope"] = record_scope
        if path.startswith("/v1/delegates/"):
            if isinstance(merged.get("plan"), dict):
                merged["plan"]["user_id"] = actor_id
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
    timeout = 10
    gateway: Gateway

    def log_message(self, fmt: str, *args: Any) -> None:
        log(fmt % args)

    def _headers(self) -> dict[str, str]:
        return {key.lower(): value for key, value in self.headers.items()}

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError as exc:
            raise GatewayError(400, "malformed", "Content-Length is invalid") from exc
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
