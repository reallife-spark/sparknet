"""The GitHub workflows are a pinned mirror of the local gate, and nothing more.

Three rot vectors, all silent until a runner turns up:

1. **A floating action ref.** `uses: actions/checkout@v4` (or worse, `@main`)
   means the next upstream release changes what this repository executes, with
   no commit here to review. Everything is pinned to a full commit SHA, the way
   the dsx repos do it.
2. **CI drifting from the local gate.** Decision A5: the local pre-merge gate
   is authoritative and CI only mirrors it. So the gate workflow must *call*
   `make ci` — not re-list `lint`, `format-check`, `contract-test` and the rest,
   because a second copy of the vocabulary is a second thing to keep true.
3. **The script's vocabulary changing under the mirror.** If
   `scripts/pre-merge-gate.sh` gains or loses a step and the workflow does not
   know, the "mirror" is fiction. The step names are pinned here; a change to
   the script fails this test and forces the documentation decision.

The first real run on GitHub is a `DoD: confirm: user` item (PLAN Step 48);
these tests prove the workflows are shaped to run, not that GitHub ran them.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.layout


REPO_ROOT = Path(__file__).resolve().parent.parent
GOSPARK_ROOT = REPO_ROOT / "gospark"

#: A pinned action ref: `owner/repo[/path]@` + a full 40-hex commit SHA.
#: Moving tags (v4), branches (@main) and abbreviations are all rejected.
PINNED_USES = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._/-]+@[0-9a-f]{40}$")

#: The gate script's step names, in order. `scripts/pre-merge-gate.sh` prints
#: these; the workflow mirrors the script by calling `make ci`, so this tuple
#: is the vocabulary the mirror has to match. A deliberate edit to the script
#: must edit this line too — that is the point.
PRE_MERGE_GATE_STEPS = (
    "context-check",
    "governance-check",
    "phase8-check",
    "keys-check",
    "shims-check",
    "lint",
    "format-check",
    "shellcheck",
    "role-skills-check",
    "skills-check",
    "validate",
    "contract-test",
    "render-check",
    "sbom-check",
)
FULL_SUITE_STEP = "test-all"

#: Directories that hold workflows in the two repositories of the fabric.
WORKFLOW_DIRS = (REPO_ROOT / ".github" / "workflows", GOSPARK_ROOT / ".github" / "workflows")


def workflow_files() -> list[Path]:
    files = []
    for directory in WORKFLOW_DIRS:
        if directory.is_dir():
            files.extend(sorted(directory.glob("*.yml")))
            files.extend(sorted(directory.glob("*.yaml")))
    return files


def steps_of(workflow: dict) -> list[dict]:
    steps = []
    for job in (workflow.get("jobs") or {}).values():
        steps.extend(job.get("steps") or [])
    return steps


def uses_of(workflow: dict) -> list[str]:
    return [step["uses"] for step in steps_of(workflow) if "uses" in step]


def runs_of(workflow: dict) -> str:
    return "\n".join(step.get("run", "") for step in steps_of(workflow))


def display(path: Path) -> str:
    """`sparknet:.github/workflows/gate.yml`, not an absolute path in a failure."""
    for base, label in ((REPO_ROOT, "sparknet"), (GOSPARK_ROOT, "goSpark")):
        try:
            return f"{label}:{path.relative_to(base)}"
        except ValueError:
            continue
    return str(path)


@pytest.mark.parametrize("path", workflow_files(), ids=display)
def test_workflow_parses(path: Path):
    """A workflow that does not parse is a status check that never runs."""
    workflow = yaml.safe_load(path.read_text())
    assert isinstance(workflow, dict), f"{display(path)} is not a mapping"
    assert workflow.get("jobs"), f"{display(path)} has no jobs"


@pytest.mark.parametrize("path", workflow_files(), ids=display)
def test_every_action_is_pinned_to_a_commit_sha(path: Path):
    """No moving tags, no branches: `@v4` and `@main` are both unacceptable."""
    workflow = yaml.safe_load(path.read_text())
    offenders = [ref for ref in uses_of(workflow) if not PINNED_USES.match(ref)]
    assert not offenders, (
        f"{display(path)} has unpinned action refs: {offenders}. "
        f"Pin each to a 40-hex commit SHA with the tag as a trailing comment."
    )


@pytest.mark.parametrize("path", workflow_files(), ids=display)
def test_workflow_declares_minimum_permissions(path: Path):
    """Every workflow asks for `contents: read`, plus the two documented
    CodeQL exceptions: `security-events: write` to upload results, and
    `actions: read` so analyze() can read the workflow run it belongs to
    (without it that call 403s and the step fails as a "configuration error"
    even though the analysis succeeded)."""
    workflow = yaml.safe_load(path.read_text())
    permissions = workflow.get("permissions")
    allowed = (
        {"contents": "read"},
        {"contents": "read", "security-events": "write"},
        {"contents": "read", "actions": "read", "security-events": "write"},
    )
    assert permissions in allowed, (
        f"{display(path)} should declare "
        f"`permissions: {{contents: read}}` at the top (CodeQL's "
        f"security-events: write and actions: read are the documented "
        f"exceptions)."
    )
    if permissions and "actions" in permissions:
        assert path.name == "codeql.yml", (
            f"{display(path)} asks for actions: read, which only CodeQL needs to classify its own workflow run."
        )


def test_the_gate_workflows_call_the_local_gate():
    """CI mirrors the local gate by calling it, not by re-listing its checks."""
    for directory in WORKFLOW_DIRS:
        gate = directory / "gate.yml"
        if not gate.is_file():
            continue
        run = runs_of(yaml.safe_load(gate.read_text()))
        assert re.search(r"\bmake ci\b", run), (
            f"{display(gate)} must run `make ci` — the local "
            f"pre-merge gate is authoritative and the workflow mirrors it."
        )
        for name in (*PRE_MERGE_GATE_STEPS, FULL_SUITE_STEP):
            assert f"make {name}" not in run, (
                f"{display(gate)} re-implements the check "
                f"`make {name}` instead of calling `make ci`. A second copy of "
                f"the vocabulary is a second thing to keep true (decision A5)."
            )


def test_pre_merge_gate_script_matches_the_pinned_vocabulary():
    """The script's steps are exactly the documented set, in order."""
    script = (REPO_ROOT / "scripts" / "pre-merge-gate.sh").read_text()
    names = re.findall(r'run_step\s+"([^"]+)"', script)
    assert names == [*PRE_MERGE_GATE_STEPS, FULL_SUITE_STEP], (
        "scripts/pre-merge-gate.sh changed its step list; update "
        "PRE_MERGE_GATE_STEPS in this test (and the CI mirror note in "
        ".github/workflows/gate.yml) so the two stay the same document."
    )


def test_quick_mode_skips_the_full_suite():
    """`--quick` is what a PR runs; it must not silently run the whole suite."""
    script = (REPO_ROOT / "scripts" / "pre-merge-gate.sh").read_text()
    branches = re.search(r'if \[ "\$quick" -eq 1 \]; then\n(.*?)\nelse\n(.*?)\nfi', script, re.S)
    assert branches, "pre-merge-gate.sh no longer branches on --quick"
    quick_body, full_body = branches.group(1), branches.group(2)
    # The quick branch prints a SKIP banner that *names* test-all; what it must
    # not do is run it.
    assert 'run_step "test-all"' not in quick_body, "--quick must skip the full suite"
    assert 'run_step "test-all"' in full_body, "the full run must still include test-all"
