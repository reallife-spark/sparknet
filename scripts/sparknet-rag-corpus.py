#!/usr/bin/env python3
"""Build the STRUCTURE-ONLY corpus a node's Open WebUI may ingest (RAG).

Why this exists
~~~~~~~~~~~~~~~
The operator enabled Open WebUI RAG on each node, backed by the node's own
ChromaDB — but only over the shape of the fabric, never its personal material.
"Ingesting the vault" and "ingesting the vault's structure" are different things,
and the difference is exactly the page that says who the user is. This script is
the allow-list that keeps them apart, so the vector store never becomes an
uncontrolled copy of the vault.

Two rules, both fail-closed:

1. **Allow-list, not deny-list.** A file is in the corpus only if it matches one
   of the exact root names, the ``contracts/`` tree, or a role charter file.
   Anything not explicitly allowed is out — so a new personal page added tomorrow
   is excluded by default rather than by remembering to update an exclusion.
2. **The exclusion still wins.** Even an allowed path is dropped if it carries an
   excluded part (``sessions``, ``_raw``, ``.state`` …), an excluded name
   (``user.md``, ``secrets-index.json`` …), or an excluded suffix (``.ed25519``).
   The two rules can never disagree in the unsafe direction.

One policy, two allow-lists
~~~~~~~~~~~~~~~~~~~~~~~~~~~

There is **one** allow-list policy here, and the consumers differ only in which
root files they name:

- ``NODE_ROOTS`` — what a *node* may ingest into its own Open WebUI: the
  structural root files, the ``contracts/`` tree and the role charters.
- ``FABRIC_ROOTS`` — the node's roots **plus** the fabric's own design
  documents, which describe the shape of the whole cluster and are therefore
  safe to serve to every node over the shared 4223 vector store.

``FABRIC_ROOTS`` is a strict superset of ``NODE_ROOTS``: a file that is out for a
node is out for the fabric, and the exclusion rules are identical in both. The
rule set is written once so the two consumers cannot drift apart — a second copy
of an allow-list is a second answer to "what is safe to serve".

Usage::

    scripts/sparknet-rag-corpus.py <vault-root>            # print the manifest
    scripts/sparknet-rag-corpus.py <vault-root> --plan     # same, human summary
    scripts/sparknet-rag-corpus.py <vault-root> --out DIR  # materialize the corpus
    scripts/sparknet-rag-corpus.py <vault-root> --allow-list fabric

``--out`` writes the allowed files under ``DIR`` preserving relative paths, plus
an ``INVENTORY.md`` recording what went in and the policy that put it there. Feed
``DIR`` to Open WebUI as a Knowledge collection.

Exit codes: 0 ok, 1 vault-root/user error.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# --- the policy, in one place -------------------------------------------------

#: Root files that describe the fabric's shape (never its personal content).
#: This is the **node** allow-list: what a node's own Open WebUI may ingest.
NODE_ROOTS = {
    "AGENTS.md",
    "MISSION.md",
    "README.md",
    "index.md",
    "hot.md",
    "schema.yaml",
    "CLUSTER_INFERENCE_DESIGN.md",
    "COMPUTE_CAPABILITY_DESIGN.md",
    "MCP_A2A_DESIGN.md",
}

#: The **fabric** allow-list: the node's roots plus the fabric's own design
#: documents. These describe the shape of the whole cluster — the contract
#: surface, the job realization, the per-user vault model, the admin
#: federation and the house style — and are safe to serve to every node over
#: the shared 4223 vector store. A strict superset of ``NODE_ROOTS``: a file
#: that is out for a node is out for the fabric.
FABRIC_ROOTS = NODE_ROOTS | {
    "USER_MANUAL.md",
    "CLUSTER_JOB_REALIZATION_DESIGN.md",
    "PER_USER_VAULTS_DESIGN.md",
    "ADMIN_FEDERATION_DESIGN.md",
    "STYLE_GUIDE.md",
}

#: The allow-lists, by the name a consumer asks for.
ALLOW_LISTS = {"node": NODE_ROOTS, "fabric": FABRIC_ROOTS}

#: Directory trees whose *whole* content is structural.
DIR_PREFIXES = ("contracts",)

#: Role subvaults contribute only their charter-level files, never their vault.
ROLES = ("peer-node", "master-node")
ROLE_ROOT_FILES = {"AGENTS.md", "MISSION.md", "README.md", "PLAN.md"}

#: Suffixes worth ingesting. The contract tree's JSON (capabilities, ports,
#: overlay, schemas) is structural and included; keys are ``.ed25519`` (always
#: excluded) and images, ledgers and binaries carry no structural prose.
ALLOWED_SUFFIXES = {".md", ".yaml", ".yml", ".json"}

#: Path parts that mark personal or runtime material anywhere in the path. If any
#: appears, the file is out regardless of the allow-list above.
EXCLUDE_PARTS = {
    ".git",
    ".venv",
    ".state",
    ".cache",
    "__pycache__",
    "node_modules",
    "dist",
    ".pytest_cache",
    ".ruff_cache",
    ".opencode",
    "_raw",
    "_staging",
    "_archives",
    "journal",
    "sessions",
    "00_System",
    "01_Inbox",
    "02_Daily",
    "03_Sources",
    "06_Mail",
    "07_Archives",
    "keys",
    "mail",
}

#: Exact names that are always personal or secret-bearing.
EXCLUDE_NAMES = {
    "user.md",
    "user-env-manifest.json",
    "secrets-index.json",
    ".env",
    "MEMORY.md",
}

#: Suffixes that are always out (key material, data, media).
EXCLUDE_SUFFIXES = {".ed25519", ".pem", ".key", ".jsonl", ".db", ".sqlite3"}


def is_excluded(rel: Path) -> bool:
    """True when any part of ``rel`` names personal or runtime material."""
    if any(part in EXCLUDE_PARTS for part in rel.parts):
        return True
    if rel.name in EXCLUDE_NAMES:
        return True
    return rel.suffix.lower() in EXCLUDE_SUFFIXES


def is_allowed(rel: Path, roots: set[str] | None = None) -> bool:
    """True when ``rel`` matches the structural allow-list (before exclusions).

    ``roots`` selects which allow-list applies: the node's (default) or the
    fabric's. The rest of the rule set — the contract tree, the role charters
    and every exclusion — is the same for both, so a consumer cannot opt into
    a laxer policy by naming a different list.
    """
    allow = NODE_ROOTS if roots is None else roots
    if len(rel.parts) == 1 and rel.name in allow:
        return True
    if rel.parts and rel.parts[0] in DIR_PREFIXES:
        return True
    return bool(len(rel.parts) == 2 and rel.parts[0] in ROLES and rel.parts[1] in ROLE_ROOT_FILES)


def corpus_entries(vault: Path, roots: set[str] | None = None) -> list[Path]:
    """Return every file the corpus would contain, as vault-relative paths.

    Deterministic (sorted) and pure: it reads the tree but writes nothing, so a
    test can assert the policy without materializing anything.
    """
    vault = vault.resolve()
    entries: list[Path] = []
    for path in sorted(vault.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue
        rel = path.relative_to(vault)
        if is_excluded(rel) or not is_allowed(rel, roots):
            continue
        entries.append(rel)
    return entries


def materialized_path(rel: Path) -> Path:
    """Return the corpus-relative path a source file is written to.

    Role charter files are namespaced (``peer-node/AGENTS.md`` ->
    ``peer-node__AGENTS.md``). Open WebUI flattens an ingested file to its
    basename, so the two roles both shipping ``AGENTS.md``/``MISSION.md``/
    ``README.md`` would collide in one knowledge base and show as duplicates.
    The namespaced name keeps both charters distinct without dropping either.
    """
    if len(rel.parts) == 2 and rel.parts[0] in ROLES:
        return Path(f"{rel.parts[0]}__{rel.parts[1]}")
    return rel


def allow_list_name(roots: set[str] | None) -> str:
    """The name of an allow-list, for the inventory and the CLI output."""
    if roots is None:
        return "node"
    for name, allowed in ALLOW_LISTS.items():
        if allowed == roots:
            return name
    return "custom"


def build_corpus(vault: Path, out: Path, roots: set[str] | None = None) -> list[Path]:
    """Materialize the corpus under ``out``; return the paths written.

    The returned paths are corpus-relative and already namespaced (see
    ``materialized_path``), so they match what lands on disk.
    """
    entries = corpus_entries(vault, roots)
    if out.exists():
        shutil.rmtree(out)
    written: list[Path] = []
    for rel in entries:
        dest_rel = materialized_path(rel)
        dest = out / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(vault / rel, dest)
        written.append(dest_rel)
    (out / "INVENTORY.md").write_text(_inventory(written, allow_list_name(roots)), encoding="utf-8")
    return written


def _inventory(entries: list[Path], allow_list: str = "node") -> str:
    lines = [
        "# Structure-only RAG corpus",
        "",
        "Built by `scripts/sparknet-rag-corpus.py`. This corpus is the shape of the",
        "fabric (contracts, charters, taxonomy, design docs) and deliberately NOT",
        "the vault's personal pages. The allow/exclude policy lives in that script.",
        f"Allow-list applied: `{allow_list}`.",
        "",
        "## Included",
        "",
    ]
    lines += [f"- `{rel}`" for rel in entries] or ["- (nothing)"]
    lines += [
        "",
        "## Never included",
        "",
        "- any path under `00_System/`, `01_Inbox/`, `02_Daily/`, `03_Sources/`,",
        "  `sessions/`, `journal/`, `_raw/`, `_staging/`, `_archives/`, `.state/`",
        "- `user.md`, `MEMORY.md`, `secrets-index.json`, `user-env-manifest.json`, `.env`",
        "- `*.ed25519`, `*.pem`, `*.key`",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="build the structure-only corpus a node's Open WebUI may ingest")
    p.add_argument("vault_root", help="the vault to read (nothing is written there)")
    p.add_argument("--out", default=None, help="materialize the corpus into this directory")
    p.add_argument("--plan", action="store_true", help="print a human summary")
    p.add_argument(
        "--allow-list",
        choices=sorted(ALLOW_LISTS),
        default="node",
        help=(
            "'node' = the structural root files (a node's own corpus); "
            "'fabric' = those plus the fabric's design docs (the shared 4223 store)"
        ),
    )
    args = p.parse_args(argv)

    vault = Path(args.vault_root).expanduser()
    if not vault.is_dir():
        print(f"sparknet-rag-corpus: not a directory: {vault}", file=sys.stderr)
        return 1

    roots = ALLOW_LISTS[args.allow_list]
    entries = corpus_entries(vault, roots)

    if args.out:
        written = build_corpus(vault, Path(args.out).expanduser(), roots)
        print(f"corpus: wrote {len(written)} files to {args.out}")

    if args.plan or not args.out:
        print(f"corpus: {len(entries)} structural files under {vault} (allow-list: {args.allow_list})")
        for rel in entries:
            print(f"  {rel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
