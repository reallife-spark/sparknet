"""Every vendored agent must be one opencode will actually load.

An agent opencode cannot see is not an error, it is an agent that does not exist
— and nothing in this repository would have said so. `make bundle-verify` checks
that agent files are *copied*; it never asks opencode what it can *read*, so the
set of working agents had no guard at all. These tests are that guard.

They also encode a trap that produced a confidently wrong conclusion once
already, recorded in PLAN.md Step 5. `opencode agent list` prints roughly 9 MB of
per-agent permission config. Read through a **pipe**, the tail is silently lost —
4.5 MB and four agents instead of 9.4 MB and nine — and the two entries that
disappear are the last two, which is exactly the shape of "the agent is missing".
Reading the same command through a file returns everything.

So the loader check below redirects to a file and bounds the read size. Without
that it would quietly degrade into a test that only ever validates a prefix, and
a prefix is exactly what fails to notice a missing tail.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = REPO_ROOT / ".opencode" / "agents"
LEGACY_DIR = REPO_ROOT / ".opencode" / "agent"
BUNDLE_SCRIPT = REPO_ROOT / "scripts" / "sparknet-bundle.sh"

# The agents this repository is supposed to provide. Kept explicit rather than
# derived from the directory, so that deleting the whole directory fails loudly
# instead of quietly shrinking the set to zero.
EXPECTED_AGENTS = {"vault", "sparknet-node", "build"}

# opencode's own agent-name rule, and the modes it will surface.
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
VALID_MODES = {"primary", "subagent", "all"}

# What `opencode agent list` prints before its (very large) per-agent permission
# dump. Parsed rather than JSON-decoded: the listing is not a single JSON
# document, and the permission block it follows is megabytes of noise.
LISTED_RE = re.compile(r"^([A-Za-z0-9_-]+) \((primary|subagent|all)\)$", re.MULTILINE)


def frontmatter(path: Path) -> dict[str, str]:
    """Parse the flat top-level frontmatter of an agent file.

    Deliberately hand-rolled: the repository has no YAML dependency, and the keys
    checked here (`description`, `mode`) are flat scalars. Nested values are
    ignored rather than half-parsed, so a future block cannot make this lie.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    fields: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def test_agents_directory_is_plural():
    """The documented path, kept singular-free so the bundle cannot drift back."""
    assert AGENTS_DIR.is_dir(), f"missing {AGENTS_DIR} — the documented path is `.opencode/agents/`"
    assert not LEGACY_DIR.exists(), (
        f"{LEGACY_DIR} exists as well. opencode 1.18.34 accepts either spelling, so this is "
        "duplication rather than breakage — but two directories of agents means one of them "
        "stops being maintained without anything noticing. Keep the documented plural path."
    )


def test_documented_agents_are_present():
    present = {p.stem for p in AGENTS_DIR.glob("*.md")}
    missing = EXPECTED_AGENTS - present
    assert not missing, f"missing agent file(s): {sorted(missing)} in {AGENTS_DIR}"


def test_build_is_the_primary_mode_not_lead():
    """The operator-facing Build mode must not be shadowed by an accidental Lead."""
    assert not (AGENTS_DIR / "lead.md").exists(), (
        "lead.md is still present; opencode will surface a second primary mode and "
        "the Build mode can appear renamed to Lead"
    )
    fields = frontmatter(AGENTS_DIR / "build.md")
    assert fields.get("mode") == "primary", f"build.md must be a primary mode, found {fields.get('mode')!r}"


@pytest.mark.parametrize("path", sorted(AGENTS_DIR.glob("*.md")), ids=lambda p: p.stem)
def test_agent_is_loadable(path: Path):
    """A file opencode will refuse is worse than no file: it looks intentional."""
    assert NAME_RE.match(path.stem), (
        f"{path.name}: opencode will not surface an agent whose name is not lowercase kebab-case"
    )
    fields = frontmatter(path)
    assert fields, f"{path.name}: no parseable frontmatter — opencode needs a `---` block"
    assert fields.get("description"), (
        f"{path.name}: no description. This is what an agent picker shows and what "
        "decides whether the agent is ever chosen."
    )
    assert fields.get("mode") in VALID_MODES, (
        f"{path.name}: mode={fields.get('mode')!r} is not one of {sorted(VALID_MODES)}"
    )


def test_bundle_script_ships_the_plural_agents_path():
    """The bundle is the delivery mechanism; a stale path there un-fixes the fix."""
    script = BUNDLE_SCRIPT.read_text(encoding="utf-8")
    assert ".opencode/agents" in script, (
        "sparknet-bundle.sh does not reference .opencode/agents — it would ship the agents to a path opencode ignores"
    )
    # Allow the plural, reject the singular, without tripping over the plural.
    stale = re.findall(r"\.opencode/agent(?![s/])", script)
    assert not stale, f"sparknet-bundle.sh still references the ignored singular path: {stale}"


def test_opencode_resolves_every_vendored_agent():
    """Ask the loader, not the filesystem.

    This is the question nothing in the repository was asking: not "is the file
    present" but "can opencode see it". It is deliberately the only check here
    that shells out, because it is the only one that can fail while every file
    is exactly where it should be.
    """
    binary = shutil.which("opencode")
    if binary is None:
        pytest.skip("opencode is not installed; the loader cannot be asked")

    # Redirect to real files rather than capture_output/PIPE. `opencode agent
    # list` prints roughly 9 MB of per-agent permission config, and on a
    # non-seekable pipe the tail is lost: through a pipe it yielded 4.5 MB and
    # four agents, through a file the same command yields 9.4 MB and nine. That
    # truncation is silent and would have quietly reduced this test to checking
    # a prefix, which is how a test like this rots into a test that passes.
    with (
        tempfile.TemporaryFile(mode="w+", encoding="utf-8") as out,
        tempfile.TemporaryFile(mode="w+", encoding="utf-8") as err,
    ):
        result = subprocess.run(
            [binary, "agent", "list"],
            cwd=REPO_ROOT,  # CWD matters: this resolves *this project's* agents.
            stdout=out,
            stderr=err,
            timeout=180,
        )
        out.seek(0)
        listing = out.read()
        err.seek(0)
        errors = err.read()

    assert result.returncode == 0, f"opencode agent list failed: {errors.strip()[:2000]}"
    # A truncated read is the failure mode that matters here, so bound it
    # explicitly rather than trusting the parse to notice a missing tail.
    assert len(listing) > 1_000_000, (
        f"opencode agent list returned only {len(listing)} bytes; expected the full "
        "listing. A short read means the output was truncated and this check is not "
        "proving what it claims."
    )

    listed = {name for name, _mode in LISTED_RE.findall(listing)}
    missing = EXPECTED_AGENTS - listed
    assert not missing, (
        f"opencode cannot see {sorted(missing)}. The files exist, so the directory or "
        f"the frontmatter is wrong — opencode reads `.opencode/agents/`. Listed: {sorted(listed)}"
    )
