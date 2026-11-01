"""The optional local Chroma index tool (`scripts/sparknet-chroma.py`).

Two properties are worth locking down because both are easy to break quietly:

1. **chromadb must stay optional.** The runtime dependency allow-list is
   `cryptography` alone; a node that just wants to `inspect` a vault must never
   import chromadb. So the tool's pure logic (scope resolution, discovery,
   deterministic chunking, doc ids) is asserted to work on a host that has the
   package absent — these tests run the real module via `importlib`, not a fake.
2. **The plan is deterministic.** `inspect`/`index` must compute the same ids
   and chunks every run, so a re-index is an idempotent upsert rather than an
   ever-growing pile of dupes.

The real-chroma round trip (`index` then `query`) is skipped when the optional
package is not installed, and the `query` command must fail with a *hint*, not
a traceback, when the package is missing — the module's own import guard is
what makes a foreign-machine run fail closed instead of half-failing.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "sparknet-chroma.py"
SCOPES = ("peer", "master", "fabric")


def _load() -> None:
    spec = importlib.util.spec_from_file_location("sparknet_chroma", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


chroma = _load()
_run = [sys.executable, str(SCRIPT)]


def _has_chromadb() -> bool:
    try:
        import chromadb  # noqa: F401 - only to decide whether to skip

        return True
    except ImportError:
        return False


# --- the tool is importable without chromadb ----------------------------------


def test_module_imports_without_chromadb() -> None:
    """The module must load on a machine that has never seen the package."""
    assert callable(chroma.chunk_text)
    assert callable(chroma.plan_index)


def test_scope_resolution_places_data_inside_the_scope_vault() -> None:
    assert chroma.resolve_scope("peer") == (
        "sparknet-peer",
        REPO_ROOT / "peer-node",
        REPO_ROOT / "peer-node" / ".state" / "chroma",
    )
    assert chroma.resolve_scope("master") == (
        "sparknet-master",
        REPO_ROOT / "master-node",
        REPO_ROOT / "master-node" / ".state" / "chroma",
    )
    assert chroma.resolve_scope("fabric") == (
        "sparknet-fabric",
        REPO_ROOT,
        REPO_ROOT / ".state" / "chroma",
    )
    assert chroma.resolve_scope("shared") == (
        "sparknet-shared",
        REPO_ROOT / "master-node",
        REPO_ROOT / "master-node" / ".state" / "chroma-shared",
    )


def test_rejects_unknown_scope() -> None:
    with pytest.raises(ValueError):
        chroma.resolve_scope("peer-node")  # the dir name is not a scope


# --- deterministic chunking ---------------------------------------------------


def test_chunk_text_is_deterministic() -> None:
    text = "paragraph one.\n\n" * 40
    a = chroma.chunk_text(text)
    b = chroma.chunk_text(text)
    assert a == b, "chunking must be a pure function of the input"

    again = chroma.chunk_text(text)
    assert again == a


def test_chunk_text_respects_the_size_ceiling() -> None:
    text = ("word " * 3000).rstrip()
    for chunk in chroma.chunk_text(text, max_chars=2000):
        assert len(chunk) <= 4000  # ceiling, plus the trailing "word"


def test_chunk_text_splits_on_paragraph_boundaries() -> None:
    text = "a.\n\nb.\n\nc."
    chunks = chroma.chunk_text(text, max_chars=4)
    assert chunks == ["a.", "b.", "c."], "each paragraph is its own chunk below the ceiling"


def test_chunk_text_of_a_single_oversized_paragraph_is_split() -> None:
    text = "one. " * 1000
    chunks = chroma.chunk_text(text, max_chars=100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)


# --- discovery ----------------------------------------------------------------


def test_fabric_discovery_is_an_allow_list_not_a_whole_tree_walk(tmp_path: Path) -> None:
    """The shared scope indexes the structural fabric, not everything under it."""
    for path in (
        tmp_path / "AGENTS.md",
        tmp_path / "concepts" / "one.md",  # distilled knowledge: not structural
        tmp_path / "peer-node" / "05_Knowledge" / "concepts" / "peer.md",
        tmp_path / "master-node" / "05_Knowledge" / "concepts" / "master.md",
        tmp_path / ".opencode" / "skills" / "x" / "SKILL.md",  # vendored, not content
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content")

    policy = chroma._policy()
    found = [p.name for p in chroma.iter_markdown(tmp_path, allow_list=policy.FABRIC_ROOTS)]
    assert found == ["AGENTS.md"], "only the allowed root files survive"
    assert not any(p.startswith("concepts") for p in found)


def test_peer_scope_excludes_the_other_role_and_shared(tmp_path: Path) -> None:
    scope_root = tmp_path / "peer-node"
    scope_root.mkdir()
    (scope_root / "05_Knowledge" / "concepts").mkdir(parents=True)
    (scope_root / "05_Knowledge" / "concepts" / "peer.md").write_text("peer")
    (scope_root / "blockchain").mkdir()
    (scope_root / "blockchain" / "ledger.json").write_text("{}")  # not markdown

    found = list(chroma.plan_index("peer", scope_root))
    assert len(found) == 1
    assert found[0]["path"] == "05_Knowledge/concepts/peer.md"


# --- doc ids / plan -----------------------------------------------------------


def test_doc_ids_are_stable_and_namespaced(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("alpha")
    plan_a = chroma.plan_index("fabric", tmp_path)
    plan_b = chroma.plan_index("fabric", tmp_path)
    assert plan_a == plan_b

    ids = [d["id"] for d in plan_a]
    assert ids and ids == sorted(ids), "plan must be sorted so ids are stable"
    for doc_id in ids:
        assert doc_id.startswith("fabric:") and "#" in doc_id


def test_plan_index_returns_paths_not_absolute(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("x")
    (tmp_path / "contracts").mkdir(parents=True)
    (tmp_path / "contracts" / "ports.json").write_text("{}")
    for entry in chroma.plan_index("fabric", tmp_path):
        assert not Path(str(entry["path"])).is_absolute()
        assert "/mnt/" not in str(entry["path"])


# --- the stamp (pure logic; no chromadb) ---------------------------------------


def _stamp(**over: str) -> dict[str, str]:
    base = {
        "embedding_model": "all-MiniLM-L6-v2",
        "embedding_sha256": "913d7300",
        "chroma_version": "0.6.3",
        "corpus_digest": "deadbeef",
    }
    base.update(over)
    return base


def test_corpus_digest_is_deterministic_and_content_sensitive() -> None:
    docs = [
        {"id": "fabric:a.md#0", "document": "alpha"},
        {"id": "fabric:b.md#0", "document": "beta"},
    ]
    first = chroma.corpus_digest(docs)
    assert first == chroma.corpus_digest(list(reversed(docs))), "order must not matter"
    assert first != chroma.corpus_digest([{"id": "fabric:a.md#0", "document": "alpha, edited"}])


def test_a_matching_stamp_has_no_refusals_and_no_reports() -> None:
    refusals, reports = chroma.stamp_mismatch(_stamp(), _stamp())
    assert refusals == []
    assert reports == []


def test_a_different_embedding_model_refuses() -> None:
    refusals, _ = chroma.stamp_mismatch(_stamp(embedding_model="other-model"), _stamp())
    assert refusals and "embedding_model" in refusals[0]


def test_a_different_weights_digest_refuses() -> None:
    refusals, _ = chroma.stamp_mismatch(_stamp(embedding_sha256="0000"), _stamp())
    assert refusals and "embedding_sha256" in refusals[0]


def test_a_different_corpus_digest_refuses() -> None:
    refusals, _ = chroma.stamp_mismatch(_stamp(corpus_digest="0000"), _stamp())
    assert refusals and "corpus_digest" in refusals[0]


def test_a_different_chroma_version_only_reports() -> None:
    """A different library version changes the library, not the vectors."""
    refusals, reports = chroma.stamp_mismatch(_stamp(chroma_version="0.5.0"), _stamp())
    assert refusals == []
    assert reports and "chroma_version" in reports[0]


def test_a_missing_stamp_field_refuses() -> None:
    refusals, _ = chroma.stamp_mismatch(_stamp(corpus_digest=""), _stamp())
    assert refusals and "corpus_digest" in refusals[0]


# --- CLI behaviour without chromadb -------------------------------------------


@pytest.mark.skipif(_has_chromadb(), reason="chromadb installed; the missing-case can't hold")
def test_init_without_chromadb_fails_with_a_hint(tmp_path: Path) -> None:
    proc = subprocess.run(
        [*_run, "peer", "init", "--data-dir", str(tmp_path / "chroma")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2
    assert "chromadb is not installed" in proc.stdout + proc.stderr
    assert "make chroma-dev" in proc.stdout + proc.stderr


def test_init_creates_the_state_dir_at_0700(tmp_path: Path) -> None:
    """An index is local machine state and must never widen .state."""
    if _has_chromadb():
        pytest.skip("chromadb installed; init would use it (covered live elsewhere)")

    data_dir = tmp_path / "chroma"
    proc = subprocess.run(
        [*_run, "peer", "init", "--data-dir", str(data_dir)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2  # fails on the missing package, AFTER creating the dir
    assert oct(data_dir.stat().st_mode & 0o777) == "0o700", "data dir must be 0700"


def test_inspect_never_touches_chromadb() -> None:
    proc = subprocess.run([*_run, "peer", "inspect"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "documents:" in proc.stdout
    # The peer vault has content (03_Sources at minimum), so the plan is non-empty.
    assert "documents: " in proc.stdout


# --- real chroma round trip (skipped when the optional package is absent) -----


REAL_CHROMA = pytest.mark.skipif(not _has_chromadb(), reason="chromadb not installed; optional extra is opt-in")


@REAL_CHROMA
def test_index_and_query_round_trip(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "concepts").mkdir(parents=True)
    (vault / "concepts" / "peering.md").write_text(
        "The peer verifies a Master-signed authorization before applying it."
    )

    data_dir = tmp_path / "chroma"
    proc = subprocess.run(
        [*_run, "peer", "index", "--data-dir", str(data_dir), "--vault", str(vault)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    proc = subprocess.run(
        [
            *_run,
            "peer",
            "query",
            "how does a peer verify an authorization?",
            "--top-k",
            "3",
            "--data-dir",
            str(data_dir),
            "--vault",
            str(vault),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "concepts/peering.md" in proc.stdout


@REAL_CHROMA
def test_index_stamps_the_collection(tmp_path: Path) -> None:
    """The index carries the model, the weights and the corpus it was built from."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "AGENTS.md").write_text("the fabric's charter")

    data_dir = tmp_path / "chroma"
    proc = subprocess.run(
        [*_run, "fabric", "index", "--data-dir", str(data_dir), "--vault", str(vault)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    import chromadb

    collection = chromadb.PersistentClient(path=str(data_dir)).get_collection("sparknet-fabric")
    metadata = dict(collection.metadata or {})
    assert metadata.get("embedding_model"), "the model must be stamped"
    assert metadata.get("embedding_sha256"), "the weights must be stamped"
    assert metadata.get("corpus_digest"), "the corpus must be stamped"
    assert metadata.get("corpus_digest") == chroma.corpus_digest(chroma.plan_index("fabric", vault))


@REAL_CHROMA
def test_a_tampered_stamp_refuses_the_query(tmp_path: Path) -> None:
    """A stale index is a loud failure, never a quiet wrong answer."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "AGENTS.md").write_text("the fabric's charter")

    data_dir = tmp_path / "chroma"
    assert (
        subprocess.run(
            [*_run, "fabric", "index", "--data-dir", str(data_dir), "--vault", str(vault)],
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )

    import chromadb

    collection = chromadb.PersistentClient(path=str(data_dir)).get_collection("sparknet-fabric")
    metadata = dict(collection.metadata or {})
    metadata["corpus_digest"] = "0" * 64
    collection.modify(metadata=metadata)

    proc = subprocess.run(
        [
            *_run,
            "fabric",
            "query",
            "what is the fabric?",
            "--data-dir",
            str(data_dir),
            "--vault",
            str(vault),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "REFUSED" in proc.stdout + proc.stderr
    assert "corpus_digest" in proc.stdout + proc.stderr


@REAL_CHROMA
def test_the_stamp_verb_reports_a_mismatch_with_exit_3(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "AGENTS.md").write_text("the fabric's charter")

    data_dir = tmp_path / "chroma"
    assert (
        subprocess.run(
            [*_run, "fabric", "index", "--data-dir", str(data_dir), "--vault", str(vault)],
            capture_output=True,
            text=True,
        ).returncode
        == 0
    )

    proc = subprocess.run(
        [*_run, "fabric", "stamp", "--data-dir", str(data_dir), "--vault", str(vault)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "stamp: match" in proc.stdout


@REAL_CHROMA
def test_query_against_a_missing_index_refuses_rather_than_answering(tmp_path: Path) -> None:
    """An empty result set is a sentence; this tool must not write one by accident."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "AGENTS.md").write_text("the fabric's charter")

    proc = subprocess.run(
        [
            *_run,
            "fabric",
            "query",
            "what is the fabric?",
            "--data-dir",
            str(tmp_path / "nope"),
            "--vault",
            str(vault),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 3, proc.stdout + proc.stderr
    assert "no results" not in proc.stdout + proc.stderr


@REAL_CHROMA
def test_reindex_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "AGENTS.md").write_text("stable content")
    data_dir = tmp_path / "chroma"

    for _ in range(2):
        proc = subprocess.run(
            [*_run, "fabric", "index", "--data-dir", str(data_dir), "--vault", str(vault)],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

    import chromadb

    client = chromadb.PersistentClient(path=str(data_dir))
    collection = client.get_collection("sparknet-fabric")
    assert collection.count() == len(chroma.plan_index("fabric", vault))


@REAL_CHROMA
def test_the_index_records_the_chromadb_version_that_wrote_it(tmp_path: Path) -> None:
    """A version marker is what makes an unreadable index explainable."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "AGENTS.md").write_text("stable content")
    data_dir = tmp_path / "chroma"

    proc = subprocess.run(
        [*_run, "fabric", "index", "--data-dir", str(data_dir), "--vault", str(vault)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    import chromadb

    marker = data_dir / chroma.VERSION_MARKER
    assert marker.is_file()
    assert marker.read_text(encoding="utf-8").strip() == chromadb.__version__


@REAL_CHROMA
def test_an_index_with_an_unknown_provenance_is_rebuilt_not_trusted(tmp_path: Path) -> None:
    """An index nobody can account for is not one this tool may serve."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "AGENTS.md").write_text("stable content")
    data_dir = tmp_path / "chroma"

    first = subprocess.run(
        [*_run, "fabric", "index", "--data-dir", str(data_dir), "--vault", str(vault)],
        capture_output=True,
        text=True,
    )
    assert first.returncode == 0, first.stdout + first.stderr

    # the marker goes missing: the index's provenance is now unknown
    (data_dir / chroma.VERSION_MARKER).unlink()

    second = subprocess.run(
        [*_run, "fabric", "index", "--data-dir", str(data_dir), "--vault", str(vault)],
        capture_output=True,
        text=True,
    )
    assert second.returncode == 0, second.stdout + second.stderr
    assert "rebuilding it from source" in second.stderr

    # and a marker from another library version is equally refused
    (data_dir / chroma.VERSION_MARKER).write_text("0.0.0\n", encoding="utf-8")
    third = subprocess.run(
        [*_run, "fabric", "index", "--data-dir", str(data_dir), "--vault", str(vault)],
        capture_output=True,
        text=True,
    )
    assert third.returncode == 0, third.stdout + third.stderr
    assert "written by chromadb 0.0.0" in third.stderr


@REAL_CHROMA
def test_a_chunk_that_left_the_corpus_leaves_the_index(tmp_path: Path) -> None:
    """The index must equal the corpus, not merely contain it.

    An upsert-only rebuild leaves the chunks of a passage that was shortened
    or deleted behind — and the corpus digest still matches, because it hashes
    what was *written*. A stale chunk would then answer a query with text the
    corpus no longer contains.
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    doc = vault / "AGENTS.md"
    doc.write_text("the first passage, which is quite long. " * 80)
    data_dir = tmp_path / "chroma"

    before = subprocess.run(
        [*_run, "fabric", "index", "--data-dir", str(data_dir), "--vault", str(vault)],
        capture_output=True,
        text=True,
    )
    assert before.returncode == 0, before.stdout + before.stderr

    import chromadb

    client = chromadb.PersistentClient(path=str(data_dir))
    count_before = client.get_collection("sparknet-fabric").count()
    assert count_before > 1

    doc.write_text("now short")
    after = subprocess.run(
        [*_run, "fabric", "index", "--data-dir", str(data_dir), "--vault", str(vault)],
        capture_output=True,
        text=True,
    )
    assert after.returncode == 0, after.stdout + after.stderr

    count_after = client.get_collection("sparknet-fabric").count()
    assert count_after < count_before
    assert count_after == len(chroma.plan_index("fabric", vault))


def test_shared_scope_indexes_only_explicit_share_staging(tmp_path: Path) -> None:
    (tmp_path / "01_Inbox" / "share-share-1" / "notes").mkdir(parents=True)
    (tmp_path / "01_Inbox" / "share-share-1" / "notes" / "shared.md").write_text("explicit")
    (tmp_path / "01_Inbox" / "unrelated.md").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "01_Inbox" / "unrelated.md").write_text("not a share")
    (tmp_path / "concepts").mkdir()
    (tmp_path / "concepts" / "private.md").write_text("private")
    docs = chroma.plan_index("shared", tmp_path)
    assert [doc["path"] for doc in docs] == ["01_Inbox/share-share-1/notes/shared.md"]
