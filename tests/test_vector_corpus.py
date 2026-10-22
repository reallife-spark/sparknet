"""The `fabric` scope of the optional Chroma index (`scripts/sparknet-chroma.py`).

The `fabric` collection is the one the 4223 vector store would serve to every
node in the cluster. It therefore holds the *structural* fabric and nothing
else: the root documents, the contract tree and the role charters, selected by
the shared allow-list policy in `scripts/sparknet-rag-corpus.py`.

The property under test is the one a deny-list cannot give: a page nobody
classified is **out**, not in. These tests are the vector-store counterpart of
`tests/test_rag_corpus.py` — that one proves the policy for Open WebUI, this
one proves it for the shared store. Both read the *same* policy module, so
the two consumers cannot drift into disagreeing about what is safe to serve.

The role scopes are deliberately not covered here: a node's private index is
its own business and still walks its whole vault. What must never happen is
personal material reaching the collection that is shared.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "sparknet-chroma.py"
POLICY_SCRIPT = REPO_ROOT / "scripts" / "sparknet-rag-corpus.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


chroma = _load("sparknet_chroma", SCRIPT)
policy = _load("sparknet_rag_corpus_policy", POLICY_SCRIPT)


def _write(root: Path, rel: str | Path, text: str = "x") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fabric_paths(vault: Path) -> set[str]:
    return {str(d["path"]) for d in chroma.plan_index("fabric", vault)}


# --- the policy is shared, not copied -----------------------------------------


def test_the_index_loads_the_corpus_policy_by_path() -> None:
    """One allow-list, one answer to 'what is safe to serve'."""
    loaded = chroma._policy()
    assert Path(loaded.__file__).resolve() == POLICY_SCRIPT.resolve(), (
        "the index must load the shared policy file, not a copy of it"
    )
    assert loaded.FABRIC_ROOTS == policy.FABRIC_ROOTS
    source = SCRIPT.read_text(encoding="utf-8")
    assert "sparknet-rag-corpus.py" in source, "the policy is loaded by path, never copied"


def test_the_two_allow_lists_are_one_policy_and_a_superset() -> None:
    assert policy.NODE_ROOTS < policy.FABRIC_ROOTS, "the fabric list adds, it never relaxes"
    assert set(policy.ALLOW_LISTS) == {"node", "fabric"}
    assert policy.ALLOW_LISTS["node"] is policy.NODE_ROOTS
    assert policy.ALLOW_LISTS["fabric"] is policy.FABRIC_ROOTS


# --- the real repository ------------------------------------------------------


def test_the_fabric_scope_holds_only_allowed_paths() -> None:
    """Every indexed path must survive the policy's own allow-list."""
    paths = _fabric_paths(REPO_ROOT)
    assert paths, "the fabric has structural files; none were found"
    for rel in paths:
        path = Path(rel)
        assert not policy.is_excluded(path), f"{rel} is excluded but reached the index"
        assert policy.is_allowed(path, policy.FABRIC_ROOTS), f"{rel} is not allowed but reached the index"


def test_the_fabric_scope_leaks_no_personal_or_runtime_material() -> None:
    """The whole point: 64% of the old deny-list corpus was personal material."""
    paths = _fabric_paths(REPO_ROOT)
    for rel in paths:
        parts = Path(rel).parts
        assert "00_System" not in parts, f"{rel} is personal material"
        assert "sessions" not in parts and "journal" not in parts, f"{rel} is a session/journal page"
        assert Path(rel).name not in {"user.md", "MEMORY.md"}, f"{rel} is personal material"
    for rel in paths:
        assert not rel.startswith("peer-node/05_Knowledge"), "a role's vault is not shared"
        assert not rel.startswith("master-node/05_Knowledge"), "a role's vault is not shared"


def test_the_fabric_scope_carries_the_contract_tree_and_the_charters() -> None:
    paths = _fabric_paths(REPO_ROOT)
    assert "contracts/guard-protocol.md" in paths
    assert "contracts/ports.json" not in paths, "the index is markdown-only"
    assert "peer-node/AGENTS.md" in paths
    assert "master-node/AGENTS.md" in paths


def test_the_fabric_scope_carries_the_fabric_design_documents() -> None:
    """The design docs are the point of the shared store; they must be in it."""
    paths = _fabric_paths(REPO_ROOT)
    for name in ("USER_MANUAL.md", "CLUSTER_JOB_REALIZATION_DESIGN.md", "PER_USER_VAULTS_DESIGN.md"):
        assert name in paths
        assert name not in policy.NODE_ROOTS, "these are the fabric's additions, not the node's"


# --- the failure mode a deny-list cannot have ---------------------------------


def test_a_page_nobody_classified_is_out_by_default(tmp_path: Path) -> None:
    _write(tmp_path, "AGENTS.md")
    _write(tmp_path, "concepts/peering.md")  # distilled knowledge, not structure
    _write(tmp_path, "entities/agx64.md")
    _write(tmp_path, "notes/scratch.md")
    assert _fabric_paths(tmp_path) == {"AGENTS.md"}


def test_a_role_vault_page_never_reaches_the_shared_scope(tmp_path: Path) -> None:
    _write(tmp_path, "peer-node/AGENTS.md")
    _write(tmp_path, "peer-node/05_Knowledge/concepts/private.md")
    _write(tmp_path, "master-node/00_System/user.md")
    assert _fabric_paths(tmp_path) == {"peer-node/AGENTS.md"}


def test_a_personal_page_smuggled_into_the_contract_tree_is_out(tmp_path: Path) -> None:
    """Even an allowed tree cannot carry a personal page (the exclusion wins)."""
    _write(tmp_path, "contracts/guard-protocol.md")
    _write(tmp_path, "contracts/user.md")
    _write(tmp_path, "contracts/sessions/inside.md")
    assert _fabric_paths(tmp_path) == {"contracts/guard-protocol.md"}


# --- the role scopes keep their own vault -------------------------------------


def test_a_role_scope_still_indexes_its_own_vault_whole(tmp_path: Path) -> None:
    """A node's private index is its own business; only the shared scope is filtered."""
    vault = tmp_path / "peer-node"
    _write(vault, "05_Knowledge/concepts/private.md")
    _write(vault, "00_System/user.md")
    paths = {str(d["path"]) for d in chroma.plan_index("peer", vault)}
    assert paths == {"05_Knowledge/concepts/private.md", "00_System/user.md"}
