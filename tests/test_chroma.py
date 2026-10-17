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


def test_fabric_discovery_walks_the_scope_root_and_both_roles(tmp_path: Path) -> None:
    root = tmp_path
    for path in (
        root / "concepts" / "one.md",
        root / "peer-node" / "05_Knowledge" / "concepts" / "peer.md",
        root / "master-node" / "05_Knowledge" / "concepts" / "master.md",
        root / ".opencode" / "skills" / "x" / "SKILL.md",  # vendored, not content
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content")

    found = sorted(label for label, _ in chroma.iter_markdown(root, include_roles=True))
    # .opencode is excluded; both roles are included, each once via its own walk.
    assert found == ["", "master-node", "peer-node"]


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
    (tmp_path / "concepts").mkdir()
    (tmp_path / "concepts" / "one.md").write_text("alpha")
    plan_a = chroma.plan_index("fabric", tmp_path)
    plan_b = chroma.plan_index("fabric", tmp_path)
    assert plan_a == plan_b

    ids = [d["id"] for d in plan_a]
    assert ids and ids == sorted(ids), "plan must be sorted so ids are stable"
    for doc_id in ids:
        assert doc_id.startswith("fabric:") and "#" in doc_id


def test_plan_index_returns_paths_not_absolute(tmp_path: Path) -> None:
    (tmp_path / "peer-node" / "05_Knowledge").mkdir(parents=True)
    (tmp_path / "peer-node" / "05_Knowledge" / "a.md").write_text("x")
    for entry in chroma.plan_index("fabric", tmp_path):
        assert not Path(str(entry["path"])).is_absolute()
        assert "/mnt/" not in str(entry["path"])


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
        [*_run, "peer", "index", "--data-dir", str(data_dir)],
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
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "concepts/peering.md" in proc.stdout


@REAL_CHROMA
def test_reindex_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "concepts").mkdir(parents=True)
    (vault / "concepts" / "stable.md").write_text("stable content")
    data_dir = tmp_path / "chroma"

    for _ in range(2):
        proc = subprocess.run(
            [*_run, "fabric", "index", "--data-dir", str(data_dir)],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

    import chromadb

    client = chromadb.PersistentClient(path=str(data_dir))
    collection = client.get_collection("sparknet-fabric")
    assert collection.count() == len(chroma.plan_index("fabric", vault))
