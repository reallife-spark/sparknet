#!/usr/bin/env python3
"""Optional local Qdrant index for a sparknet vault (port 4223's substrate).

The fabric reserves ``4223 vector-embed`` for the Master-hosted shared vector
store. This script builds the same collections locally and is the one
chunking/embedding/stamping implementation the 4223 service loads by path.

Three design rules, all enforced:

1. **Qdrant is optional.** The runtime dependency allow-list is
   ``cryptography`` alone, and the Qdrant client is imported lazily inside the
   functions that need it. Importing this module, or running ``inspect``, never
   touches Qdrant — so the pure logic (discovery, deterministic chunking, doc
   ids, the corpus digest) is testable on a system that has never seen it.
2. **Everything is deterministic.** ``inspect`` reproduces ids and chunks
   exactly across runs, so a re-index is an idempotent upsert by stable point id
   and a test can assert on the plan without Qdrant being present.
3. **The index carries a stamp, and a mismatch refuses.** The index is derived
   state — it can be rebuilt from signed vault content — but a stale index
   served as current is worse than no index: every distance it returns would be
   meaningless while looking healthy. The stamp lives in ``sparknet-meta`` and
   records ``embedding_model``, ``embedding_sha256``, ``embedding_backend``,
   ``embedding_dim``, ``corpus_digest`` and ``qdrant_version``. A query whose
   stamp does not match this build is refused (exit 3; 503 on 4223).

Scopes
~~~~~~

- ``peer``    -> ``peer-node/``            (local data ``peer-node/.state/qdrant/``)
- ``master``  -> ``master-node/``          (local data ``master-node/.state/qdrant/``)
- ``fabric``  -> the structural tree: root documents, ``contracts/`` and role
  charters, selected by the shared policy in ``scripts/sparknet-rag-corpus.py``
- ``shared``  -> only ``01_Inbox/share-*`` markdown payloads

The role scopes index their own vault whole. The ``fabric`` scope is served to
every node over 4223, so it is an allow-list; the policy is loaded by path from
``scripts/sparknet-rag-corpus.py``, never copied. ``shared`` is privacy model A:
only an explicitly accepted share reaches it.

The production store is a Qdrant server on node loopback. Passing ``--data-dir``
with no ``SPARKNET_QDRANT_URL`` opens Qdrant's embedded mode for tests and an
isolated operator run; embedded mode takes an exclusive lock, so it is not the
deployment shape.

Usage::

    scripts/sparknet-vector.py <scope> init              # create the collection
    scripts/sparknet-vector.py <scope> inspect           # plan without Qdrant
    scripts/sparknet-vector.py <scope> index             # build the index
    scripts/sparknet-vector.py <scope> stamp             # compare stamp with this build
    scripts/sparknet-vector.py <scope> query "text" [--top-k N] [--data-dir DIR]
    scripts/sparknet-vector.py <scope> query "text" --reflex shadow|assist

Exit codes: 0 ok, 1 discovery/user error, 2 qdrant-client missing,
3 the index's stamp does not match this build (refused).
"""

from __future__ import annotations

import argparse
import contextlib
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
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Stamp fields whose disagreement means the stored vectors cannot be trusted:
#: a different model, different weights, or different content.
REFUSAL_FIELDS = ("embedding_model", "embedding_sha256", "embedding_dim", "corpus_digest")

#: The RAG reflex pilot (Step 64E) reranks the Qdrant candidates locally. The
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
    """Vector distance for stable tie-breaking; infinite when absent."""
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
    which case the caller must keep the Qdrant order. The contract's
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
    """Min-max vector closeness, with missing/infinite distances neutralised."""
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


#: Stamp fields that are reported but never refuse.
REPORT_FIELDS = ("embedding_backend", "qdrant_version")

#: File next to a local embedded index that records which Qdrant version wrote
#: it. Server stamps are in ``sparknet-meta``; this marker makes an unreadable
#: embedded path rebuildable without reading the collection first.
VERSION_MARKER = ".sparknet-qdrant-version"

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

SCOPES = ("peer", "master", "fabric", "shared")
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
    elif scope == "shared":
        vault = REPO_ROOT / "master-node"
        return "sparknet-shared", vault, vault / ".state" / "qdrant-shared"
    else:
        vault = REPO_ROOT
    return f"sparknet-{scope}", vault, vault / ".state" / "qdrant"


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


def _shared_docs(vault: Path) -> list[dict[str, object]]:
    """Only markdown payloads an accepted share staged under 01_Inbox/share-*.

    Privacy model A: an explicit share is the only way a page reaches the
    Master's shared collection. The ordinary fabric allow-list is not used
    here, because it excludes 01_Inbox by design; this narrower rule admits a
    path only when its first two parts are exactly the share staging shape.
    """
    docs: list[dict[str, object]] = []
    for path in sorted(vault.glob("01_Inbox/share-*/**/*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(vault)
        if len(relative.parts) < 4 or relative.parts[0] != "01_Inbox" or not relative.parts[1].startswith("share-"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for index, chunk in enumerate(chunk_text(text)):
            docs.append({"id": f"shared:{relative}#{index}", "document": chunk, "path": str(relative)})
    return docs


def plan_index(scope: str, vault: Path) -> list[dict[str, object]]:
    """List every doc that ``index`` would write, without touching Qdrant.

    Each entry is ``{"id", "document", "path"}``. Stable ids make the index
    idempotent: re-running ``index`` upserts the same ids and never duplicates.

    The ``fabric`` scope is the shared store, so it is an allow-list; the role
    scopes index their own vault whole.
    """
    if scope == "shared":
        return _shared_docs(vault)
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
    be computed without Qdrant — which is what lets ``inspect`` show an
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
    Qdrant version).
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


# --- qdrant (lazy) ------------------------------------------------------------
#
# Qdrant is the runtime backend, but it is still an OPTIONAL dependency: the
# runtime allow-list is ``cryptography`` alone, and a node that only runs
# ``inspect`` must not need qdrant-client or fastembed. The package is imported
# inside the functions that use it, and the pure plan/chunk logic above stays
# importable on a host that has never installed it.
#
# The production store is a Qdrant server bound to node loopback. Tests and an
# isolated operator run may use Qdrant's embedded mode by passing --data-dir
# (or --path); when SPARKNET_QDRANT_URL is set the server wins. Qdrant's
# embedded mode takes an exclusive lock on the path, which is why it is a test
# and recovery surface, not the deployment shape.


class QdrantMissing(RuntimeError):
    """The optional package is absent; the command cannot proceed."""


def _require() -> None:
    """Fail with exit code 2 and the install hint when qdrant-client is absent."""
    try:
        import qdrant_client  # type: ignore[import-not-found]  # noqa: F401 - presence is the probe
    except ImportError as exc:  # pragma: no cover - only reachable without the package
        print(
            "sparknet-vector: qdrant-client is not installed. It is an OPTIONAL "
            "dependency (the runtime allow-list stays 'cryptography' only). "
            "Install it with:\n"
            "  make vector-dev     (or: pip install 'qdrant-client[fastembed]>=1.12,<2')\n"
            f"({exc})",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


def _qdrant_url() -> str:
    return os.environ.get("SPARKNET_QDRANT_URL", "").strip() or "http://127.0.0.1:6333"


def _api_key() -> str | None:
    value = os.environ.get("SPARKNET_QDRANT_API_KEY", "").strip()
    return value or None


def _use_local(data_dir: Path | None) -> bool:
    """Choose embedded Qdrant only when no server URL was explicitly supplied."""
    return bool(data_dir) and not os.environ.get("SPARKNET_QDRANT_URL", "").strip()


def _client(data_dir: Path | None = None, *, path: Path | None = None):
    """Open a Qdrant client: embedded path for tests, server by default."""
    _require()
    from qdrant_client import QdrantClient  # type: ignore[import-not-found]

    if path is not None:
        return QdrantClient(path=str(path))
    explicit_path = os.environ.get("SPARKNET_QDRANT_PATH", "").strip()
    if explicit_path:
        return QdrantClient(path=explicit_path)
    if _use_local(data_dir):
        if data_dir is None:
            raise RuntimeError("embedded Qdrant needs a data directory")
        _data_dir(data_dir)
        return QdrantClient(path=str(data_dir))
    return QdrantClient(url=_qdrant_url(), api_key=_api_key(), timeout=30.0)


def _qdrant_version(client: Any) -> str:
    try:
        version = getattr(client.info(), "version", None)
        return str(version) if version else "unknown"
    except Exception:
        return "unknown"


META_COLLECTION = "sparknet-meta"
META_NAMESPACE = uuid.UUID("c3a7bb6e-4f6d-5d8e-9b8a-2b4f2f5b9c11")


def _meta_point_id(scope: str) -> str:
    return str(uuid.uuid5(META_NAMESPACE, f"meta:{scope}"))


def point_id(doc_id: str) -> str:
    """A stable Qdrant point id for the human-readable corpus doc id."""
    return str(uuid.uuid5(META_NAMESPACE, f"doc:{doc_id}"))


def _ensure_meta(client: Any) -> None:
    from qdrant_client import models  # type: ignore[import-not-found]

    if client.collection_exists(META_COLLECTION):
        return
    client.create_collection(
        collection_name=META_COLLECTION,
        vectors_config=models.VectorParams(size=1, distance=models.Distance.COSINE),
    )


def _read_stamp(client: Any, scope: str) -> dict[str, Any] | None:
    try:
        if not client.collection_exists(META_COLLECTION):
            return None
        points = client.retrieve(
            collection_name=META_COLLECTION,
            ids=[_meta_point_id(scope)],
            with_payload=True,
            with_vectors=False,
        )
    except Exception:
        return None
    if not points:
        return None
    payload = getattr(points[0], "payload", None)
    return dict(payload) if isinstance(payload, dict) else None


def _write_stamp(client: Any, scope: str, stamp: dict[str, Any]) -> None:
    from qdrant_client import models  # type: ignore[import-not-found]

    _ensure_meta(client)
    client.upsert(
        collection_name=META_COLLECTION,
        points=[
            models.PointStruct(
                id=_meta_point_id(scope),
                vector=[0.0],
                payload=dict(stamp),
            )
        ],
        wait=True,
    )


def _collection_dim() -> int:
    raw = os.environ.get("SPARKNET_EMBED_DIM", "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError as exc:
            raise SystemExit(f"sparknet-vector: SPARKNET_EMBED_DIM is not an integer: {raw!r}") from exc
        if value <= 0:
            raise SystemExit("sparknet-vector: SPARKNET_EMBED_DIM must be positive")
        return value
    return 384


def _embedding_backend() -> str:
    explicit = os.environ.get("SPARKNET_EMBED_BACKEND", "").strip().lower()
    if explicit:
        return explicit
    if os.environ.get("SPARKNET_EMBED_URL", "").strip():
        return "http"
    return "fastembed"


def embedding_identity() -> dict[str, str]:
    """The identity of the embedder this build would use.

    The model name plus a logical weights digest are inside the stamp. The
    digest is deliberately over the *named model identity*, not the library's
    cache path: Qdrant's FastEmbed download layout is an implementation detail,
    while the model name is what a reindex must be pinned to. An operator who
    swaps the weights behind the same name must set SPARKNET_EMBED_SHA256, and
    the stamp will then refuse the old index.
    """
    backend = _embedding_backend()
    model = os.environ.get("SPARKNET_EMBED_MODEL", "").strip()
    if backend == "hash":
        model = model or "sparknet-hash-384"
        digest = hashlib.sha256(f"hash:{model}:{_collection_dim()}".encode()).hexdigest()
    elif backend == "http":
        model = model or "sentence-transformers/all-MiniLM-L6-v2"
        digest = hashlib.sha256(f"http:{_qdrant_url()}:{model}".encode()).hexdigest()
    elif backend == "fastembed":
        model = model or "sentence-transformers/all-MiniLM-L6-v2"
        digest = hashlib.sha256(f"fastembed:{model}".encode()).hexdigest()
    else:
        raise SystemExit(
            f"sparknet-vector: unknown SPARKNET_EMBED_BACKEND={backend!r}; expected fastembed, http or hash"
        )
    override = os.environ.get("SPARKNET_EMBED_SHA256", "").strip()
    return {
        "embedding_model": model,
        "embedding_sha256": override or digest,
        "embedding_backend": backend,
        "embedding_dim": str(_collection_dim()),
    }


_FASTEMBED_CACHE: dict[str, Any] = {}


def _hash_embedding(text: str, dim: int) -> list[float]:
    """A deterministic offline embedding for tests and dependency-free smoke runs.

    It is not semantic. It exists so the Qdrant backend can be exercised on a
    host that cannot download a model; the stamp names it, so a real index can
    never be mistaken for this one.
    """
    vector = [0.0] * dim
    for token in _tokens(text):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return vector
    return [value / norm for value in vector]


def _embed_http(texts: list[str]) -> list[list[float]]:
    url = os.environ.get("SPARKNET_EMBED_URL", "").strip()
    if not url:
        raise RuntimeError("SPARKNET_EMBED_URL is not set")
    endpoint = url.rstrip("/")
    if not endpoint.endswith("/embeddings"):
        endpoint = endpoint + "/embeddings" if endpoint.endswith("/v1") else endpoint + "/v1/embeddings"
    body = json.dumps(
        {"model": embedding_identity()["embedding_model"], "input": texts},
        sort_keys=True,
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    key = os.environ.get("SPARKNET_EMBED_API_KEY", "").strip()
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    timeout = float(os.environ.get("SPARKNET_EMBED_TIMEOUT", "30"))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != len(texts):
        raise RuntimeError("embedding endpoint returned a malformed data array")
    ordered = sorted(rows, key=lambda row: int(row.get("index", 0)) if isinstance(row, dict) else 0)
    vectors: list[list[float]] = []
    for row in ordered:
        vector = row.get("embedding") if isinstance(row, dict) else None
        if not isinstance(vector, list) or not all(isinstance(value, (int, float)) for value in vector):
            raise RuntimeError("embedding endpoint returned a non-numeric vector")
        vectors.append([float(value) for value in vector])
    return vectors


def _embed_fastembed(texts: list[str]) -> list[list[float]]:
    try:
        from fastembed import TextEmbedding  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - only reachable without the package
        raise SystemExit(
            "sparknet-vector: fastembed is not installed. Install it with "
            "'make vector-dev' or 'pip install \"qdrant-client[fastembed]>=1.12,<2\"'."
        ) from exc
    model_name = embedding_identity()["embedding_model"]
    model = _FASTEMBED_CACHE.get(model_name)
    if model is None:
        model = TextEmbedding(model_name=model_name)
        _FASTEMBED_CACHE[model_name] = model
    return [[float(value) for value in vector] for vector in model.embed(texts)]


def embed_texts(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    backend = _embedding_backend()
    if backend == "hash":
        return [_hash_embedding(text, _collection_dim()) for text in texts]
    if backend == "http":
        return _embed_http(texts)
    if backend == "fastembed":
        return _embed_fastembed(texts)
    raise SystemExit(f"sparknet-vector: unknown embedding backend {backend!r}")


def _embed_query(text: str) -> list[float]:
    vectors = embed_texts([text])
    if len(vectors) != 1:
        raise RuntimeError("embedder returned no query vector")
    return vectors[0]


def expected_stamp(docs: list[dict[str, object]], client: Any | None = None) -> dict[str, str]:
    """The stamp this build would write for ``docs``."""
    stamp = {**embedding_identity(), "corpus_digest": corpus_digest(docs)}
    if client is not None:
        stamp["qdrant_version"] = _qdrant_version(client)
    return stamp


class _UnusableIndex(Exception):
    """The index cannot be read or does not match this build.

    The index is derived state — the corpus in the vault is the source of
    truth — so the answer to an unusable index is always to rebuild it, never
    to serve what is there.
    """


class VectorCollection:
    """The tiny Qdrant surface the CLI and 4223 need, without leaking the client."""

    def __init__(self, client: Any, name: str, dim: int) -> None:
        self.client = client
        self.name = name
        self.dim = dim

    def _points(self, result: Any) -> list[Any]:
        points = getattr(result, "points", None)
        if points is None and isinstance(result, dict):
            points = result.get("points")
        return list(points or [])

    def query(self, query: str, limit: int) -> list[dict[str, Any]]:
        vector = _embed_query(query)
        result = self.client.query_points(
            collection_name=self.name,
            query=vector,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        hits: list[dict[str, Any]] = []
        for point in self._points(result):
            payload = getattr(point, "payload", None) or {}
            score = getattr(point, "score", None)
            distance = None if score is None else max(0.0, min(2.0, 1.0 - float(score)))
            hits.append(
                {
                    "id": str(payload.get("doc_id") or getattr(point, "id", "")),
                    "path": str(payload.get("path") or payload.get("doc_id") or ""),
                    "document": str(payload.get("document") or ""),
                    "distance": distance,
                    "point_id": str(getattr(point, "id", "")),
                }
            )
        return hits

    def get(self, ids: list[str]) -> list[dict[str, Any]]:
        """Retrieve by the human-readable doc id, never by a filesystem path."""
        wanted = [point_id(value) for value in ids]
        points = self.client.retrieve(
            collection_name=self.name,
            ids=wanted,
            with_payload=True,
            with_vectors=False,
        )
        rows: list[dict[str, Any]] = []
        for point in points:
            payload = getattr(point, "payload", None) or {}
            if isinstance(payload, dict):
                rows.append(payload)
        return rows


def _ensure_collection(client: Any, name: str, *, dim: int, create: bool) -> bool:
    from qdrant_client import models  # type: ignore[import-not-found]

    exists = client.collection_exists(name)
    if not exists and not create:
        return False
    if not exists:
        client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            on_disk_payload=True,
        )
    for field in ("doc_id", "path", "scope"):
        # Payload indexes are an optimisation; a store that refuses one must
        # not make the corpus unreadable.
        with contextlib.suppress(Exception):
            client.create_payload_index(
                collection_name=name,
                field_name=field,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
    return True


def _collection_name(scope: str) -> str:
    return f"sparknet-{scope}"


def _open_collection(scope: str, data_dir: Path, *, create: bool, client: Any | None = None):
    """Open the scope's Qdrant collection, or refuse a missing one.

    ``create=False`` never creates a collection. A query against a missing
    index must fail loudly, not return an empty result set: an empty result
    set is a sentence, and this tool must not be able to write one by accident.
    """
    client = client or _client(data_dir)
    name = _collection_name(scope)
    dim = _collection_dim()
    try:
        if not _ensure_collection(client, name, dim=dim, create=create):
            raise _UnusableIndex(f"collection {name!r} does not exist")
    except SystemExit:
        raise
    except Exception as exc:
        raise _UnusableIndex(str(exc)) from exc
    return VectorCollection(client, name, dim)


def _no_usable_index(scope: str, data_dir: Path, exc: Exception) -> None:
    """Report an index that cannot be used, and exit 3."""
    sys.stdout.flush()
    print(
        f"sparknet-vector: the '{scope}' index in {data_dir} cannot be used: {exc}\n"
        "(it may not exist, the Qdrant server may be unreachable, or it may "
        "have been written with a different embedding model). The index is "
        "derived state — rebuild it with:\n"
        f"  scripts/sparknet-vector.py {scope} index",
        file=sys.stderr,
    )
    raise SystemExit(3) from exc


def _reset_index(scope: str, data_dir: Path) -> None:
    """Remove an unusable local index directory; server collections are rebuilt."""
    target = data_dir.resolve()
    if target in {Path("/"), Path.home().resolve(), Path.cwd().resolve()} or target in Path.cwd().resolve().parents:
        raise SystemExit(f"refusing to remove unsafe index directory {target}")
    if _use_local(data_dir) and target.exists():
        shutil.rmtree(target, ignore_errors=True)
    _data_dir(data_dir)


def _data_dir(path: Path) -> Path:
    """Create the scope's state dir at 0700, never widening it."""
    bare = str(path)
    if not os.path.isdir(bare):
        os.makedirs(bare, mode=0o700)
    os.chmod(bare, 0o700)
    return path


def _index_version(data_dir: Path) -> str | None:
    marker = data_dir / VERSION_MARKER
    if not marker.is_file():
        return None
    return marker.read_text(encoding="utf-8").strip() or None


def _write_index_version(data_dir: Path, client: Any) -> None:
    (data_dir / VERSION_MARKER).write_text(f"{_qdrant_version(client)}\n", encoding="utf-8")


def cmd_init(scope: str, data_dir: Path) -> None:
    _data_dir(data_dir)
    client = _client(data_dir)
    _ensure_meta(client)
    try:
        collection = _open_collection(scope, data_dir, create=True, client=client)
    except _UnusableIndex:
        print(
            f"init: the existing index in {data_dir} cannot be read — rebuilding it",
            file=sys.stderr,
        )
        _reset_index(scope, data_dir)
        client = _client(data_dir)
        collection = _open_collection(scope, data_dir, create=True, client=client)
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


def _write_index(scope: str, data_dir: Path, docs: list[dict[str, object]], client: Any) -> None:
    """Upsert the corpus, drop what is no longer in it, and stamp it."""
    from qdrant_client import models  # type: ignore[import-not-found]

    collection = _open_collection(scope, data_dir, create=True, client=client)
    ids = [str(d["id"]) for d in docs]
    points: list[Any] = []
    batch = 32
    for start in range(0, len(docs), batch):
        chunk = docs[start : start + batch]
        vectors = embed_texts([str(item["document"]) for item in chunk])
        if len(vectors) != len(chunk):
            raise _UnusableIndex("embedder returned a different number of vectors than documents")
        for item, vector in zip(chunk, vectors, strict=True):
            doc_id = str(item["id"])
            points.append(
                models.PointStruct(
                    id=point_id(doc_id),
                    vector=vector,
                    payload={
                        "doc_id": doc_id,
                        "path": str(item["path"]),
                        "document": str(item["document"]),
                        "scope": scope,
                    },
                )
            )
    try:
        if points:
            collection.client.upsert(collection_name=collection.name, points=points, wait=True)
        # Exact corpus: remove every stored point whose doc id is not in the plan.
        stored: list[str] = []
        offset = None
        while True:
            page, offset = collection.client.scroll(
                collection_name=collection.name,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in page:
                payload = getattr(point, "payload", None) or {}
                doc_id = payload.get("doc_id") if isinstance(payload, dict) else None
                if doc_id:
                    stored.append(str(doc_id))
            if offset is None:
                break
        stale = sorted(set(stored) - set(ids))
        if stale:
            collection.client.delete(
                collection_name=collection.name,
                points_selector=models.PointIdsList(points=[point_id(value) for value in stale]),
                wait=True,
            )
        _write_stamp(collection.client, scope, expected_stamp(docs, collection.client))
    except _UnusableIndex:
        raise
    except Exception as exc:
        raise _UnusableIndex(str(exc)) from exc


def cmd_index(scope: str, vault: Path, data_dir: Path) -> None:
    docs = plan_index(scope, vault)
    _data_dir(data_dir)
    client = _client(data_dir)
    written = _index_version(data_dir)
    current = _qdrant_version(client)
    if written != current and _use_local(data_dir):
        reason = (
            "its provenance is unknown (no version marker)"
            if written is None
            else f"it was written by Qdrant {written}, this build has {current}"
        )
        print(
            f"index: {data_dir} is not this build's index — {reason} — rebuilding it from source",
            file=sys.stderr,
        )
        _reset_index(scope, data_dir)
        client = _client(data_dir)
    try:
        _write_index(scope, data_dir, docs, client)
    except _UnusableIndex as exc:
        _no_usable_index(scope, data_dir, exc)
    _write_index_version(data_dir, client)
    stamp = expected_stamp(docs)
    print(f"index: upserted {len(docs)} chunks into '{scope}'")
    print(f"index: stamped {stamp['embedding_model']} / {stamp['embedding_backend']} / {stamp['corpus_digest'][:12]}")


def cmd_stamp(scope: str, vault: Path, data_dir: Path) -> int:
    docs = plan_index(scope, vault)
    try:
        client = _client(data_dir)
        expected = expected_stamp(docs, client)
        stamp = _read_stamp(client, scope)
        if stamp is None:
            raise _UnusableIndex("the collection has no stamp")
    except _UnusableIndex as exc:
        _no_usable_index(scope, data_dir, exc)
    except SystemExit:
        raise
    refusals, reports = stamp_mismatch(stamp, expected)
    print(f"stamp: collection '{_collection_name(scope)}' in {data_dir}")
    for field in (*REFUSAL_FIELDS, *REPORT_FIELDS):
        print(f"  {field}: index={stamp.get(field)!r} build={expected.get(field)!r}")
    for report in reports:
        print(f"  note: {report}")
    if refusals:
        sys.stdout.flush()
        print("stamp: MISMATCH — this index must not be served:", file=sys.stderr)
        for refusal in refusals:
            print(f"  {refusal}", file=sys.stderr)
        print(f"  reindex it: scripts/sparknet-vector.py {scope} index", file=sys.stderr)
        return 3
    print("stamp: match")
    return 0


def open_checked(scope: str, vault: Path, data_dir: Path, *, log_prefix: str = "query", client: Any | None = None):
    """Open a collection whose stamp matches this build, or exit 3."""
    docs = plan_index(scope, vault)
    try:
        client = client or _client(data_dir)
        expected = expected_stamp(docs, client)
        stamp = _read_stamp(client, scope)
        if stamp is None:
            raise _UnusableIndex("the collection has no stamp")
        collection = _open_collection(scope, data_dir, create=False, client=client)
    except _UnusableIndex as exc:
        _no_usable_index(scope, data_dir, exc)
    except SystemExit:
        raise
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
        print(f"  reindex it: scripts/sparknet-vector.py {scope} index", file=sys.stderr)
        raise SystemExit(3)
    return collection


def query_candidates(scope: str, data_dir: Path, collection, query: str, n_results: int) -> list[dict[str, Any]]:
    """The Qdrant candidates, in similarity order, as plain dictionaries."""
    try:
        if hasattr(collection, "query"):
            return collection.query(query, n_results)
        result = collection.query_points(
            collection_name=getattr(collection, "name", _collection_name(scope)),
            query=_embed_query(query),
            limit=n_results,
            with_payload=True,
            with_vectors=False,
        )
        points = getattr(result, "points", []) or []
        rows = []
        for point in points:
            payload = getattr(point, "payload", None) or {}
            score = getattr(point, "score", None)
            rows.append(
                {
                    "id": str(payload.get("doc_id") or getattr(point, "id", "")),
                    "path": str(payload.get("path") or ""),
                    "document": str(payload.get("document") or ""),
                    "distance": None if score is None else max(0.0, min(2.0, 1.0 - float(score))),
                }
            )
        return rows
    except Exception as exc:
        _no_usable_index(scope, data_dir, exc)


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
    p = argparse.ArgumentParser(description="sparknet - local Qdrant index (optional; 4223 substrate)")
    p.add_argument("scope", choices=SCOPES, help="which vault to index")
    p.add_argument(
        "command",
        choices=("init", "inspect", "index", "stamp", "query"),
        help=(
            "init=create collection; inspect=plan without Qdrant; index=build; "
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
            "rerank Qdrant's candidates locally: shadow=log only (default when the flag "
            "is bare); assist=return the reranked order unless the reflex abstains"
        ),
    )
    p.add_argument("--candidate-k", type=int, default=50, help="candidates fetched before reranking (default 50)")
    p.add_argument("--reflex-top-k", type=int, default=None, help="results kept after reranking (default: --top-k)")
    p.add_argument("--reflex-json", action="store_true", help="print one machine-readable reflex line")
    p.add_argument("--no-reflex-cache", action="store_true", help="bypass the on-disk reflex ordering cache")
    p.add_argument(
        "--data-dir",
        default=None,
        help="override the scope's default .state/qdrant location; with no server URL this opens embedded Qdrant",
    )
    p.add_argument("--path", default=None, help="open embedded Qdrant at this path (explicit)")
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
        _collection_name_value, vault, default_data = resolve_scope(args.scope)
    except ValueError as exc:
        print(f"sparknet-vector: {exc}", file=sys.stderr)
        return 1
    if args.vault:
        vault = Path(args.vault).expanduser()
    data_dir = Path(args.data_dir) if args.data_dir else default_data
    if args.path:
        os.environ["SPARKNET_QDRANT_PATH"] = args.path

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
        print("sparknet-vector: 'query' needs text", file=sys.stderr)
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
