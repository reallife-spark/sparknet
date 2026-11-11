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

import json
import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.layout


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
    "no node has been elected yet",  # the 2026-10-07 election disproved it
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


def _manual_section(start: str, end: str) -> str:
    """Return the USER_MANUAL section between two headings."""
    text = (REPO_ROOT / "USER_MANUAL.md").read_text(encoding="utf-8")
    assert start in text, f"USER_MANUAL.md lost the {start!r} section"
    assert end in text, f"USER_MANUAL.md lost the {end!r} section"
    return text.split(start, 1)[1].split(end, 1)[0]


def test_manual_compose_table_names_every_compose_service() -> None:
    """The compose table must name every service the compose file declares."""
    compose = yaml.safe_load((REPO_ROOT / "spark.compose.yml").read_text(encoding="utf-8"))
    section = _manual_section("### 7.2 The compose graph", "### 7.3 The entrypoint")
    missing = [name for name in compose["services"] if f"`{name}`" not in section]
    assert not missing, "USER_MANUAL.md §7.2 is missing compose services: " + ", ".join(missing)


def test_manual_gate_section_names_every_gate_step() -> None:
    """The manual's gate table must not silently omit a gate step."""
    script = (REPO_ROOT / "scripts" / "pre-merge-gate.sh").read_text(encoding="utf-8")
    steps = re.findall(r'run_step "([^"]+)"', script)
    assert steps, "scripts/pre-merge-gate.sh has no run_step calls"
    section = _manual_section("## 10. The gate", "## 11.")
    missing = [step for step in steps if f"`{step}`" not in section]
    assert not missing, "USER_MANUAL.md §10 is missing gate steps: " + ", ".join(missing)


def test_guard_protocol_lists_every_approval_field() -> None:
    """The narrative protocol must name every field in the machine-readable contract."""
    approval = json.loads((REPO_ROOT / "contracts" / "guard-approval.json").read_text(encoding="utf-8"))
    fields = approval["approval"]["fields"]
    protocol = (REPO_ROOT / "contracts" / "guard-protocol.md").read_text(encoding="utf-8")
    missing = [field for field in fields if f"`{field}`" not in protocol]
    assert not missing, "contracts/guard-protocol.md is missing approval fields: " + ", ".join(missing)


def test_manual_bundle_section_names_the_pinned_bundle_keys() -> None:
    """A verifiable bundle needs both the signing key and the pinned public key."""
    section = _manual_section("### 9.4 Bundles", "### 9.5 goSpark")
    for key in ("BUNDLE_SIGN_KEY", "BUNDLE_PUBKEY"):
        assert key in section, f"USER_MANUAL.md §9.4 no longer names {key}"


def test_manual_port_table_marks_master_ports_implemented() -> None:
    """The master-side file/vector ports are implemented, not spec-only."""
    section = _manual_section("### 7.4 The two port namespaces", "### 7.5 Bring-up")
    row = next((line for line in section.splitlines() if "4220" in line), "")
    assert "implemented" in row, "USER_MANUAL.md §7.4 no longer marks the master ports implemented"
