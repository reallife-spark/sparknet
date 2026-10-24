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
    scripts/sparknet-chroma.py <scope> query "text" --reflex shadow|assist

Exit codes: 0 ok, 1 discovery/user error, 2 chromadb missing,
3 the index's stamp does not match this build (refused).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import re
import shutil
import sys
import time
import urllib.request
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

#: The RAG reflex pilot (Step 64E) reranks the Chroma candidates locally. The
#: upstream design names ``bge-reranker-v2-m3``; that model is already in the
#: node stack behind ``SPARKNET_RERANK_URL``. When that URL is unset (the CLI's
#: default, and every unit test), a deterministic lexical reranker stands in:
#: it is offline, free, and its scores are reproducible. The HTTP reranker is
#: an *option* on the same seam, never a requirement.
_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "of",
        "to",
        "and",
        "or",
        "in",
        "on",
        "for",
        "is",
        "are",
        "be",
        "with",
        "from",
        "by",
        "as",
        "at",
        "this",
        "that",
        "it",
        "its",
        "was",
        "were",
        "which",
        "who",
        "whom",
        "what",
        "when",
        "where",
        "why",
        "how",
    ]
)


def _tokens(text: str) -> set[str]:
    """Lower-cased content tokens, used by the offline reranker."""
    return {tok for tok in _TOKEN_RE.findall(text.lower()) if len(tok) > 2 and tok not in _STOPWORDS}


def lexical_relevance(query: str, text: str) -> float:
    """How much of the query the passage covers, in ``[0, 1]``.

    Coverage (not Jaccard) is the right bias for retrieval: a long chunk that
    contains every query term should beat a short chunk that contains half of
    them. The score is deliberately simple and deterministic so the pilot's
    measurements are reproducible without a model download.
    """
    wanted = _tokens(query)
    if not wanted:
        return 0.0
    return len(wanted & _tokens(text)) / len(wanted)


def _distance(candidate: dict[str, Any]) -> float:
    """Chroma distance for stable tie-breaking; infinite when absent."""
    value = candidate.get("distance")
    return float(value) if isinstance(value, (int, float)) else float("inf")


def _normalised(scores: list[float]) -> list[float] | None:
    """Min-max scores, or ``None`` when all values are equal (no signal)."""
    if not scores:
        return None
    low, high = min(scores), max(scores)
    if high <= low:
        return None
    return [(score - low) / (high - low) for score in scores]


def _rerank_url() -> str | None:
    """The operator-configured local reranker endpoint, if any."""
    url = os.environ.get("SPARKNET_RERANK_URL", "").strip()
    if not url.startswith(("http://", "https://")):
        return None
    return url


def http_rerank_scores(query: str, documents: list[str]) -> list[float] | None:
    """Ask the node's local reranker for scores; ``None`` on any failure.

    The endpoint is opt-in via ``SPARKNET_RERANK_URL`` and must answer with
    ``{"scores": [...]}`` in the same order as ``documents``. A timeout, a
    malformed body or a non-2xx response falls back to the lexical reranker —
    the reflex path is fail-open by contract, and the CLI must never fail a
    query because an optional reranker is down.
    """
    url = _rerank_url()
    if url is None or not documents:
        return None
    body = json.dumps({"query": query, "documents": documents}).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    timeout = float(os.environ.get("SPARKNET_RERANK_TIMEOUT", "2.0"))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, TimeoutError):
        return None
    scores = payload.get("scores") if isinstance(payload, dict) else None
    if not isinstance(scores, list) or len(scores) != len(documents):
        return None
    if not all(isinstance(score, (int, float)) and not isinstance(score, bool) for score in scores):
        return None
    return [float(score) for score in scores]


def rerank_candidates(query: str, candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], bool, str, float]:
    """Order candidates by local relevance.

    Returns ``(ordered, abstained, backend, latency_ms)``. ``abstained`` means
    the local signal was empty (no lexical overlap and no reranker scores), in
    which case the caller must keep the Chroma order. The contract's
    fail-open rule is implemented here, not by every caller.
    """
    if not candidates:
        return [], True, "rules", 0.0
    started = time.perf_counter()
    documents = [str(candidate.get("document", "")) for candidate in candidates]
    lexical = [lexical_relevance(query, document) for document in documents]
    backend = "rules"
    scores = lexical
    signal = max(lexical, default=0.0)
    remote = http_rerank_scores(query, documents)
    normalised = _normalised(remote) if remote is not None else None
    if normalised is not None:
        scores = [0.7 * model + 0.3 * rule for model, rule in zip(normalised, lexical, strict=True)]
        backend = "http-rerank"
        signal = max(normalised)
    else:
        # Without a model, trust the embedding and let lexical overlap nudge
        # ties. A pure lexical reorder measurably loses precision on the
        # fabric golden set, so the rules backend is deliberately conservative.
        closeness = _distance_scores(candidates)
        scores = [0.9 * distance + 0.1 * rule for distance, rule in zip(closeness, lexical, strict=True)]
    abstained = signal <= 0.0
    order = sorted(
        range(len(candidates)),
        key=lambda i: (-scores[i], _distance(candidates[i]), str(candidates[i].get("id", ""))),
    )
    ordered = [{**candidates[i], "reflex_score": round(scores[i], 6)} for i in order]
    return ordered, abstained, backend, (time.perf_counter() - started) * 1000


def _distance_scores(candidates: list[dict[str, Any]]) -> list[float]:
    """Min-max Chroma closeness, with missing/infinite distances neutralised."""
    distances = [_distance(candidate) for candidate in candidates]
    finite = [value for value in distances if math.isfinite(value)]
    if not finite:
        return [0.0] * len(candidates)
    ceiling = max(finite)
    safe = [-value if math.isfinite(value) else -ceiling for value in distances]
    return _normalised(safe) or [0.0] * len(candidates)


REFLEX_CACHE_VERSION = "rag-relevance-v1"
REFLEX_CACHE_LIMIT = 256


def _reflex_cache_path(data_dir: Path) -> Path:
    """The cache lives beside the index (``.state/reflex-cache.json``)."""
    return data_dir.parent / "reflex-cache.json"


def _cache_key(query: str, candidates: list[dict[str, Any]]) -> str:
    """Cache key: query + candidate ids + policy version, never the model output."""
    payload = json.dumps(
        {
            "query": query,
            "ids": [candidate.get("id") for candidate in candidates],
            "policy": REFLEX_CACHE_VERSION,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _cache_write(path: Path, cache: dict[str, Any]) -> None:
    if len(cache) > REFLEX_CACHE_LIMIT:
        cache = dict(list(cache.items())[-REFLEX_CACHE_LIMIT:])
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(cache, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def cached_rerank(
    query: str,
    candidates: list[dict[str, Any]],
    data_dir: Path,
    *,
    use_cache: bool = True,
) -> tuple[list[dict[str, Any]], bool, str, float, bool]:
    """``rerank_candidates`` with a bounded on-disk cache.

    Returns ``(ordered, abstained, backend, latency_ms, cached)``. The cache is
    keyed by the query, the candidate ids and the policy version, so a changed
    corpus, candidate set or policy never reuses a stale ordering. Cache writes
    are atomic; a corrupt or unreadable cache is ignored, never fatal.
    """
    if not candidates:
        return [], True, "rules", 0.0, False
    path = _reflex_cache_path(data_dir)
    cache = _cache_read(path) if use_cache else {}
    key = _cache_key(query, candidates)
    entry = cache.get(key)
    if isinstance(entry, dict) and isinstance(entry.get("order"), list):
        by_id = {candidate.get("id"): candidate for candidate in candidates}
        ordered: list[dict[str, Any]] = []
        for item in entry["order"]:
            candidate = by_id.get(item.get("id")) if isinstance(item, dict) else None
            if candidate is None:
                ordered = []
                break
            ordered.append({**candidate, "reflex_score": item.get("score")})
        if len(ordered) == len(candidates) and isinstance(entry.get("abstained"), bool):
            return ordered, entry["abstained"], str(entry.get("backend", "rules")), 0.0, True
    ordered, abstained, backend, latency_ms = rerank_candidates(query, candidates)
    if use_cache:
        cache[key] = {
            "abstained": abstained,
            "backend": backend,
            "order": [{"id": candidate.get("id"), "score": candidate.get("reflex_score")} for candidate in ordered],
        }
        _cache_write(path, cache)
    return ordered, abstained, backend, latency_ms, False


def order_overlap(left: list[str], right: list[str]) -> float:
    """Jaccard overlap of two result lists, for shadow agreement."""
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(set(left) & set(right)) / len(set(left) | set(right))


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


def open_checked(scope: str, vault: Path, data_dir: Path, *, log_prefix: str = "query"):
    """Open a collection whose stamp matches this build, or exit 3.

    Query and evaluation must refuse the same stale index, so the check lives
    here once instead of in each caller.
    """
    docs = plan_index(scope, vault)
    expected = expected_stamp(docs)
    try:
        collection = _open_collection(scope, data_dir, create=False)
        stamp = dict(collection.metadata or {})
    except _UnusableIndex as exc:
        _no_usable_index(scope, data_dir, exc)
    refusals, reports = stamp_mismatch(stamp, expected)
    for report in reports:
        print(f"{log_prefix}: note: {report}")
    if refusals:
        sys.stdout.flush()
        print(
            f"{log_prefix}: REFUSED — the index's stamp does not match this build, so its distances cannot be trusted:",
            file=sys.stderr,
        )
        for refusal in refusals:
            print(f"  {refusal}", file=sys.stderr)
        print(f"  reindex it: scripts/sparknet-chroma.py {scope} index", file=sys.stderr)
        raise SystemExit(3)
    return collection


def query_candidates(scope: str, data_dir: Path, collection, query: str, n_results: int) -> list[dict[str, Any]]:
    """The Chroma candidates, in distance order, as plain dictionaries."""
    try:
        result = collection.query(query_texts=[query], n_results=n_results)
    except Exception as exc:
        _no_usable_index(scope, data_dir, exc)
    ids = result.get("ids", [[]])[0]
    distances = result.get("distances", [[]])[0]
    documents = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    candidates: list[dict[str, Any]] = []
    for i, doc_id in enumerate(ids):
        meta = metadatas[i] if i < len(metadatas) else {}
        candidates.append(
            {
                "id": doc_id,
                "path": meta.get("path", doc_id) if isinstance(meta, dict) else doc_id,
                "document": documents[i] if i < len(documents) else "",
                "distance": distances[i] if i < len(distances) else None,
            }
        )
    return candidates


def cmd_query(
    scope: str,
    vault: Path,
    data_dir: Path,
    query: str,
    top_k: int,
    reflex: str = "off",
    candidate_k: int = 50,
    reflex_top_k: int | None = None,
    reflex_json: bool = False,
    use_cache: bool = True,
) -> int:
    collection = open_checked(scope, vault, data_dir)
    depth = candidate_k if reflex != "off" else top_k
    candidates = query_candidates(scope, data_dir, collection, query, depth)
    if not candidates:
        print(f"query: no results for {query!r} in '{collection.name}'")
        return 0
    baseline = candidates[:top_k]
    shown = baseline
    if reflex != "off":
        ordered, abstained, backend, latency_ms, cached = cached_rerank(
            query, candidates, data_dir, use_cache=use_cache
        )
        keep = reflex_top_k or top_k
        reflex_order = ordered[:keep]
        agreement = order_overlap([c["path"] for c in baseline], [c["path"] for c in reflex_order])
        if reflex == "assist" and not abstained:
            shown = reflex_order
        print(
            f"query: reflex={reflex} backend={backend} abstain={str(abstained).lower()} "
            f"agreement={agreement:.3f} latency_ms={latency_ms:.3f} cached={str(cached).lower()}"
        )
        if reflex_json:
            payload = {
                "agreement": round(agreement, 6),
                "backend": backend,
                "cached": cached,
                "candidate_k": depth,
                "latency_ms": round(latency_ms, 6),
                "mode": reflex,
                "paths": [c["path"] for c in shown],
                "query": query,
                "reflex_abstained": abstained,
                "top_k": top_k,
            }
            print("reflex-json: " + json.dumps(payload, sort_keys=True))
    print(f"query: top {len(shown)} results in '{collection.name}'")
    for i, candidate in enumerate(shown):
        score = candidate.get("distance")
        path = candidate.get("path", candidate.get("id"))
        text = candidate.get("document", "")
        snippet = " ".join(str(text).split())[:160]
        print(f"  [{i + 1}] {path}  (dist={score:.4f})" if isinstance(score, float) else f"  [{i + 1}] {path}")
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
        "--reflex",
        nargs="?",
        const="shadow",
        choices=("off", "shadow", "assist"),
        default="off",
        help=(
            "rerank Chroma's candidates locally: shadow=log only (default when the flag "
            "is bare); assist=return the reranked order unless the reflex abstains"
        ),
    )
    p.add_argument("--candidate-k", type=int, default=50, help="candidates fetched before reranking (default 50)")
    p.add_argument(
        "--reflex-top-k",
        type=int,
        default=None,
        help="results kept after reranking (default: --top-k)",
    )
    p.add_argument("--reflex-json", action="store_true", help="print one machine-readable reflex line")
    p.add_argument("--no-reflex-cache", action="store_true", help="bypass the on-disk reflex ordering cache")
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
    return cmd_query(
        args.scope,
        vault,
        data_dir,
        args.query_text,
        args.top_k,
        args.reflex,
        args.candidate_k,
        args.reflex_top_k,
        args.reflex_json,
        not args.no_reflex_cache,
    )


if __name__ == "__main__":
    sys.exit(main())
