#!/usr/bin/env python3
"""Read-only view over the fabric's Qdrant collections.

The console is stdlib-only by design: the runtime allow-list is
``cryptography`` alone, so it cannot import ``qdrant-client``. This module is
the dependency-free seam the console uses instead of growing its own HTTP
client, collection allow-list and vector projection.

It is a *view*. It never creates, upserts, deletes or snapshots a collection.
The writer remains ``scripts/sparknet-vector.py``; this module reads the same
collection names and the same ``sparknet-meta`` stamp point so a console cannot
present a stale or foreign collection as if it were the current index.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

META_COLLECTION = "sparknet-meta"
META_NAMESPACE = uuid.UUID("c3a7bb6e-4f6d-5d8e-9b8a-2b4f2f5b9c11")
DEFAULT_URI = "http://127.0.0.1:6333"
DEFAULT_LIMIT = 500


class VectorViewError(RuntimeError):
    """A read refusal with a stable code the console can map to HTTP."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def collection_name(scope: str) -> str:
    return f"sparknet-{scope}"


def scope_for_collection(name: str) -> str | None:
    prefix = "sparknet-"
    if name.startswith(prefix) and name != META_COLLECTION:
        return name[len(prefix) :]
    return None


def meta_point_id(scope: str) -> str:
    return str(uuid.uuid5(META_NAMESPACE, f"meta:{scope}"))


def _resolve(role_root: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path(role_root) / path


def _api_key(qdrant: dict[str, Any], role_root: Path) -> str | None:
    explicit = os.environ.get("SPARKNET_QDRANT_API_KEY") or os.environ.get("QDRANT_API_KEY")
    if explicit:
        return explicit
    path = _resolve(role_root, qdrant.get("api_key_file"))
    if path and path.is_file():
        try:
            return path.read_text(encoding="utf-8").strip() or None
        except OSError:
            return None
    return None


class VectorView:
    """The small read interface the console and the vector service share."""

    def __init__(
        self,
        *,
        uri: str,
        api_key: str | None = None,
        allowed_collections: tuple[str, ...] = (),
        excluded_prefixes: tuple[str, ...] = (),
        timeout: float = 15.0,
    ) -> None:
        self.uri = str(uri or DEFAULT_URI).rstrip("/")
        self.api_key = api_key
        self.allowed_collections = tuple(str(value) for value in allowed_collections)
        self.excluded_prefixes = tuple(str(value) for value in excluded_prefixes)
        self.timeout = timeout

    @classmethod
    def from_config(cls, config: dict[str, Any], role_root: Path) -> VectorView:
        qdrant = config.get("qdrant") or {}
        return cls(
            uri=str(qdrant.get("uri") or DEFAULT_URI),
            api_key=_api_key(qdrant, role_root),
            allowed_collections=tuple(qdrant.get("allowed_collections") or ()),
            excluded_prefixes=tuple(qdrant.get("excluded_prefixes") or ()),
        )

    @property
    def api_key_configured(self) -> bool:
        return bool(self.api_key)

    def allowed(self, name: str) -> bool:
        if any(name.startswith(prefix) for prefix in self.excluded_prefixes):
            return False
        return any(fnmatch.fnmatch(name, pattern) for pattern in self.allowed_collections)

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.uri + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        if self.api_key:
            request.add_header("api-key", self.api_key)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout or self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise VectorViewError("qdrant-http", f"Qdrant returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise VectorViewError("qdrant-unavailable", f"Qdrant unavailable: {exc}") from exc
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VectorViewError("qdrant-malformed", "Qdrant returned non-JSON") from exc

    def version(self) -> str | None:
        root = self._request("GET", "/")
        return (root or {}).get("version") if isinstance(root, dict) else None

    def collections(self, limit: int = 20) -> list[dict[str, Any]]:
        listing = self._request("GET", "/collections")
        rows = (listing or {}).get("result", {}).get("collections", []) if isinstance(listing, dict) else []
        names = sorted(
            str(row["name"])
            for row in rows
            if isinstance(row, dict) and row.get("name") and self.allowed(str(row["name"]))
        )
        result: list[dict[str, Any]] = []
        for name in names[:limit]:
            try:
                detail = self._collection_detail(name)
            except VectorViewError:
                detail = {}
            stamp = self.stamp(name)
            result.append(
                {
                    "name": name,
                    "status": detail.get("status"),
                    "points_count": detail.get("points_count"),
                    "vectors_count": detail.get("vectors_count"),
                    "vector_size": _vector_size(detail),
                    "distance": _distance(detail),
                    "index": {"status": "stamped" if stamp else "unstamped", "stamp": stamp},
                }
            )
        return result

    def _collection_detail(self, name: str) -> dict[str, Any]:
        info = self._request("GET", f"/collections/{urllib.parse.quote(name)}")
        result = (info or {}).get("result") if isinstance(info, dict) else None
        return result if isinstance(result, dict) else {}

    def stamp(self, name: str) -> dict[str, Any] | None:
        """The stored index stamp for a ``sparknet-<scope>`` collection.

        An absent stamp is not an error: a foreign collection (an Open WebUI
        collection, for example) has none. A console must show that absence as
        ``unstamped`` rather than claim the index is current.
        """
        scope = scope_for_collection(name)
        if scope is None:
            return None
        try:
            result = self._request(
                "POST",
                f"/collections/{META_COLLECTION}/points",
                {"ids": [meta_point_id(scope)], "with_payload": True, "with_vector": False},
            )
        except VectorViewError:
            return None
        rows = result.get("result") if isinstance(result, dict) else None
        if isinstance(rows, dict):
            rows = rows.get("points")
        if not isinstance(rows, list) or not rows:
            return None
        point = rows[0]
        payload = point.get("payload") if isinstance(point, dict) else None
        return dict(payload) if isinstance(payload, dict) else None

    def sample(self, name: str, limit: int = DEFAULT_LIMIT) -> list[dict[str, Any]]:
        if not self.allowed(name):
            raise VectorViewError("collection-not-allowed", "collection is outside this surface")
        result = self._request(
            "POST",
            f"/collections/{urllib.parse.quote(name)}/points/scroll",
            {"limit": max(1, min(int(limit), DEFAULT_LIMIT)), "with_payload": True, "with_vector": True},
        )
        points = (result or {}).get("result", {}).get("points", []) if isinstance(result, dict) else []
        return [point for point in points if isinstance(point, dict)]


def _vector_size(detail: dict[str, Any]) -> int | None:
    vectors = ((detail.get("config") or {}).get("params") or {}).get("vectors")
    if isinstance(vectors, dict) and vectors:
        first = next(iter(vectors.values()))
        if isinstance(first, dict):
            return first.get("size")
        return vectors.get("size")
    return None


def _distance(detail: dict[str, Any]) -> str | None:
    vectors = ((detail.get("config") or {}).get("params") or {}).get("vectors")
    if isinstance(vectors, dict) and vectors:
        first = next(iter(vectors.values()))
        if isinstance(first, dict):
            return first.get("distance")
        return vectors.get("distance")
    return None


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
