"""Live surfaces must state current truth (fabric PLAN Step 14).

The gates were all green on 2026-10-08 and the vault was still lying: README,
index and AGENTS described a Master that "signs nothing" (the election and the
signer went live on agx64/agx32 the day before), the skill count said 31 while
33 directories shipped, and `master-node/plans/` still carried the pre-Step-3
preamble claiming no `scripts/` exists. Green gates prove the code; nothing
was proving the prose an agent reads first.

So this file asserts three classes of claim that rot silently:

1. **Counts** — every "N skills" on a live surface equals what is on disk.
2. **Forbidden phrases** — specific past-true statements that must never
   reappear (they were listed in the Step 14 DoD for exactly this reason).
3. **Coverage** — `index.md`'s contract table names every file in `contracts/`,
   so a new contract cannot be silently absent from the navigation.

Provenance is exempt, by the same rule `tests/test_layout.py` applies:
`references/`, `plans/`, `sessions/`, `journal/`, `_raw/`, `_archives/`,
`_staging/` record what was true when they were written. `PLAN.md` and
`log.md` are exempt for a sharper reason — `PLAN.md`'s Step 14 DoD *quotes*
the forbidden phrases as the list to enforce, so scanning it would make the
test fail against its own instruction. `tests/` is exempt for the same
self-reference reason. `.opencode/` is the skill suite's own metadata, which
counts "shipped" and "local" separately rather than in the "N skills" total
this file checks.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Directories whose contents are history rather than current specification.
#: Mirrors `tests/test_layout.py::PROVENANCE_DIRS`; duplicated rather than
#: imported so the two files can evolve independently.
PROVENANCE_DIRS = {
    "references",
    "plans",
    "sessions",
    "journal",
    "_raw",
    "_archives",
    "01_Inbox",
    "02_Daily",
    "03_Sources",
    "07_Archives",
}

SKIP_DIRS = PROVENANCE_DIRS | {
    "__pycache__",
    ".git",
    ".venv",
    "dist",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".opencode",
    "tests",
    "_staging",
}

#: Files excluded by name (not directory), each with the reason it is exempt.
SKIP_FILES = {
    # Step history and append-only audit trail; PLAN.md's DoD quotes the very
    # phrases this test forbids.
    "PLAN.md",
    "log.md",
}

#: Statements that were true once and must never be asserted again. Each one
#: was found on a live surface during the 2026-10-08 review; the Step 14 DoD
#: names the first three.
FORBIDDEN_PHRASES = (
    "signs nothing yet",  # disproven by the 2026-10-07 election
    "holds no usable",  # the signer has run live since 2026-10-07
    "no usable signing key",  # same claim, other phrasing
    "isolated signer is Step",  # Steps 15-18 are done and deployed
    "One peer, no master, no second node",  # disproven by the 2/2 live pair
    "Nothing above is live-verified",
    "No `scripts/`, `services/` or `systemd/` directory exists yet",
)

SKILL_COUNT = re.compile(r"(\d+)\s+skills")

SKILLS_DIR = REPO_ROOT / ".opencode" / "skills"
CONTRACTS_DIR = REPO_ROOT / "contracts"


def live_surfaces() -> list[Path]:
    """Every prose surface an agent (or a human) reads as current.

    Suffixes are deliberately narrow: `.md` and `.sh` prose plus the Makefile.
    Configs, manifests and JSON are checked by their own tests.
    """
    out: list[Path] = []
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT)
        if set(rel.parts) & SKIP_DIRS:
            continue
        if path.name in SKIP_FILES:
            continue
        if path.suffix in {".md", ".sh"} or path.name == "Makefile":
            out.append(path)
    return out


def shipped_skill_count() -> int:
    """Skill directories that actually ship — counted from disk, not claimed."""
    return sum(1 for p in SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())


def test_the_suite_really_has_the_expected_shape():
    """Guard the counter itself: if this fails, every count below is noise."""
    count = shipped_skill_count()
    assert count >= 30, (
        f"only {count} skill directories with a SKILL.md — the counter is "
        "reading the wrong place, or the suite lost most of its skills"
    )
    assert (SKILLS_DIR / "README.md").is_file(), "the suite README is missing"


def test_documented_skill_counts_match_the_disk():
    """Every "N skills" on a live surface equals what ships.

    The count is asserted against disk rather than against a literal 33 so
    that adding a skill is a docs edit and not a test edit — but a surface
    that documents no count at all would make this trivially pass, so at
    least one must mention it.
    """
    actual = shipped_skill_count()
    seen = 0
    for path in live_surfaces():
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in SKILL_COUNT.finditer(text):
            seen += 1
            assert int(match.group(1)) == actual, (
                f"{path.relative_to(REPO_ROOT)} says {match.group(0)!r} but "
                f".opencode/skills/ ships {actual} — update the surface, or "
                "fix the counter"
            )
    assert seen >= 1, (
        "no live surface documents the skill count at all — the count is "
        "supposed to be stated (README, AGENTS, Makefile, MEMORY, hot)"
    )


def test_no_live_surface_carries_a_forbidden_phrase():
    """The specific stale claims from the 2026-10-08 review stay dead.

    Provenance (`plans/`, `references/`, sessions, `log.md`, `PLAN.md`) may
    still say them; it records what was believed at the time. A live surface
    saying them sends the next agent out with a false model of the system.
    """
    hits: list[str] = []
    for path in live_surfaces():
        text = path.read_text(encoding="utf-8", errors="replace")
        for phrase in FORBIDDEN_PHRASES:
            if phrase in text:
                hits.append(f"{path.relative_to(REPO_ROOT)}: {phrase!r}")
    assert not hits, "live surfaces carry claims the 2026-10-07/08 verification disproved:\n  " + "\n  ".join(hits)


def test_index_names_every_contract_file():
    """A new contract that the index never mentions does not exist for navigation.

    `contracts/README.md` documents each file; this checks the other direction
    — that the curated index in `index.md` names all of them, table row by
    table row. Both directions are needed: the README is read inside
    `contracts/`, the index is read first.
    """
    index = (REPO_ROOT / "index.md").read_text(encoding="utf-8")
    missing = []
    for path in sorted(CONTRACTS_DIR.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        if f"| `contracts/{path.name}`" not in index:
            missing.append(path.name)
    assert not missing, (
        "index.md's contract table is missing: "
        + ", ".join(missing)
        + " — a contract without an index row is a contract nobody navigates to"
    )


def test_readme_documents_the_verifier_for_each_claim_class():
    """The three claims above are only useful if an operator can run them.

    Cheap cross-check that the README's verification section still points at
    the gates, so the tests added here are reachable from the prose rather
    than only from `make test-all`.
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for tool in ("make test-all", "make contract-test", "make validate"):
        assert tool in readme, f"README.md no longer mentions `{tool}`"
