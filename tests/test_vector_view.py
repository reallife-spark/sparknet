"""The shared read-only vector view matches the writer's names and stamps."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

ROOT = Path(__file__).resolve().parent.parent
SHARED = ROOT / "shared"


def _load_view():
    return load_by_path("sparknet_vector_view_test", SHARED / "sparknet-vector-view.py")


def _load_vector():
    return load_by_path("sparknet_vector_writer_test", ROOT / "scripts" / "sparknet-vector.py")


view = _load_view()
vector = _load_vector()


class _Qdrant(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            self._json({"version": "1.20.0"})
        elif self.path == "/collections":
            self._json(
                {
                    "result": {
                        "collections": [
                            {"name": "sparknet-fabric"},
                            {"name": "uplift-x"},
                            {"name": "open-webui_knowledge"},
                        ]
                    }
                }
            )
        elif self.path == "/collections/sparknet-fabric":
            self._json(
                {
                    "result": {
                        "status": "green",
                        "points_count": 2,
                        "vectors_count": 2,
                        "config": {"params": {"vectors": {"size": 3, "distance": "Cosine"}}},
                    }
                }
            )
        else:
            self._json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if self.path == "/collections/sparknet-meta/points":
            self._json(
                {
                    "result": [
                        {
                            "id": "meta",
                            "payload": {
                                "embedding_model": "m",
                                "corpus_digest": "d",
                                "qdrant_version": "1.20.0",
                            },
                        }
                    ]
                }
            )
        elif self.path.endswith("/points/scroll"):
            self._json(
                {
                    "result": {
                        "points": [
                            {"id": 1, "vector": [1.0, 0.0, 0.0], "payload": {"doc_id": "a"}},
                            {"id": 2, "vector": [0.0, 1.0, 0.0], "payload": {"doc_id": "b"}},
                        ]
                    }
                }
            )
        else:
            self._json({"error": "not found"}, status=404)

    def _json(self, body: dict, status: int = 200) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture
def qdrant():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Qdrant)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def _view(url: str):
    return view.VectorView(
        uri=url,
        allowed_collections=("sparknet-*", "open-webui_*"),
        excluded_prefixes=("uplift-",),
    )


def test_collection_names_and_stamp_ids_match_the_writer() -> None:
    assert view.collection_name("fabric") == vector._collection_name("fabric")
    assert view.meta_point_id("fabric") == vector._meta_point_id("fabric")
    assert view.META_NAMESPACE == vector.META_NAMESPACE


def test_view_filters_collections_and_reads_the_stamp(qdrant: str) -> None:
    result = _view(qdrant).collections()
    names = [row["name"] for row in result]
    assert names == ["open-webui_knowledge", "sparknet-fabric"]
    fabric = next(row for row in result if row["name"] == "sparknet-fabric")
    assert fabric["vector_size"] == 3
    assert fabric["index"]["status"] == "stamped"
    assert fabric["index"]["stamp"]["corpus_digest"] == "d"
    assert next(row for row in result if row["name"] == "open-webui_knowledge")["index"]["status"] == "unstamped"


def test_sample_refuses_a_collection_outside_the_allow_list(qdrant: str) -> None:
    with pytest.raises(view.VectorViewError) as refused:
        _view(qdrant).sample("uplift-x", 10)
    assert refused.value.code == "collection-not-allowed"


def test_projection_is_deterministic_and_uses_payload_labels() -> None:
    points = [
        {"id": 1, "vector": [1.0, 0.0, 0.0], "payload": {"doc_id": "a", "role": "teacher"}},
        {"id": 2, "vector": [0.0, 1.0, 0.0], "payload": {"doc_id": "b"}},
    ]
    first = view.project_points(points, "agx64")
    second = view.project_points(points, "agx64")
    assert first == second
    assert [row["label"] for row in first] == ["a", "b"]
    assert {row["role"] for row in first} == {"teacher", "knowledge"}
