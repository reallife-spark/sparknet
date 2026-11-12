"""The vendored wiki skill suite must stay loadable, portable and accounted for.

These tests exist because the suite is *vendored*, which means it can rot in
three ways a global skill farm never could: a file can be edited until it names
a host path that does not exist on a node, an excluded skill can reappear, and
a reference can dangle after an upstream sync. None of those fail loudly at
runtime — they fail as a node quietly writing to the wrong place.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration


REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / ".opencode" / "skills"
SYNC_STATE = SKILLS_DIR / ".sync.json"
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync-wiki-skills.py"
PATCH_DIR = REPO_ROOT / "scripts" / "wiki-skill-patches"

# A skill opencode will actually surface: name matches its folder, description
# present. Mirrors the loader's rules, because a skill that fails them is
# invisible — no error, just a command that silently does not exist.
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Kept in sync with scripts/sync-wiki-skills.py by
# test_exclusion_list_matches_the_sync_script.
EXPECTED_EXCLUSIONS = {
    "rlspark-sourcewatch",
    "memory-bridge",
    "wiki-agent",
    "wiki-history-ingest",
}

# Authored in-repo rather than vendored from the farm. Kept in sync with
# scripts/sync-wiki-skills.py by test_local_skill_list_matches_the_sync_script.
EXPECTED_LOCAL_SKILLS = {
    "wiki-audit",
    "setup-deep-modules",
}

# Referenced by vendored skills but deliberately not shipped. Pre-existing
# upstream references; see .opencode/skills/README.md. If an upstream sync
# resolves or adds one, this test fails so the README gets updated on purpose.
EXPECTED_DANGLING = {
    "daily-update": {"wiki-history-ingest", "wiki-daily", "wiki-notify"},
    "impl-validator": {"memory-bridge"},
    "llm-wiki": {"claude-history-ingest", "codex-history-ingest"},
    "wiki-ingest": {"claude-history-ingest"},
    "wiki-rebuild": {"claude-history-ingest", "codex-history-ingest"},
    "wiki-setup": {"claude-history-ingest", "codex-history-ingest", "wiki-stop-capture", "wiki-vault"},
    "wiki-status": {"claude-history-ingest", "codex-history-ingest"},
}

SKILL_REF_RE = re.compile(
    r"\b(wiki-[a-z-]+|llm-wiki|cross-linker|tag-taxonomy|memory-bridge"
    r"|vault-skill-factory|graph-colorize|orchestrator-markdown|orchestrator-bases"
    r"|orchestrator-cli|json-canvas|impl-validator|skill-creator|daily-update|defuddle"
    r"|[a-z]+-history-ingest)\b"
)

# Same rule as the sync script, and for the same reason: a generic /home/ or
# /Users/ rule fires on the docs' own placeholder examples.
HOST_MARKERS = ("/mnt/knowledge/", "/mnt/nvme/", "/opt/raxxar", "/home/raxxar", "/srv/raxxar")
HOME_PLACEHOLDERS = {
    "me",
    "name",
    "you",
    "your",
    "user",
    "username",
    "someone",
    "somebody",
    "u",
    "x",
    "example",
    "test",
    "default",
    "nobody",
}
HOME_RE = re.compile(r"/(?:home|Users)/([^/\s\"'`]+)")

SKILL_DIRS = sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()) if SKILLS_DIR.is_dir() else []


def frontmatter(skill_md: Path) -> dict[str, str]:
    """Parse the YAML frontmatter opencode reads. Tolerant by design: the point
    is to assert the required keys are present, not to be a YAML parser."""
    text = skill_md.read_text()
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end]
    out: dict[str, str] = {}
    key = None
    for line in block.splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if match:
            key = match.group(1)
            out[key] = match.group(2).strip()
        elif key and line.strip():
            out[key] += " " + line.strip()
    return out


# --- the suite exists and is loadable ----------------------------------------


def test_skills_are_vendored_in_the_repo():
    assert SKILLS_DIR.is_dir(), (
        f"{SKILLS_DIR} missing — the suite must ship with the vault so a node "
        f"can run it without a global skill farm (make wiki-sync)"
    )
    assert len(SKILL_DIRS) >= 25, f"only {len(SKILL_DIRS)} skills vendored"


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_skill_has_frontmatter_opencode_will_load(skill_dir: Path):
    """opencode filters out any skill without a name and description."""
    meta = frontmatter(skill_dir / "SKILL.md")
    assert meta, f"{skill_dir.name}: no parseable frontmatter"
    name = meta.get("name", "")
    description = meta.get("description", "")

    assert name, f"{skill_dir.name}: frontmatter has no `name`"
    assert name == skill_dir.name, (
        f"{skill_dir.name}: frontmatter name is {name!r} — opencode requires the "
        f"folder name to match, or the skill registers under the wrong name"
    )
    assert NAME_RE.match(name), f"{skill_dir.name}: name must be lowercase-hyphenated"
    assert len(name) <= 64, f"{skill_dir.name}: name exceeds 64 chars"
    assert description, f"{skill_dir.name}: frontmatter has no `description`"
    assert len(description) > 40, (
        f"{skill_dir.name}: description is too thin to trigger on — it must say what the skill does AND when to use it"
    )


# --- portability ---------------------------------------------------------------


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_no_host_paths_in_vendored_skill(skill_dir: Path):
    """A vendored skill naming a host path breaks silently on a node."""
    offenders: list[str] = []
    for path in sorted(skill_dir.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(SKILLS_DIR)
        for marker in HOST_MARKERS:
            if marker in text:
                offenders.append(f"{rel}: {marker}")
        for match in HOME_RE.finditer(text):
            if match.group(1).lower() not in HOME_PLACEHOLDERS:
                offenders.append(f"{rel}: {match.group(0)}")
    assert not offenders, "host paths in a vendored skill:\n  " + "\n  ".join(offenders)


def test_no_symlinks_in_vendored_skills():
    """Symlinks are how the 40-deep self-referential chain got in.

    A vendored symlink either dangles on the node or points outside the repo.
    """
    links = [str(p.relative_to(SKILLS_DIR)) for p in SKILLS_DIR.rglob("*") if p.is_symlink()]
    assert not links, f"symlinks must not be vendored: {links}"


# --- the sync contract ---------------------------------------------------------


def test_sync_state_is_present_and_current():
    assert SYNC_STATE.is_file(), "no .sync.json — run make wiki-sync"
    state = json.loads(SYNC_STATE.read_text())
    assert state["license"] == "MIT"
    assert state["upstream"].startswith("https://")
    assert re.fullmatch(r"[0-9a-f]{7,40}", state["upstream_commit"])
    assert state["skills"], "no skills recorded"


def test_sync_check_passes():
    """The drift check is the guard; if it fails, the vendored copy is stale."""
    proc = subprocess.run(
        [sys.executable, str(SYNC_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"vendoring is stale:\n{proc.stdout}\n{proc.stderr}"


def test_exclusion_list_matches_the_sync_script():
    """The README, the tests and the script must agree on what is withheld."""
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import importlib.util,sys;"
            f"spec=importlib.util.spec_from_file_location('sync', r'{SYNC_SCRIPT}');"
            f"m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
            f"print('\\n'.join(sorted(m.EXCLUSIONS)))",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    from_script = set(proc.stdout.split())
    assert from_script == EXPECTED_EXCLUSIONS, (
        f"sync script excludes {sorted(from_script)}, tests expect {sorted(EXPECTED_EXCLUSIONS)}"
    )


@pytest.mark.parametrize("name", sorted(EXPECTED_EXCLUSIONS))
def test_excluded_skill_is_actually_absent(name: str):
    assert not (SKILLS_DIR / name).exists(), (
        f"{name} is excluded but vendored — either the exclusion or the copy is wrong"
    )


def test_local_skill_list_matches_the_sync_script():
    """The tests and the sync script must agree on which skills are in-repo.

    A local skill is authored under .opencode/skills/ and records `source:
    "local"` in .sync.json. If the list drifts, an in-repo skill could be
    pruned by the next --apply (or an unexpected local skill could linger
    unrecorded).
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import importlib.util,sys;"
            f"spec=importlib.util.spec_from_file_location('sync', r'{SYNC_SCRIPT}');"
            f"m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);"
            f"print('\\n'.join(sorted(m.LOCAL_SKILLS)))",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    from_script = set(proc.stdout.split())
    assert from_script == EXPECTED_LOCAL_SKILLS, (
        f"sync script local skills {sorted(from_script)}, tests expect {sorted(EXPECTED_LOCAL_SKILLS)}"
    )


@pytest.mark.parametrize("name", sorted(EXPECTED_LOCAL_SKILLS))
def test_local_skill_is_present_and_recorded_as_local(name: str):
    skill_md = SKILLS_DIR / name / "SKILL.md"
    assert skill_md.is_file(), f"{name}: local skill missing SKILL.md"
    state = json.loads(SYNC_STATE.read_text())
    recorded = state["skills"].get(name)
    assert recorded is not None, f"{name}: not recorded in .sync.json"
    assert recorded.get("source") == "local", f"{name}: recorded as {recorded.get('source')} — must be 'local'"


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=lambda p: p.name)
def test_dangling_references_are_known(skill_dir: Path):
    """An unexpected dangling reference means upstream moved and the README lies."""
    vendored = {p.name for p in SKILL_DIRS}
    text = (skill_dir / "SKILL.md").read_text()
    refs = set(SKILL_REF_RE.findall(text)) - {skill_dir.name}
    missing = {r for r in refs if r not in vendored}
    expected = EXPECTED_DANGLING.get(skill_dir.name, set())
    assert missing == expected, (
        f"{skill_dir.name}: dangling refs {sorted(missing)}, expected "
        f"{sorted(expected)} — update .opencode/skills/README.md if upstream changed"
    )


def test_every_patch_applies_to_pristine_upstream():
    """A patch that no longer applies is a silently dropped local fix."""
    for patch in sorted(PATCH_DIR.glob("*.patch")):
        name = patch.stem
        state = json.loads(SYNC_STATE.read_text())
        assert name in state["skills"], f"patch exists for non-vendored skill: {name}"
        applied = {Path(entry).name for entry in state["patches"].get(name, [])}
        assert patch.name in applied, (
            f"{patch.name} exists but was not recorded as applied in .sync.json "
            f"(recorded: {sorted(applied) or 'none'}) — re-run make wiki-sync"
        )


def test_readme_documents_exclusions_and_provenance():
    readme = (SKILLS_DIR / "README.md").read_text()
    for name in EXPECTED_EXCLUSIONS:
        assert name in readme, f"{name} is excluded but absent from the vendored README"
    for token in ("Upstream", "MIT", "wiki-sync", "wiki-verify"):
        assert token in readme, f"vendored README does not mention {token}"
    assert (SKILLS_DIR / "LICENSE").is_file(), "MIT license text must ship with the vendored copy"


# --- the editor rebrand: what may still say the old name, and why --------------

# The vault's editor was rebranded to "orchestrator" by the sync script's dialect
# rewrite. What survives is the *product*, which this repo does not own and
# cannot rename: its config directory, its CLI, its documentation URLs and its
# upstream repository. Each pattern below is one of those, and a match outside
# them means the dialect missed a mention or someone reintroduced the old name
# as ours.
OBSIDIAN_EXTERNAL_ARTIFACTS = (
    re.compile(r"\.obsidian"),  # the editor's own config directory
    re.compile(r"obsidian-wiki"),  # the upstream repository this suite is vendored from
    re.compile(r"obsidian-skills|opencode-obsidian"),  # external repositories in the role catalog registry
    re.compile(r"obsidian\.md|obsidianmd"),  # documentation and GitHub-org URLs
    re.compile(r"Obsidian CLI"),  # the external command-line tool some skills drive
    re.compile(r"obsidian-(?:bases|cli|markdown)"),  # upstream skill names the dialect maps FROM
)

# Files whose entire job is the rename, so they must name what they rename from.
OBSIDIAN_RENAME_MECHANISM = {
    "scripts/sync-wiki-skills.py",
    ".opencode/skills/README.md",
    ".opencode/skills/.sync.json",
}

# A generated snapshot of the host it was captured on. Its PATH names a real
# directory; rewriting the value would make the manifest lie about the machine.
# Recorded as by-design in log.md (2026-10-08, EXPANSION Phase G).
OBSIDIAN_HOST_SNAPSHOTS = {"peer-node/manifests/user-env-manifest.json"}

# Append-only history states what was true when it was written and is never
# rewritten to suit a later rename.
OBSIDIAN_HISTORY_PARTS = {"log.md", "sessions", "journal", "02_Daily"}


def _ours_with_old_editor_name() -> list[tuple[str, int, str]]:
    out: list[tuple[str, int, str]] = []
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".md", ".json", ".sh", ".yml", ".yaml", ".service"}:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        parts = set(rel.split("/"))
        if parts & {
            "__pycache__",
            ".git",
            ".venv",
            "dist",
            "node_modules",
            ".pytest_cache",
            ".ruff_cache",
            "gospark",
            "peer-node",
            "master-node",
            "goagx",
        }:
            continue
        if parts & OBSIDIAN_HISTORY_PARTS:
            continue
        if path == Path(__file__).resolve():
            continue  # this file names the boundary it enforces
        if rel.startswith(".opencode/skills/") or "/.opencode/skills/" in rel or rel in OBSIDIAN_RENAME_MECHANISM:
            continue  # vendored (base or role-local) or the dialect itself
        if rel in OBSIDIAN_HOST_SNAPSHOTS:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            if "obsidian" in line.lower():
                out.append((rel, lineno, line.strip()))
    return out


def test_the_old_editor_name_survives_only_as_an_external_artifact() -> None:
    """Our own files name the editor only where the product itself is meant.

    The rebrand is applied by `scripts/sync-wiki-skills.py`'s dialect rewrite,
    which deliberately leaves four categories alone because they are real
    external artifacts rather than sparknet prose. This asserts that boundary
    holds in the files *we* author, so the rebrand cannot quietly regress and so
    the exemptions stay a short, reviewable list instead of a shrug.

    The vendored suite is not swept here: it is pinned by sha256 and verified by
    `make wiki-verify`, and hand-editing it would break that pin.
    """
    offenders = [
        (rel, lineno, line)
        for rel, lineno, line in _ours_with_old_editor_name()
        if not any(pattern.search(line) for pattern in OBSIDIAN_EXTERNAL_ARTIFACTS)
    ]
    assert not offenders, (
        "the editor was rebranded to 'orchestrator'; these mentions name neither an "
        "external artifact nor an exempt file:\n"
        + "\n".join(f"  {rel}:{lineno}: {line[:110]}" for rel, lineno, line in offenders)
    )


def test_the_rebrand_exemptions_are_still_narrow() -> None:
    """An exemption list that grows silently stops being an exemption list."""
    expected_mechanism = {
        "scripts/sync-wiki-skills.py",
        ".opencode/skills/README.md",
        ".opencode/skills/.sync.json",
    }
    expected_snapshots = {"peer-node/manifests/user-env-manifest.json"}
    assert expected_mechanism == OBSIDIAN_RENAME_MECHANISM, (
        "the rename-mechanism exemptions changed; an entry belongs there only if the file's whole job is the rename"
    )
    assert expected_snapshots == OBSIDIAN_HOST_SNAPSHOTS, (
        "the host-snapshot exemptions changed; only a generated snapshot of a real host belongs there"
    )
    for rel in OBSIDIAN_RENAME_MECHANISM | OBSIDIAN_HOST_SNAPSHOTS:
        assert (REPO_ROOT / rel).is_file(), f"exempt file {rel} no longer exists; drop the exemption"
    # The sweep must actually reach files, or it passes vacuously.
    assert len(_ours_with_old_editor_name()) >= 3, "the sweep found almost nothing; its glob is broken"


# --- vault scoping: the part that silently files knowledge in the wrong place --


@pytest.mark.parametrize("role", ["peer", "master"])
def test_role_env_example_points_at_its_own_vault(role: str):
    example = REPO_ROOT / f"{role}-node" / ".env.example"
    assert example.is_file(), f"{role}-node/.env.example missing"
    text = example.read_text()
    assert "VAULT_PATH=" in text
    # The template must be role-specific, or env-init writes a path pointing at
    # the other role or at the fabric root.
    assert f"{role}-node" in text, f"{role}-node/.env.example does not name its own vault"


def test_role_preflight_rejects_a_missing_role_env(tmp_path: Path):
    """The core trap: no role .env means the skills fall back to the parent.

    Reproduces a fresh clone, where `.env` is gitignored and therefore absent,
    and asserts the preflight refuses rather than letting the session target the
    fabric vault.
    """
    repo = tmp_path / "repo"
    (repo / "peer-node").mkdir(parents=True)
    (repo / "master-node").mkdir(parents=True)
    for role in ("peer", "master"):
        (repo / f"{role}-node" / "AGENTS.md").write_text("charter\n")
    (repo / "peer-node" / ".env").write_text(f'VAULT_PATH="{repo}"\n')  # parent fallback
    (repo / "scripts").mkdir()
    (repo / "scripts" / "sparknet-wiki-env.sh").write_text((REPO_ROOT / "scripts" / "sparknet-wiki-env.sh").read_text())

    proc = subprocess.run(
        ["bash", "-c", f"cd '{repo}/peer-node' && source '{repo}/scripts/sparknet-wiki-env.sh'"],
        capture_output=True,
        text=True,
        check=False,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode != 0, (
        "preflight passed with no peer .env — the skills would have resolved the "
        "parent vault and filed peer knowledge there"
    )
    assert "env-init" in proc.stdout + proc.stderr, "failure should say how to fix it"


@pytest.mark.parametrize("role", ["peer", "master"])
def test_preflight_accepts_a_correct_role_env(role: str, tmp_path: Path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "sparknet-wiki-env.sh").write_text((REPO_ROOT / "scripts" / "sparknet-wiki-env.sh").read_text())
    role_dir = repo / f"{role}-node"
    role_dir.mkdir()
    (role_dir / "AGENTS.md").write_text("charter\n")
    (role_dir / ".env").write_text(f'VAULT_PATH="{role_dir}"\n')
    (role_dir / "_raw").mkdir()

    proc = subprocess.run(
        ["bash", "-c", f"cd '{role_dir}' && source '{repo}/scripts/sparknet-wiki-env.sh'"],
        capture_output=True,
        text=True,
        check=False,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"role         : {role}" in proc.stdout
    assert f"VAULT_PATH   : {role_dir}" in proc.stdout


def test_preflight_rejects_an_env_pointing_elsewhere(tmp_path: Path):
    """A role .env whose VAULT_PATH names another vault is a config error.

    It is also the state a bundled machine-local .env would leave behind, which
    is why the bundle excludes it.
    """
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "sparknet-wiki-env.sh").write_text((REPO_ROOT / "scripts" / "sparknet-wiki-env.sh").read_text())
    role_dir = repo / "peer-node"
    other = repo / "master-node"
    role_dir.mkdir()
    other.mkdir()
    (role_dir / "AGENTS.md").write_text("charter\n")
    (other / "AGENTS.md").write_text("charter\n")
    (role_dir / ".env").write_text(f'VAULT_PATH="{other}"\n')
    (other / "_raw").mkdir()

    proc = subprocess.run(
        ["bash", "-c", f"cd '{role_dir}' && source '{repo}/scripts/sparknet-wiki-env.sh'"],
        capture_output=True,
        text=True,
        check=False,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert proc.returncode != 0, "preflight accepted a peer .env pointing at the master vault"
    assert "VAULT_PATH" in proc.stdout + proc.stderr
