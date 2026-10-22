#!/usr/bin/env python3
"""Optional local semantic index for a sparknet vault (port 4223's substrate).

The fabric contract reserves ``4223 vector-embed`` for the Master to host a
single shared vector store that the roles and their wiki skills query over the
overlay. That service is deliberately **not built** (``contracts/ports.json``
keeps 4223 ``spec-only``). This script is the piece that may be used *before*
that service exists, and on a host that will never host it: a local, optional
Chroma index of a vault's markdown, one collection per scope.

Three design rules, all enforced:

1. **chromadb is optional.** The runtime dependency allow-list is
   ``cryptography`` alone, and chromadb is a heavy package a node should not be
   forced to install. This module imports chromadb *lazily*, inside the
   functions that need it, with a clear install hint. Importing the module, or
   running ``inspect``, never touches chromadb — so the pure logic
   (discovery, deterministic chunking, doc ids, the corpus digest) is testable
   on a system that has never seen the package.
2. **Everything is deterministic.** ``inspect`` reproduces ids and chunks
   exactly across runs, so a re-index is idempotent (upsert by stable id) and
   a test can assert on the plan without chromadb being present.

And a third, added when the shared vector store (port 4223) was designed:

3. **The index carries a stamp, and a mismatch refuses.** The index is
   *derived state* — it can be rebuilt from the signed vault content — but a
   stale index served as if it were current is worse than no index, because
   every distance it returns would be meaningless while looking healthy. The
   collection therefore carries ``embedding_model``, ``embedding_sha256``,
   ``chroma_version`` and ``corpus_digest`` in its metadata. A query whose
   stamp does not match this build is **refused** (exit 3), never answered
   from a stale index.

   The embedder is named explicitly (``EMBEDDING_FUNCTION`` below) rather than
   taken from the library's default, because the default is fetched by the
   library and does not identify itself: on chromadb 1.5.x its ``name()`` is
   the constant ``"default"`` and on 0.6.x it has no ``name`` at all. Naming
   the class means a library upgrade that renames it fails loudly here and
   forces a reindex — which is the outcome the design wants — instead of
   silently swapping the model under a live index.

   The resolved model is **all-MiniLM-L6-v2** (ONNX, sha256
   ``913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3``),
   recorded here in the docstring of the reindex target as the design
   requires. Switching it requires a full reindex.

Scopes
~~~~~~

- ``peer``    -> index ``peer-node/``            (data in ``peer-node/.state/chroma/``)
- ``master``  -> index ``master-node/``          (data in ``master-node/.state/chroma/``)
- ``fabric``  -> index the **structural** tree the roles share: the fabric's
  root documents, the ``contracts/`` tree and the role charters, selected by
  the shared allow-list policy in ``scripts/sparknet-rag-corpus.py``
  (data in ``.state/chroma/``)

The role scopes index their own vault whole — a node's private index is its
own business. The ``fabric`` scope is the one served to every node over 4223,
so it is an **allow-list**: a deny-list requires someone to notice that a new
page is sensitive, an allow-list requires someone to notice that a new page is
safe, and only the second failure mode is survivable for a shared store. The
policy is loaded by path from ``scripts/sparknet-rag-corpus.py``, never copied
here: two copies of an allow-list are two answers to "what is safe to serve".

``.state/`` is gitignored at every level, so the index never enters a bundle
or a commit. The collection name is ``sparknet-<scope>``.

Usage::

    scripts/sparknet-chroma.py <scope> init              # create the collection
    scripts/sparknet-chroma.py <scope> inspect           # plan without chromadb
    scripts/sparknet-chroma.py <scope> index             # build the index
    scripts/sparknet-chroma.py <scope> stamp             # compare the index's stamp with this build
    scripts/sparknet-chroma.py <scope> query "text" [--top-k N] [--data-dir DIR]

Exit codes: 0 ok, 1 discovery/user error, 2 chromadb missing,
3 the index's stamp does not match this build (refused).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import re
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The embedding function the index is built and queried with, named explicitly.
#:
#: Chroma's *default* embedding function is fetched by the library and does not
#: identify itself — on chromadb 1.5.x its ``name()`` is the constant
#: ``"default"`` and on 0.6.x the instance has no ``name`` at all — so an
#: upgrade could change the model under a live index and every distance
#: returned afterwards would be meaningless while looking entirely healthy.
#: Naming the class here makes that failure loud instead: if a future chromadb
#: renames or drops it, the index cannot be built or queried until it is
#: reindexed against the new name, which is the outcome the design wants.
EMBEDDING_FUNCTION = "ONNXMiniLM_L6_V2"

#: Stamp fields whose disagreement means the stored vectors cannot be trusted:
#: a different model, different weights, or different content.
REFUSAL_FIELDS = ("embedding_model", "embedding_sha256", "corpus_digest")

#: Stamp fields that are reported but never refuse: a different chromadb
#: version changes the library, not the meaning of the vectors.
REPORT_FIELDS = ("chroma_version",)

#: File next to the index that records which chromadb version wrote it.
#:
#: It is a plain file rather than a field of the collection metadata because
#: the metadata cannot be read when the index is unreadable — which is the
#: case the marker exists to answer. An index whose marker is missing or names
#: another version is discarded and written again: the storage format belongs
#: to the library, and only the library that wrote it can read it.
VERSION_MARKER = ".sparknet-chroma-version"

#: Directories that are never vault content. Generated dirs, caches, the
#: vendored skills (not knowledge) and role trees that belong to another scope.
#:
#: For the ``fabric`` scope this is the *belt-and-braces* second list: the
#: shared allow-list policy in ``scripts/sparknet-rag-corpus.py`` is the
#: primary gate, and this one still catches what a policy change might let
#: through. For the role scopes it is the whole gate.
EXCLUDE_PARTS = {
    ".git",
    ".venv",
    ".state",
    ".cache",
    "__pycache__",
    ".opencode",
    "node_modules",
    "dist",
    ".pytest_cache",
    ".ruff_cache",
}

SCOPES = ("peer", "master", "fabric")
DEFAULT_MAX_CHARS = 2000


# --- scope resolution ---------------------------------------------------------


def resolve_scope(scope: str) -> tuple[str, Path, Path]:
    """Return ``(collection_name, vault_root, data_dir)`` for a scope.

    The choice to keep each scope's data inside its own vault's ``.state/``
    (rather than one shared location) matches how ``.env`` and the wiki
    categories already per-scope: a role subvault stands alone, so its index
    should travel with it and be invisible from the parent.
    """
    if scope not in SCOPES:
        raise ValueError(f"unknown scope {scope!r}; expected one of {', '.join(SCOPES)}")
    if scope == "peer":
        vault = REPO_ROOT / "peer-node"
    elif scope == "master":
        vault = REPO_ROOT / "master-node"
    else:
        vault = REPO_ROOT
    return f"sparknet-{scope}", vault, vault / ".state" / "chroma"


# --- discovery ----------------------------------------------------------------


_POLICY: Any = None


def _policy() -> Any:
    """Load the shared corpus policy by path, never a copy.

    The allow-list that decides what may be served to every node over 4223
    lives once, in ``scripts/sparknet-rag-corpus.py``. Loading it by path —
    the pattern ``master-node/services/sparknet-ledger.py:37`` already uses
    for ``shared/sparknet-authz.py`` — proves there is one policy. A second
    copy would be a second answer to "what is safe to serve", and the two
    would drift exactly where it matters.
    """
    global _POLICY
    if _POLICY is None:
        script = Path(__file__).resolve().parent / "sparknet-rag-corpus.py"
        spec = importlib.util.spec_from_file_location("sparknet_rag_corpus_policy", script)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load the corpus policy: {script}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        _POLICY = module
    return _POLICY


def iter_markdown(root: Path, *, allow_list: set[str] | None = None) -> Iterator[Path]:
    """Yield the vault-relative paths of the markdown files a scope indexes.

    ``allow_list=None`` walks the vault whole — the role scopes, whose index
    is private to the node that built it. A set of root file names applies the
    shared allow-list policy: the structural roots, the contract tree and the
    role charters survive, and the exclusion list always wins.

    The policy's own exclusions are consulted as well, not just the local
    ``EXCLUDE_PARTS``: a path the policy calls personal must not slip in
    through a root that happens to be allowed.
    """
    policy = _policy() if allow_list is not None else None
    for path in sorted(root.rglob("*.md")):  # sorted -> deterministic discovery
        rel = path.relative_to(root)
        if EXCLUDE_PARTS & set(rel.parts):
            continue
        if policy is not None:
            if policy.is_excluded(rel):
                continue
            if not policy.is_allowed(rel, allow_list):
                continue
        yield rel


# --- deterministic chunking ---------------------------------------------------


def chunk_text(text: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[str]:
    """Split markdown into deterministic chunks of roughly ``max_chars``.

    Blocks are paragraphs separated by blank lines. Blocks accumulate until the
    next one would overflow ``max_chars``, so a chunk is never split in the
    middle of a paragraph unless that paragraph alone is larger than the limit —
    in which case it is cut at the last sentence boundary before ``max_chars``
    (or flat at ``max_chars`` if the paragraph has no early sentence). The
    result is a pure function of the input: same text, same chunks.
    """
    text = text.replace("\r\n", "\n")
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text)]
    blocks = [b for b in blocks if b]
    chunks: list[str] = []
    current = ""
    for block in blocks:
        if current and len(current) + 1 + len(block) <= max_chars:
            current = f"{current}\n\n{block}"
            continue
        if current:
            chunks.append(current)
        while len(block) > max_chars:
            cut = block.rfind(". ", 0, max_chars)
            if cut < max_chars // 2:  # no usable sentence boundary early enough
                cut = max_chars
            chunks.append(block[:cut].strip())
            block = block[cut:].strip()
        current = block
    if current:
        chunks.append(current)
    return chunks


def plan_index(scope: str, vault: Path) -> list[dict[str, object]]:
    """List every doc that ``index`` would write, without touching chromadb.

    Each entry is ``{"id", "document", "path"}``. Stable ids make the index
    idempotent: re-running ``index`` upserts the same ids and never duplicates.

    The ``fabric`` scope is the shared store, so it is an allow-list; the role
    scopes index their own vault whole.
    """
    allow_list = _policy().FABRIC_ROOTS if scope == "fabric" else None
    docs: list[dict[str, object]] = []
    for rel in iter_markdown(vault, allow_list=allow_list):
        text = (vault / rel).read_text(encoding="utf-8", errors="replace")
        for i, chunk in enumerate(chunk_text(text)):
            docs.append(
                {
                    "id": f"{scope}:{rel}#{i}",
                    "document": chunk,
                    "path": str(rel),
                }
            )
    return docs


# --- the stamp ----------------------------------------------------------------


def corpus_digest(docs: list[dict[str, object]]) -> str:
    """A stable digest of the indexed content.

    The digest covers the doc ids *and* the chunk text, so editing a page
    changes it: an unchanged corpus produces the same digest on every run,
    and a changed one does not. It is a pure function of the plan, so it can
    be computed without chromadb — which is what lets ``inspect`` show an
    operator the digest the index would carry.
    """
    digest = hashlib.sha256()
    for entry in sorted(docs, key=lambda d: str(d["id"])):
        digest.update(str(entry["id"]).encode("utf-8"))
        digest.update(b"\x00")
        digest.update(str(entry["document"]).encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def stamp_mismatch(stamp: dict[str, Any], expected: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Compare a collection's stamp with the one this build expects.

    Returns ``(refusals, reports)``. A *refusal* is a field that is missing or
    disagrees: the stored vectors cannot be trusted, and serving them would
    return meaningless distances that look healthy. A *report* is a difference
    worth saying out loud that does not change the meaning of the vectors (the
    chromadb version).
    """
    refusals: list[str] = []
    reports: list[str] = []
    for field in REFUSAL_FIELDS:
        want = expected.get(field)
        have = stamp.get(field)
        if not have or not want:
            refusals.append(f"{field}: missing (index has {have!r}, this build expects {want!r})")
        elif want != have:
            refusals.append(f"{field}: index has {have!r}, this build expects {want!r}")
    for field in REPORT_FIELDS:
        want = expected.get(field)
        have = stamp.get(field)
        if want and have and want != have:
            reports.append(f"{field}: index has {have!r}, this build has {want!r}")
    return refusals, reports


# --- chromadb (lazy) ----------------------------------------------------------


class ChromadbMissing(RuntimeError):
    """The optional package is absent; the command cannot proceed."""


def _require() -> None:
    """Fail with exit code 2 and the install hint when chromadb is absent."""
    try:
        import chromadb  # type: ignore[import-not-found]  # noqa: F401 - presence is the probe
    except ImportError as exc:  # pragma: no cover - only reachable without the package
        print(
            "sparknet-chroma: chromadb is not installed. It is an OPTIONAL "
            "dependency (the runtime allow-list stays 'cryptography' only). "
            "Install it with:\n"
            "  make chroma-dev     (or: pip install 'chromadb>=0.5,<1')\n"
            f"({exc})",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


def embedding_identity() -> dict[str, str]:
    """The identity of the embedder this build would use.

    Reads the model name and the weights digest from the *named* embedding
    class. The digest is the precise identity: a library could ship the same
    model name with different weights, and that would invalidate every stored
    vector just as surely as a different model.
    """
    _require()
    import chromadb  # type: ignore[import-not-found]
    import chromadb.utils.embedding_functions as ef  # type: ignore[import-not-found]

    cls = getattr(ef, EMBEDDING_FUNCTION, None)
    if cls is None:
        print(
            f"sparknet-chroma: {EMBEDDING_FUNCTION} is not available in chromadb "
            f"{chromadb.__version__}. The embedder is named explicitly so that a "
            "library upgrade cannot silently change the model under a live index; "
            "if the class was renamed, point EMBEDDING_FUNCTION at the new name "
            "and reindex the collection.",
            file=sys.stderr,
        )
        raise SystemExit(3)
    return {
        "embedding_model": str(getattr(cls, "MODEL_NAME", EMBEDDING_FUNCTION)),
        "embedding_sha256": str(getattr(cls, "_MODEL_SHA256", "") or ""),
        "chroma_version": str(chromadb.__version__),
    }


def _embedding_function() -> Any:
    """An instance of the named embedding function."""
    _require()
    import chromadb.utils.embedding_functions as ef  # type: ignore[import-not-found]

    cls = getattr(ef, EMBEDDING_FUNCTION, None)
    if cls is None:
        embedding_identity()  # raises with the explanation
    return cls()


def expected_stamp(docs: list[dict[str, object]]) -> dict[str, str]:
    """The stamp this build would write for ``docs``."""
    return {**embedding_identity(), "corpus_digest": corpus_digest(docs)}


class _UnusableIndex(Exception):
    """The on-disk index cannot be read by this chromadb.

    The usual cause is a different library version: the storage format
    changed, and the failure surfaces as an unknown segment type rather than
    as a readable error. The index is derived state — the corpus in the vault
    is the source of truth — so the answer to an unreadable index is always
    to rebuild it, never to serve what is there.
    """


def _open_collection(scope: str, data_dir: Path, *, create: bool):
    """Open the scope's collection, with the named embedder attached.

    The embedder is passed on *every* open, not only at build time: Chroma
    embeds a query with the embedding function of the collection object it
    hands back, and the one the library attaches by default is not necessarily
    the one the index was stamped with. Passing it explicitly makes "the
    index-time and query-time embedder are the same one" true by construction.

    ``create=False`` never creates a collection. A query against a missing
    index must fail loudly, not return an empty result set: an empty result
    set is a sentence, and this tool must not be able to write one by accident.

    Raises ``_UnusableIndex`` when the collection cannot be opened or read —
    including when it was written by another chromadb version, which is a
    rebuild, not an error to hide behind a traceback.
    """
    _require()
    import chromadb  # type: ignore[import-not-found]

    try:
        client = chromadb.PersistentClient(path=str(data_dir))
        if create:
            return client.get_or_create_collection(name=f"sparknet-{scope}", embedding_function=_embedding_function())
        return client.get_collection(name=f"sparknet-{scope}", embedding_function=_embedding_function())
    except SystemExit:
        raise
    except Exception as exc:
        raise _UnusableIndex(str(exc)) from exc


def _no_usable_index(scope: str, data_dir: Path, exc: Exception) -> None:
    """Report an index that cannot be used, and exit 3.

    Exit 3 is the refusal code everywhere in this tool, so "there is no index
    I can trust" and "the index does not match this build" are the same
    answer to the caller: refuse, and say how to fix it.
    """
    sys.stdout.flush()
    print(
        f"sparknet-chroma: the '{scope}' index in {data_dir} cannot be used: {exc}\n"
        f"(it may not exist, or it may have been written by a different chromadb "
        f"version). The index is derived state — rebuild it with:\n"
        f"  scripts/sparknet-chroma.py {scope} index",
        file=sys.stderr,
    )
    raise SystemExit(3) from exc


def _reset_index(scope: str, data_dir: Path) -> None:
    """Remove an unusable index directory so it can be written again.

    Only the index lives in the scope's state directory (the peer's key store
    is a sibling under `.state/keys/`), so removing it loses derived state and
    nothing else.
    """
    shutil.rmtree(data_dir, ignore_errors=True)
    _data_dir(data_dir)


def _chromadb_version() -> str:
    """The chromadb version this build would use."""
    import chromadb  # type: ignore[import-not-found]

    return str(chromadb.__version__)


def _index_version(data_dir: Path) -> str | None:
    """The chromadb version that wrote the index, or None if it is unknown.

    Read from a plain file rather than from the collection's metadata on
    purpose: the metadata cannot be read when the index is unreadable, which
    is exactly the case this answers.
    """
    marker = data_dir / VERSION_MARKER
    if not marker.is_file():
        return None
    return marker.read_text(encoding="utf-8").strip() or None


def _write_index_version(data_dir: Path) -> None:
    """Record which chromadb version wrote this index."""
    (data_dir / VERSION_MARKER).write_text(f"{_chromadb_version()}\n", encoding="utf-8")


def _data_dir(path: Path) -> Path:
    """Create the scope's state dir at 0700.

    ``.state/`` at the vault roots is the peer's key store and must never loosen
    (``make keys-check`` fails if it is not 0700). The index inherits that
    rule: an index over signed vault content is local machine state, not
    something a stray umask should widen.
    """
    bare = str(path)
    if not os.path.isdir(bare):
        os.makedirs(bare, mode=0o700)
    os.chmod(bare, 0o700)
    return path


def cmd_init(scope: str, data_dir: Path) -> None:
    _data_dir(data_dir)
    try:
        collection = _open_collection(scope, data_dir, create=True)
    except _UnusableIndex:
        print(
            f"init: the existing index in {data_dir} cannot be read — rebuilding it",
            file=sys.stderr,
        )
        _reset_index(scope, data_dir)
        try:
            collection = _open_collection(scope, data_dir, create=True)
        except _UnusableIndex as exc:
            _no_usable_index(scope, data_dir, exc)
    print(f"init: collection '{collection.name}' ready in {data_dir}")


def cmd_inspect(scope: str, vault: Path) -> int:
    docs = plan_index(scope, vault)
    total_chars = sum(len(d["document"]) for d in docs)  # type: ignore[arg-type]
    print(f"inspect: scope={scope} path={vault}")
    print(f"  documents: {len(docs)}")
    print(f"  characters: {total_chars}")
    print(f"  corpus_digest: {corpus_digest(docs)}")
    for entry in docs[:20]:
        print(f"  {entry['id']}  ({len(entry['document'])} chars)")
    if len(docs) > 20:
        print(f"  ... and {len(docs) - 20} more")
    return 0


def cmd_index(scope: str, vault: Path, data_dir: Path) -> None:
    """Build (or rebuild) the scope's index, and stamp it.

    The index is derived state — the corpus in the vault is the source of
    truth — so this command makes the collection *equal* the corpus rather
    than patching it: chunks that are no longer in the corpus are removed, so
    a query can never return a passage the corpus does not contain.

    An index written by another chromadb version cannot be read by this one:
    the storage format differs, and the failure surfaces as an unknown segment
    type rather than as a readable error. So the version that wrote the index
    is recorded next to it, and an index whose provenance is unknown or does
    not match this build is discarded and written again — *before* any client
    opens it, because chroma caches its storage system per path and a cached
    system would hand back the very state we just deleted.
    """
    docs = plan_index(scope, vault)
    _data_dir(data_dir)
    written = _index_version(data_dir)
    current = _chromadb_version()
    if written != current:
        reason = (
            "its provenance is unknown (no version marker)"
            if written is None
            else f"it was written by chromadb {written}, this build has {current}"
        )
        print(
            f"index: {data_dir} is not this build's index — {reason} — rebuilding it from source",
            file=sys.stderr,
        )
        _reset_index(scope, data_dir)
    try:
        _write_index(scope, data_dir, docs)
    except _UnusableIndex as exc:
        _no_usable_index(scope, data_dir, exc)
    _write_index_version(data_dir)
    stamp = expected_stamp(docs)
    print(f"index: upserted {len(docs)} chunks into '{scope}'")
    print(f"index: stamped {stamp['embedding_model']} / {stamp['chroma_version']} / {stamp['corpus_digest'][:12]}")


def _write_index(scope: str, data_dir: Path, docs: list[dict[str, object]]) -> None:
    """Upsert the corpus, drop what is no longer in it, and stamp it.

    Raises ``_UnusableIndex`` when the collection cannot be read or written.
    """
    collection = _open_collection(scope, data_dir, create=True)
    ids = [str(d["id"]) for d in docs]
    try:
        collection.upsert(
            ids=ids,
            documents=[str(d["document"]) for d in docs],
            metadatas=[{"path": d["path"]} for d in docs],
        )
        stale = set(collection.get(include=["metadatas"])["ids"]) - set(ids)
        if stale:
            collection.delete(ids=sorted(stale))
        collection.modify(metadata=expected_stamp(docs))
    except Exception as exc:
        raise _UnusableIndex(str(exc)) from exc


def cmd_stamp(scope: str, vault: Path, data_dir: Path) -> int:
    """Show the index's stamp and whether it matches this build."""
    docs = plan_index(scope, vault)
    expected = expected_stamp(docs)
    try:
        collection = _open_collection(scope, data_dir, create=False)
        stamp = dict(collection.metadata or {})
    except _UnusableIndex as exc:
        _no_usable_index(scope, data_dir, exc)
    refusals, reports = stamp_mismatch(stamp, expected)
    print(f"stamp: collection '{collection.name}' in {data_dir}")
    for field in (*REFUSAL_FIELDS, *REPORT_FIELDS):
        print(f"  {field}: index={stamp.get(field)!r} build={expected.get(field)!r}")
    for report in reports:
        print(f"  note: {report}")
    if refusals:
        sys.stdout.flush()
        print("stamp: MISMATCH — this index must not be served:", file=sys.stderr)
        for refusal in refusals:
            print(f"  {refusal}", file=sys.stderr)
        print(f"  reindex it: scripts/sparknet-chroma.py {scope} index", file=sys.stderr)
        return 3
    print("stamp: match")
    return 0


def cmd_query(scope: str, vault: Path, data_dir: Path, query: str, top_k: int) -> int:
    docs = plan_index(scope, vault)
    expected = expected_stamp(docs)
    try:
        collection = _open_collection(scope, data_dir, create=False)
        stamp = dict(collection.metadata or {})
    except _UnusableIndex as exc:
        _no_usable_index(scope, data_dir, exc)
    refusals, reports = stamp_mismatch(stamp, expected)
    for report in reports:
        print(f"query: note: {report}")
    if refusals:
        sys.stdout.flush()
        print(
            "query: REFUSED — the index's stamp does not match this build, so its distances cannot be trusted:",
            file=sys.stderr,
        )
        for refusal in refusals:
            print(f"  {refusal}", file=sys.stderr)
        print(f"  reindex it: scripts/sparknet-chroma.py {scope} index", file=sys.stderr)
        return 3
    try:
        result = collection.query(query_texts=[query], n_results=top_k)
    except Exception as exc:
        _no_usable_index(scope, data_dir, exc)
    ids = result.get("ids", [[]])[0]
    distances = result.get("distances", [[]])[0]
    docs_found = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    if not ids:
        print(f"query: no results for {query!r} in '{collection.name}'")
        return 0
    print(f"query: top {len(ids)} results in '{collection.name}'")
    for i, doc_id in enumerate(ids):
        score = distances[i] if i < len(distances) else None
        meta = metadatas[i] if i < len(metadatas) else {}
        path = meta.get("path", doc_id) if isinstance(meta, dict) else doc_id
        text = docs_found[i] if i < len(docs_found) else ""
        snippet = " ".join(str(text).split())[:160]
        print(f"  [{i + 1}] {path}  (dist={score:.4f})" if score is not None else f"  [{i + 1}] {path}")
        print(f"      {snippet}")
    return 0


# --- CLI ---------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="sparknet - local Chroma index (optional; 4223 stays spec-only)")
    p.add_argument("scope", choices=SCOPES, help="which vault to index")
    p.add_argument(
        "command",
        choices=("init", "inspect", "index", "stamp", "query"),
        help=(
            "init=create collection; inspect=plan without chromadb; index=build; "
            "stamp=compare the index's stamp with this build; query=search"
        ),
    )
    p.add_argument("query_text", nargs="?", default="", help="search text for 'query'")
    p.add_argument("--top-k", type=int, default=5, help="results to return (default 5)")
    p.add_argument(
        "--data-dir",
        default=None,
        help="override the scope's default .state/chroma location (tests use this)",
    )
    p.add_argument(
        "--vault",
        default=None,
        help=(
            "override the scope's vault root (the scope still decides the policy: "
            "'fabric' stays an allow-list, a role scope stays whole-vault)"
        ),
    )
    args = p.parse_args(argv)
    try:
        _collection_name, vault, default_data = resolve_scope(args.scope)
    except ValueError as exc:
        print(f"sparknet-chroma: {exc}", file=sys.stderr)
        return 1
    if args.vault:
        vault = Path(args.vault).expanduser()
    data_dir = Path(args.data_dir) if args.data_dir else default_data

    if args.command == "init":
        cmd_init(args.scope, data_dir)
        return 0
    if args.command == "inspect":
        return cmd_inspect(args.scope, vault)
    if args.command == "index":
        cmd_index(args.scope, vault, data_dir)
        return 0
    if args.command == "stamp":
        return cmd_stamp(args.scope, vault, data_dir)
    if not args.query_text:
        print("sparknet-chroma: 'query' needs text", file=sys.stderr)
        p.print_usage(file=sys.stderr)
        return 1
    return cmd_query(args.scope, vault, data_dir, args.query_text, args.top_k)


if __name__ == "__main__":
    sys.exit(main())
