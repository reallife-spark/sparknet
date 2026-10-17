#!/usr/bin/env python3
"""Optional local semantic index for a sparknet vault (port 4223's substrate).

The fabric contract reserves ``4223 vector-embed`` for the Master to host a
single shared vector store that the roles and their wiki skills query over the
overlay. That service is deliberately **not built** (``contracts/ports.json``
keeps 4223 ``spec-only``). This script is the piece that may be used *before*
that service exists, and on a host that will never host it: a local, optional
Chroma index of a vault's markdown, one collection per scope.

Two design rules, both enforced:

1. **chromadb is optional.** The runtime dependency allow-list is
   ``cryptography`` alone, and chromadb is a heavy package a node should not be
   forced to install. This module imports chromadb *lazily*, inside the
   functions that need it, with a clear install hint. Importing the module, or
   running ``inspect``, never touches chromadb — so the pure logic
   (discovery, deterministic chunking, doc ids) is testable on a system that
   has never seen the package.
2. **Everything is deterministic.** ``inspect`` reproduces ids and chunks
   exactly across runs, so a re-index is idempotent (upsert by stable id) and
   a test can assert on the plan without chromadb being present.

Scopes
~~~~~~

- ``peer``    -> index ``peer-node/``            (data in ``peer-node/.state/chroma/``)
- ``master``  -> index ``master-node/``          (data in ``master-node/.state/chroma/``)
- ``fabric``  -> index the whole tree (the shared single store the roles use,
  matching the 4223 contract's description)      (data in ``.state/chroma/``)

``.state/`` is gitignored at every level, so the index never enters a bundle
or a commit. The collection name is ``sparknet-<scope>``.

Usage::

    scripts/sparknet-chroma.py <scope> init              # create the collection
    scripts/sparknet-chroma.py <scope> inspect           # plan without chromadb
    scripts/sparknet-chroma.py <scope> index             # build the index
    scripts/sparknet-chroma.py <scope> query "text" [--top-k N] [--data-dir DIR]

Exit codes: 0 ok, 1 discovery/user error, 2 chromadb missing.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Directories that are never vault content. Generated dirs, caches, the
#: vendored skills (not knowledge) and role trees that belong to another scope.
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


ROLE_DIRS = ("peer-node", "master-node")


def _vault_roots(scope: str, vault: Path) -> list[tuple[str, Path]]:
    """The roots a scope indexes: the scope's own vault, plus (for fabric) both roles."""
    if scope == "fabric":
        return [("", vault), ("peer-node", vault / "peer-node"), ("master-node", vault / "master-node")]
    return [("", vault)]


def iter_markdown(root: Path, *, include_roles: bool = False) -> Iterator[tuple[str, Path]]:
    """Yield ``(label, path)`` for every markdown file belonging to a root.

    ``label`` is the path prefix for a doc's id (``""`` for the root's own
    content, ``"peer-node"``/``"master-node"`` for the combined fabric store).
    When ``include_roles`` is false the role dirs are *skipped* entirely — the
    fabric store enumerates them via their own rooted walks, so a file is never
    discovered twice, which would give it two ids and break idempotency.
    """
    for path in sorted(root.rglob("*.md")):  # sorted -> deterministic discovery
        rel = path.relative_to(root)
        if EXCLUDE_PARTS & set(rel.parts):
            continue
        if rel.parts and rel.parts[0] in ROLE_DIRS:
            # Files under a role dir are enumerated by that role's rooted walk
            # below (once, with the right label). Folding them in here as well
            # would give every role file two ids and break idempotency.
            continue
        yield "", rel
    if include_roles:
        for sub in ROLE_DIRS:
            sub_root = root / sub
            if not sub_root.is_dir():
                continue
            for path in sorted(sub_root.rglob("*.md")):
                rel = path.relative_to(sub_root)
                if EXCLUDE_PARTS & set(rel.parts):
                    continue
                yield sub, rel


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
    """
    docs: list[dict[str, object]] = []
    for label, root in _vault_roots(scope, vault):
        for prefix, rel in iter_markdown(root):
            del prefix  # discovery label == this root's label; path is from root
            rel_path = Path(label) / rel if label else rel
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
            for i, chunk in enumerate(chunk_text(text)):
                docs.append(
                    {
                        "id": f"{scope}:{rel_path}#{i}",
                        "document": chunk,
                        "path": str(rel_path),
                    }
                )
    return docs


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
            "  make chroma-dev     (or: pip install 'chromadb>=0.5')\n"
            f"({exc})",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


def _collection(scope: str, data_dir: Path):
    _require()
    import chromadb  # type: ignore[import-not-found]

    return chromadb.PersistentClient(path=str(data_dir)).get_or_create_collection(name=f"sparknet-{scope}")


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
    collection = _collection(scope, data_dir)
    print(f"init: collection '{collection.name}' ready in {data_dir}")


def cmd_inspect(scope: str, vault: Path) -> int:
    docs = plan_index(scope, vault)
    total_chars = sum(len(d["document"]) for d in docs)  # type: ignore[arg-type]
    print(f"inspect: scope={scope} path={vault}")
    print(f"  documents: {len(docs)}")
    print(f"  characters: {total_chars}")
    for entry in docs[:20]:
        print(f"  {entry['id']}  ({len(entry['document'])} chars)")
    if len(docs) > 20:
        print(f"  ... and {len(docs) - 20} more")
    return 0


def cmd_index(scope: str, vault: Path, data_dir: Path) -> None:
    docs = plan_index(scope, vault)
    collection = _collection(scope, data_dir)
    collection.upsert(
        ids=[str(d["id"]) for d in docs],
        documents=[str(d["document"]) for d in docs],
        metadatas=[{"path": d["path"]} for d in docs],
    )
    print(f"index: upserted {len(docs)} chunks into '{collection.name}'")


def cmd_query(scope: str, vault: Path, data_dir: Path, query: str, top_k: int) -> int:
    collection = _collection(scope, data_dir)
    result = collection.query(query_texts=[query], n_results=top_k)
    ids = result.get("ids", [[]])[0]
    distances = result.get("distances", [[]])[0]
    docs = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    if not ids:
        print(f"query: no results for {query!r} in '{collection.name}'")
        return 0
    print(f"query: top {len(ids)} results in '{collection.name}'")
    for i, doc_id in enumerate(ids):
        score = distances[i] if i < len(distances) else None
        meta = metadatas[i] if i < len(metadatas) else {}
        path = meta.get("path", doc_id) if isinstance(meta, dict) else doc_id
        text = docs[i] if i < len(docs) else ""
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
        choices=("init", "inspect", "index", "query"),
        help="init=create collection; inspect=plan without chromadb; index=build; query=search",
    )
    p.add_argument("query_text", nargs="?", default="", help="search text for 'query'")
    p.add_argument("--top-k", type=int, default=5, help="results to return (default 5)")
    p.add_argument(
        "--data-dir",
        default=None,
        help="override the scope's default .state/chroma location (tests use this)",
    )
    args = p.parse_args(argv)
    try:
        _collection_name, vault, default_data = resolve_scope(args.scope)
    except ValueError as exc:
        print(f"sparknet-chroma: {exc}", file=sys.stderr)
        return 1
    data_dir = Path(args.data_dir) if args.data_dir else default_data

    if args.command == "init":
        cmd_init(args.scope, data_dir)
        return 0
    if args.command == "inspect":
        return cmd_inspect(args.scope, vault)
    if args.command == "index":
        cmd_index(args.scope, vault, data_dir)
        return 0
    if not args.query_text:
        print("sparknet-chroma: 'query' needs text", file=sys.stderr)
        p.print_usage(file=sys.stderr)
        return 1
    return cmd_query(args.scope, vault, data_dir, args.query_text, args.top_k)


if __name__ == "__main__":
    sys.exit(main())
