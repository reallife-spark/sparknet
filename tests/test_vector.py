"""The optional local Qdrant index tool (`scripts/sparknet-vector.py`).

Two properties are worth locking down because both are easy to break quietly:

1. **qdrant-client must stay optional.** The runtime dependency allow-list is
   `cryptography` alone; a node that just wants to `inspect` a vault must never
   import Qdrant. The pure logic (scope resolution, discovery, deterministic
   chunking, doc ids, stamp comparison) is asserted on a host that has the
   package absent.
2. **The plan is deterministic.** `inspect`/`index` must compute the same ids
   and chunks every run, so a re-index is an idempotent upsert by stable point
   id rather than an ever-growing pile of dupes.

The real-Qdrant round trip is skipped when the optional package is absent.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "sparknet-vector.py"
SCOPES = ("peer", "master", "fabric", "shared")


def _load():
    spec = importlib.util.spec_from_file_location("sparknet_vector", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


vector = _load()
_run = [sys.executable, str(SCRIPT)]


def _has_qdrant() -> bool:
    try:
        import qdrant_client  # noqa: F401 - only to decide whether to skip

        return True
    except ImportError:
        return False


def _env(**over: str) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("SPARKNET_QDRANT_URL", None)
    env.pop("SPARKNET_QDRANT_PATH", None)
    env["SPARKNET_EMBED_BACKEND"] = "hash"
    env["SPARKNET_EMBED_DIM"] = "48"
    env.update(over)
    return env


# --- the tool is importable without qdrant-client -----------------------------


def test_module_imports_without_qdrant() -> None:
    assert callable(vector.chunk_text)
    assert callable(vector.plan_index)


def test_scope_resolution_places_data_inside_the_scope_vault() -> None:
    assert vector.resolve_scope("peer") == (
        "sparknet-peer",
        REPO_ROOT / "peer-node",
        REPO_ROOT / "peer-node" / ".state" / "qdrant",
    )
    assert vector.resolve_scope("master") == (
        "sparknet-master",
        REPO_ROOT / "master-node",
        REPO_ROOT / "master-node" / ".state" / "qdrant",
    )
    assert vector.resolve_scope("fabric") == (
        "sparknet-fabric",
        REPO_ROOT,
        REPO_ROOT / ".state" / "qdrant",
    )
    assert vector.resolve_scope("shared") == (
        "sparknet-shared",
        REPO_ROOT / "master-node",
        REPO_ROOT / "master-node" / ".state" / "qdrant-shared",
    )


def test_rejects_unknown_scope() -> None:
    with pytest.raises(ValueError):
        vector.resolve_scope("peer-node")


# --- deterministic chunking ---------------------------------------------------


def test_chunk_text_is_deterministic() -> None:
    text = "paragraph one.\n\n" * 40
    assert vector.chunk_text(text) == vector.chunk_text(text)


def test_chunk_text_respects_the_size_ceiling() -> None:
    text = ("word " * 3000).rstrip()
    for chunk in vector.chunk_text(text, max_chars=2000):
        assert len(chunk) <= 4000


def test_chunk_text_splits_on_paragraph_boundaries() -> None:
    assert vector.chunk_text("a.\n\nb.\n\nc.", max_chars=4) == ["a.", "b.", "c."]


def test_chunk_text_of_a_single_oversized_paragraph_is_split() -> None:
    chunks = vector.chunk_text("one. " * 1000, max_chars=100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)


# --- discovery ----------------------------------------------------------------


def test_fabric_discovery_is_an_allow_list_not_a_whole_tree_walk(tmp_path: Path) -> None:
    for path in (
        tmp_path / "AGENTS.md",
        tmp_path / "concepts" / "one.md",
        tmp_path / "peer-node" / "05_Knowledge" / "concepts" / "peer.md",
        tmp_path / "master-node" / "05_Knowledge" / "concepts" / "master.md",
        tmp_path / ".opencode" / "skills" / "x" / "SKILL.md",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content")
    policy = vector._policy()
    found = [p.name for p in vector.iter_markdown(tmp_path, allow_list=policy.FABRIC_ROOTS)]
    assert found == ["AGENTS.md"]


def test_peer_scope_excludes_other_role_and_shared(tmp_path: Path) -> None:
    scope_root = tmp_path / "peer-node"
    (scope_root / "05_Knowledge" / "concepts").mkdir(parents=True)
    (scope_root / "05_Knowledge" / "concepts" / "peer.md").write_text("peer")
    (scope_root / "blockchain").mkdir()
    (scope_root / "blockchain" / "ledger.json").write_text("{}")
    found = list(vector.plan_index("peer", scope_root))
    assert len(found) == 1
    assert found[0]["path"] == "05_Knowledge/concepts/peer.md"


# --- doc ids / plan -----------------------------------------------------------


def test_doc_ids_are_stable_and_namespaced(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("alpha")
    assert vector.plan_index("fabric", tmp_path) == vector.plan_index("fabric", tmp_path)
    ids = [d["id"] for d in vector.plan_index("fabric", tmp_path)]
    assert ids and ids == sorted(ids)
    for doc_id in ids:
        assert doc_id.startswith("fabric:") and "#" in doc_id
        assert vector.point_id(doc_id) == vector.point_id(doc_id)


def test_plan_index_returns_paths_not_absolute(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("x")
    (tmp_path / "contracts").mkdir(parents=True)
    (tmp_path / "contracts" / "ports.json").write_text("{}")
    for entry in vector.plan_index("fabric", tmp_path):
        assert not Path(str(entry["path"])).is_absolute()
        assert "/mnt/" not in str(entry["path"])


# --- the stamp (pure logic; no Qdrant) ----------------------------------------


def _stamp(**over: str) -> dict[str, str]:
    base = {
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "embedding_sha256": "913d7300",
        "embedding_dim": "384",
        "embedding_backend": "fastembed",
        "qdrant_version": "1.20.0",
        "corpus_digest": "deadbeef",
    }
    base.update(over)
    return base


def test_corpus_digest_is_deterministic_and_content_sensitive() -> None:
    docs = [
        {"id": "fabric:a.md#0", "document": "alpha"},
        {"id": "fabric:b.md#0", "document": "beta"},
    ]
    first = vector.corpus_digest(docs)
    assert first == vector.corpus_digest(list(reversed(docs)))
    assert first != vector.corpus_digest([{"id": "fabric:a.md#0", "document": "alpha, edited"}])


def test_a_matching_stamp_has_no_refusals_and_no_reports() -> None:
    assert vector.stamp_mismatch(_stamp(), _stamp()) == ([], [])


@pytest.mark.parametrize("field", ["embedding_model", "embedding_sha256", "embedding_dim", "corpus_digest"])
def test_a_changed_refusal_field_refuses(field: str) -> None:
    refusals, _ = vector.stamp_mismatch(_stamp(**{field: "other"}), _stamp())
    assert refusals and field in refusals[0]


@pytest.mark.parametrize("field", ["embedding_backend", "qdrant_version"])
def test_a_changed_report_field_only_reports(field: str) -> None:
    refusals, reports = vector.stamp_mismatch(_stamp(**{field: "other"}), _stamp())
    assert refusals == []
    assert reports and field in reports[0]


def test_a_missing_stamp_field_refuses() -> None:
    refusals, _ = vector.stamp_mismatch(_stamp(corpus_digest=""), _stamp())
    assert refusals and "corpus_digest" in refusals[0]


# --- CLI behaviour without qdrant-client --------------------------------------


@pytest.mark.skipif(_has_qdrant(), reason="qdrant-client installed; the missing-case can't hold")
def test_init_without_qdrant_fails_with_a_hint(tmp_path: Path) -> None:
    proc = subprocess.run(
        [*_run, "peer", "init", "--data-dir", str(tmp_path / "qdrant")],
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 2
    assert "qdrant-client is not installed" in proc.stdout + proc.stderr
    assert "make vector-dev" in proc.stdout + proc.stderr


def test_init_creates_the_state_dir_at_0700(tmp_path: Path) -> None:
    data_dir = tmp_path / "qdrant"
    subprocess.run(
        [*_run, "peer", "init", "--data-dir", str(data_dir)],
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert oct(data_dir.stat().st_mode & 0o777) == "0o700"


def test_inspect_never_touches_qdrant() -> None:
    proc = subprocess.run([*_run, "peer", "inspect"], capture_output=True, text=True, env=_env())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "documents: " in proc.stdout


# --- real Qdrant round trip (skipped when the optional package is absent) -----

REAL_QDRANT = pytest.mark.skipif(not _has_qdrant(), reason="qdrant-client not installed; optional extra is opt-in")


def _index(vault: Path, data_dir: Path, scope: str = "peer") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_run, scope, "index", "--data-dir", str(data_dir), "--vault", str(vault)],
        capture_output=True,
        text=True,
        env=_env(),
    )


def _query(vault: Path, data_dir: Path, text: str, scope: str = "peer") -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_run, scope, "query", text, "--top-k", "3", "--data-dir", str(data_dir), "--vault", str(vault)],
        capture_output=True,
        text=True,
        env=_env(),
    )


@REAL_QDRANT
def test_index_and_query_round_trip(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "concepts").mkdir(parents=True)
    (vault / "concepts" / "peering.md").write_text(
        "The peer verifies a Master-signed authorization before applying it."
    )
    data_dir = tmp_path / "qdrant"
    assert _index(vault, data_dir).returncode == 0
    proc = _query(vault, data_dir, "peer verifies authorization")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "concepts/peering.md" in proc.stdout


@REAL_QDRANT
def test_index_stamps_the_collection(tmp_path: Path) -> None:
    from qdrant_client import QdrantClient

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "AGENTS.md").write_text("the fabric's charter")
    data_dir = tmp_path / "qdrant"
    assert _index(vault, data_dir, "fabric").returncode == 0
    client = QdrantClient(path=str(data_dir))
    try:
        points = client.retrieve(
            collection_name="sparknet-meta",
            ids=[vector._meta_point_id("fabric")],
            with_payload=True,
        )
        payload = dict(points[0].payload or {})
    finally:
        client.close()
    assert payload.get("embedding_model")
    assert payload.get("embedding_sha256")
    assert payload.get("embedding_backend") == "hash"
    assert payload.get("corpus_digest") == vector.corpus_digest(vector.plan_index("fabric", vault))


@REAL_QDRANT
def test_a_tampered_stamp_refuses_the_query(tmp_path: Path) -> None:
    from qdrant_client import QdrantClient, models

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "AGENTS.md").write_text("the fabric's charter")
    data_dir = tmp_path / "qdrant"
    assert _index(vault, data_dir, "fabric").returncode == 0
    client = QdrantClient(path=str(data_dir))
    try:
        point = client.retrieve(
            collection_name="sparknet-meta",
            ids=[vector._meta_point_id("fabric")],
            with_payload=True,
        )[0]
        payload = dict(point.payload or {})
        payload["corpus_digest"] = "0" * 64
        client.upsert(
            collection_name="sparknet-meta",
            points=[models.PointStruct(id=point.id, vector=[0.0], payload=payload)],
        )
    finally:
        client.close()
    proc = _query(vault, data_dir, "fabric", "fabric")
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "REFUSED" in proc.stdout + proc.stderr
    assert "corpus_digest" in proc.stdout + proc.stderr


@REAL_QDRANT
def test_the_stamp_verb_reports_a_match(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "AGENTS.md").write_text("the fabric's charter")
    data_dir = tmp_path / "qdrant"
    assert _index(vault, data_dir, "fabric").returncode == 0
    proc = subprocess.run(
        [*_run, "fabric", "stamp", "--data-dir", str(data_dir), "--vault", str(vault)],
        capture_output=True,
        text=True,
        env=_env(),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "stamp: match" in proc.stdout


@REAL_QDRANT
def test_query_against_a_missing_index_refuses_rather_than_answering(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "AGENTS.md").write_text("the fabric's charter")
    proc = _query(vault, tmp_path / "qdrant", "fabric", "fabric")
    assert proc.returncode == 3
    assert "REFUSED" in proc.stdout + proc.stderr


@REAL_QDRANT
def test_reindex_removes_stale_chunks(tmp_path: Path) -> None:
    from qdrant_client import QdrantClient

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "one.md").write_text("one passage")
    (vault / "two.md").write_text("two passage")
    data_dir = tmp_path / "qdrant"
    assert _index(vault, data_dir).returncode == 0
    (vault / "two.md").unlink()
    assert _index(vault, data_dir).returncode == 0
    client = QdrantClient(path=str(data_dir))
    try:
        count = client.count(collection_name="sparknet-peer").count
    finally:
        client.close()
    assert count == len(vector.plan_index("peer", vault))
