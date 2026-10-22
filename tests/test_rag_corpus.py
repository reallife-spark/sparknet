"""The structure-only RAG corpus (`scripts/sparknet-rag-corpus.py`).

The operator enabled Open WebUI RAG on each node but scoped it to the *shape* of
the fabric, never the vault's personal pages. That promise is only as strong as
the builder's allow-list, so these tests hold the two rules the module documents:

1. **Allow-list, not deny-list** — a page added tomorrow is out by default.
2. **The exclusion always wins** — even an allowed path is dropped if it names
   personal material, so the two rules can never disagree unsafely.

The last test runs against this real repository and asserts the corpus it would
actually build contains no excluded path. That is the one that would catch a
future ``contracts/user.md`` or a stray ``.state`` leak into the contract tree.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "sparknet-rag-corpus.py"


def _load():
    spec = importlib.util.spec_from_file_location("sparknet_rag_corpus", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


rag = _load()


def _write(root: Path, rel: str, text: str = "x") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- allow-list ---------------------------------------------------------------


def test_root_structure_files_are_included(tmp_path: Path) -> None:
    for name in ("AGENTS.md", "MISSION.md", "index.md", "hot.md", "CLUSTER_INFERENCE_DESIGN.md"):
        _write(tmp_path, name)
    got = {str(p) for p in rag.corpus_entries(tmp_path)}
    assert got == {
        "AGENTS.md",
        "MISSION.md",
        "index.md",
        "hot.md",
        "CLUSTER_INFERENCE_DESIGN.md",
    }


def test_the_contract_tree_is_included_whole(tmp_path: Path) -> None:
    _write(tmp_path, "contracts/capabilities.json", "{}")
    _write(tmp_path, "contracts/guard-protocol.md")
    got = {str(p) for p in rag.corpus_entries(tmp_path)}
    assert got == {"contracts/capabilities.json", "contracts/guard-protocol.md"}


def test_only_role_charters_are_included_from_a_role(tmp_path: Path) -> None:
    _write(tmp_path, "peer-node/AGENTS.md")
    _write(tmp_path, "peer-node/PLAN.md")
    _write(tmp_path, "peer-node/05_Knowledge/concepts/secret.md")  # role vault content
    got = {str(p) for p in rag.corpus_entries(tmp_path)}
    assert got == {"peer-node/AGENTS.md", "peer-node/PLAN.md"}


def test_an_unlisted_root_page_is_out_by_default(tmp_path: Path) -> None:
    _write(tmp_path, "concepts/peering.md")  # distilled knowledge, not structure
    _write(tmp_path, "entities/agx64.md")
    assert rag.corpus_entries(tmp_path) == []


# --- the exclusion always wins ------------------------------------------------


def test_user_md_is_never_included_even_where_it_might_be_allowed(tmp_path: Path) -> None:
    _write(tmp_path, "AGENTS.md")
    _write(tmp_path, "contracts/README.md")
    # Even a page placed inside the allowed contract tree cannot smuggle a user page.
    _write(tmp_path, "contracts/user.md")
    got = {str(p) for p in rag.corpus_entries(tmp_path)}
    assert "contracts/user.md" not in got
    assert "AGENTS.md" in got


def test_personal_categories_and_secret_files_are_excluded(tmp_path: Path) -> None:
    for rel in (
        "00_System/user.md",
        "02_Daily/2026-10-10.md",
        "03_Sources/paper.md",
        "sessions/2026-10-10.md",
        "secrets-index.json",
        "user-env-manifest.json",
        ".env",
        "peer-node/.state/keys/operational.ed25519",
    ):
        _write(tmp_path, rel)
    assert rag.corpus_entries(tmp_path) == []


def test_excluded_suffixes_and_parts_win_over_an_allowed_prefix(tmp_path: Path) -> None:
    _write(tmp_path, "contracts/notes.md")
    _write(tmp_path, "contracts/authority.ed25519")
    _write(tmp_path, "contracts/sessions/inside.md")
    got = {str(p) for p in rag.corpus_entries(tmp_path)}
    assert got == {"contracts/notes.md"}


# --- materialization ----------------------------------------------------------


def test_build_corpus_writes_only_allowed_files_and_an_inventory(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault, "AGENTS.md", "root charter")
    _write(vault, "contracts/guard-protocol.md", "protocol")
    _write(vault, "00_System/user.md", "personal")
    out = tmp_path / "corpus"

    written = rag.build_corpus(vault, out)
    assert {str(p) for p in written} == {"AGENTS.md", "contracts/guard-protocol.md"}
    assert (out / "AGENTS.md").read_text() == "root charter"
    assert not (out / "00_System" / "user.md").exists()
    assert "Never included" in (out / "INVENTORY.md").read_text()


def test_build_corpus_is_idempotent(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault, "contracts/ports.json", "{}")
    out = tmp_path / "corpus"
    first = rag.build_corpus(vault, out)
    second = rag.build_corpus(vault, out)
    assert first == second


# --- role charters do not collide ---------------------------------------------


def test_role_charters_are_namespaced(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _write(vault, "AGENTS.md", "root")
    _write(vault, "peer-node/AGENTS.md", "peer")
    _write(vault, "master-node/AGENTS.md", "master")
    _write(vault, "peer-node/PLAN.md", "peer plan")
    out = tmp_path / "corpus"

    written = {str(p) for p in rag.build_corpus(vault, out)}
    assert written == {
        "AGENTS.md",
        "peer-node__AGENTS.md",
        "master-node__AGENTS.md",
        "peer-node__PLAN.md",
    }
    assert (out / "peer-node__AGENTS.md").read_text() == "peer"
    assert (out / "master-node__AGENTS.md").read_text() == "master"


def test_the_corpus_has_no_duplicate_basenames(tmp_path: Path) -> None:
    """Open WebUI flattens filenames, so no two corpus files may share one."""
    vault = tmp_path / "vault"
    _write(vault, "AGENTS.md")
    _write(vault, "MISSION.md")
    _write(vault, "README.md")
    _write(vault, "peer-node/AGENTS.md")
    _write(vault, "peer-node/MISSION.md")
    _write(vault, "peer-node/README.md")
    _write(vault, "master-node/AGENTS.md")
    _write(vault, "master-node/MISSION.md")
    _write(vault, "master-node/README.md")
    out = tmp_path / "corpus"

    names = [p.name for p in rag.build_corpus(vault, out)]
    assert len(names) == len(set(names)), f"duplicate basenames: {names}"


# --- the two allow-lists ------------------------------------------------------


def test_the_node_allow_list_is_unchanged() -> None:
    """The node's corpus was defined before the fabric list existed; it stays put."""
    expected = {
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
    assert sorted(rag.NODE_ROOTS) == sorted(expected)


def test_the_fabric_allow_list_adds_the_design_documents() -> None:
    """A strict superset: the fabric adds documents, it never relaxes the rule."""
    assert rag.NODE_ROOTS < rag.FABRIC_ROOTS
    for name in (
        "USER_MANUAL.md",
        "CLUSTER_JOB_REALIZATION_DESIGN.md",
        "PER_USER_VAULTS_DESIGN.md",
        "ADMIN_FEDERATION_DESIGN.md",
        "STYLE_GUIDE.md",
    ):
        assert name in rag.FABRIC_ROOTS
        assert name not in rag.NODE_ROOTS


def test_the_allow_lists_are_addressed_by_name() -> None:
    assert rag.ALLOW_LISTS == {"node": rag.NODE_ROOTS, "fabric": rag.FABRIC_ROOTS}
    assert rag.allow_list_name(rag.NODE_ROOTS) == "node"
    assert rag.allow_list_name(rag.FABRIC_ROOTS) == "fabric"
    assert rag.allow_list_name(None) == "node"


def test_the_allow_list_argument_selects_the_corpus(tmp_path: Path) -> None:
    _write(tmp_path, "AGENTS.md")
    _write(tmp_path, "USER_MANUAL.md")
    _write(tmp_path, "STYLE_GUIDE.md")
    node = {str(p) for p in rag.corpus_entries(tmp_path, rag.NODE_ROOTS)}
    fabric = {str(p) for p in rag.corpus_entries(tmp_path, rag.FABRIC_ROOTS)}
    assert node == {"AGENTS.md"}
    assert fabric == {"AGENTS.md", "USER_MANUAL.md", "STYLE_GUIDE.md"}


def test_the_real_repository_fabric_corpus_carries_the_design_documents() -> None:
    entries = rag.corpus_entries(REPO_ROOT, rag.FABRIC_ROOTS)
    names = {p.name for p in entries}
    assert "USER_MANUAL.md" in names
    assert "CLUSTER_JOB_REALIZATION_DESIGN.md" in names
    assert "AGENTS.md" in names


def test_the_inventory_records_which_allow_list_was_applied(tmp_path: Path) -> None:
    _write(tmp_path, "AGENTS.md")
    out = tmp_path / "corpus"
    rag.build_corpus(tmp_path, out, rag.FABRIC_ROOTS)
    assert "Allow-list applied: `fabric`." in (out / "INVENTORY.md").read_text()


# --- the real repository ------------------------------------------------------


def test_the_real_repository_corpus_leaks_no_personal_path() -> None:
    """The corpus this repo would actually build must contain no excluded path."""
    entries = rag.corpus_entries(REPO_ROOT)
    assert entries, "the fabric has structural files (contracts, charters); none were found"
    for rel in entries:
        assert not rag.is_excluded(rel), f"{rel} is excluded but reached the corpus"
        assert rag.is_allowed(rel), f"{rel} is not on the allow-list but reached the corpus"
    names = {p.name for p in entries}
    assert "user.md" not in names
    assert "secrets-index.json" not in names
    # A known structural page must be present, or the allow-list drifted too far.
    assert Path("contracts/guard-protocol.md") in entries
    assert Path("peer-node/AGENTS.md") in entries
