"""Cross-language canonical vectors for the Step 89B foundations.

One fixture is shared by the Python modules and the goSpark mirror. A change to
a canonical form fails here before it can become a Python-only dialect.
"""

from __future__ import annotations

import json

import pytest
from contract_helpers import REPO_ROOT
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit


VECTORS = REPO_ROOT / "contracts" / "vectors" / "foundations.json"
GOSPARK_VECTORS = REPO_ROOT / "gospark" / "spec" / "sparknet" / "foundations-vectors.json"


def _load(name: str, relative: str):
    return load_by_path(name, REPO_ROOT / "shared" / relative)


event = _load("vectors_event", "sparknet-event.py")
graph = _load("vectors_graph", "sparknet-graph.py")
hybrid = _load("vectors_hybrid", "sparknet-hybrid.py")
exec_rpc = _load("vectors_exec", "sparknet-exec-rpc.py")
collab = _load("vectors_collab", "sparknet-collab.py")
package = _load("vectors_package", "sparknet-package.py")

CANONICAL = {
    "event.message": lambda value: event.event_message(value).decode("utf-8"),
    "graph.graph": graph.to_json,
    "hybrid.bundle": lambda value: hybrid.bundle_message(value).decode("utf-8"),
    "exec.request": lambda value: exec_rpc.request_message(value).decode("utf-8"),
    "collab.room": collab.to_json,
    "collab.message": collab.to_json,
    "package.package": lambda value: package.package_message(value).decode("utf-8"),
    "package.index": lambda value: package.index_message(value).decode("utf-8"),
    "agent.descriptor": lambda value: json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ),
    "self-improvement.run": lambda value: json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ),
    "release.manifest": lambda value: json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ),
    "data-lake.record": lambda value: json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ),
}


def test_fixture_has_every_foundation_form():
    payload = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "sparknet-foundation-vectors/1"
    names = {row["name"] for row in payload["vectors"]}
    assert names == set(CANONICAL)


def test_python_canonical_bytes_match_the_vectors():
    payload = json.loads(VECTORS.read_text(encoding="utf-8"))
    for row in payload["vectors"]:
        canonical = CANONICAL[row["name"]](row["input"])
        assert canonical == row["canonical"], row["name"]
        projected = json.dumps(
            row["canonical_input"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        assert projected == row["canonical"], row["name"]
        assert "NaN" not in canonical and "Infinity" not in canonical
        json.loads(canonical)


def test_goSpark_vector_snapshot_matches_when_present():
    if not GOSPARK_VECTORS.is_file():
        return
    assert GOSPARK_VECTORS.read_bytes() == VECTORS.read_bytes(), (
        "goSpark's foundations-vectors.json is stale; copy contracts/vectors/foundations.json "
        "to gospark/spec/sparknet/foundations-vectors.json"
    )
