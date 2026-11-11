"""The release surface: `VERSION`, the generated SBOM and the `sparknet` CLI.

Three artifacts that only stay honest if something checks them:

1. **`VERSION` is the one version.** `pyproject.toml` repeats it for tooling, and
   the SBOM records it; a version that disagrees with itself is worse than none,
   because every consumer trusts a different copy.
2. **The SBOM is generated and fresh.** `make sbom-check` runs in the pre-merge
   gate and `make drift-check`; this file is what makes that gate meaningful by
   proving `--check` goes red on drift, not just green on a match.
3. **The CLI routes to the Makefile.** `scripts/sparknet` has no logic of its
   own; a test asserts each command maps to the right target, so the router
   cannot silently point at a target that no longer exists.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import tomllib
from sparknet_loader import load_by_path  # shared/ comes from conftest

pytestmark = pytest.mark.layout


REPO_ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = REPO_ROOT / "VERSION"
PYPROJECT = REPO_ROOT / "pyproject.toml"
SBOM_SCRIPT = REPO_ROOT / "scripts" / "sparknet-sbom.py"
SBOM = REPO_ROOT / "sbom" / "sparknet.cdx.json"
CLI = REPO_ROOT / "scripts" / "sparknet"
SKILLS_DIR = REPO_ROOT / ".opencode" / "skills"

SBOM_RUN = [sys.executable, str(SBOM_SCRIPT)]


def _load_sbom_module() -> object:
    return load_by_path("sparknet_sbom", SBOM_SCRIPT)


sbom_mod = _load_sbom_module()


def _version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def _sbom() -> dict:
    return json.loads(SBOM.read_text(encoding="utf-8"))


def _shipped_skill_count() -> int:
    return sum(1 for p in SKILLS_DIR.iterdir() if p.is_dir() and (p / "SKILL.md").is_file())


# --- 1. one version ------------------------------------------------------------


def test_version_file_is_a_clean_semver() -> None:
    assert VERSION_FILE.is_file(), "the root VERSION file is missing"
    version = _version()
    assert version.count(".") == 2, f"VERSION is not MAJOR.MINOR.PATCH: {version!r}"
    assert all(part.isdigit() for part in version.split(".")), version


def test_pyproject_version_matches_the_version_file() -> None:
    declared = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]
    assert declared == _version(), (
        f"pyproject.toml says {declared!r} but VERSION says {_version()!r} — one of them must move"
    )


def test_sbom_records_the_version_file() -> None:
    assert _sbom()["metadata"]["component"]["version"] == _version()


# --- 2. the SBOM is fresh, valid and complete ----------------------------------


def test_committed_sbom_is_fresh() -> None:
    proc = subprocess.run([*SBOM_RUN, "--check"], cwd=REPO_ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_sbom_is_valid_cyclonedx() -> None:
    doc = _sbom()
    assert doc["bomFormat"] == "CycloneDX"
    assert doc["specVersion"] == "1.5"
    assert doc["metadata"]["component"]["name"] == "sparknet"
    assert isinstance(doc["components"], list) and doc["components"]


def test_sbom_covers_the_runtime_dependency_and_every_skill() -> None:
    components = _sbom()["components"]
    by_name = {c["name"]: c for c in components}

    crypto = by_name.get("cryptography")
    assert crypto is not None, "the SBOM omits the one runtime dependency"
    constraint = {p["name"]: p["value"] for p in crypto["properties"]}
    assert constraint["sparknet:declared-constraint"], "cryptography has no constraint"
    assert crypto.get("purl") == "pkg:pypi/cryptography"

    skill_components = [
        c
        for c in components
        if any(p["name"] == "sparknet:kind" and p["value"] == "vendored-wiki-skill" for p in c.get("properties", []))
    ]
    assert len(skill_components) == _shipped_skill_count(), (
        f"the SBOM lists {len(skill_components)} skills but {_shipped_skill_count()} ship"
    )
    for component in skill_components:
        assert component["hashes"][0]["alg"] == "SHA-256"
        assert len(component["hashes"][0]["content"]) == 64, component["name"]

    expected_names = {"cryptography", "peer-skill-catalog", "master-skill-catalog"} | {
        p.name for p in SKILLS_DIR.iterdir() if (p / "SKILL.md").is_file()
    }
    assert set(by_name) == expected_names


def _spdx(component: dict) -> str:
    choice = component["licenses"][0]
    return choice.get("license", {}).get("id") or choice["expression"]


def test_sbom_records_the_license_each_component_actually_carries() -> None:
    """A BOM that guesses licenses is worse than one that admits it does not know.

    The suite is MIT, but `skill-creator` ships its own Apache-2.0 LICENSE.txt and
    local `wiki-audit` has no grant while the repo license (C1) is deferred.
    """
    by_name = {c["name"]: c for c in _sbom()["components"]}

    assert _spdx(by_name["skill-creator"]) == "Apache-2.0"
    assert _spdx(by_name["wiki-audit"]) == "NOASSERTION"
    assert _spdx(by_name["wiki-query"]) == "MIT"
    assert _spdx(_sbom()["metadata"]["component"]) == "NOASSERTION"

    skills = [
        c
        for c in by_name.values()
        if any(p["name"] == "sparknet:kind" and p["value"] == "vendored-wiki-skill" for p in c["properties"])
    ]
    assert len(skills) == _shipped_skill_count()
    for component in skills:
        assert component["licenses"], f"{component['name']} carries no license"
        props = {p["name"]: p["value"] for p in component["properties"]}
        assert props["sparknet:hash-scope"] == "tree"
        assert props["sparknet:license"] == _spdx(component)


def test_skill_hash_covers_files_beyond_skill_md(tmp_path: Path) -> None:
    """A changed reference file is drift even when SKILL.md is untouched."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root, text in ((first, "one"), (second, "two")):
        (root / "references").mkdir(parents=True)
        (root / "SKILL.md").write_text("identical\n", encoding="utf-8")
        (root / "references" / "notes.md").write_text(text, encoding="utf-8")

    assert sbom_mod._tree_sha256(first) == sbom_mod._tree_sha256(first)
    assert sbom_mod._tree_sha256(first) != sbom_mod._tree_sha256(second)


def test_sbom_local_skills_match_the_sync_manifest() -> None:
    """`LOCAL_SKILLS` is a copy of a fact the sync manifest already knows."""
    sync = json.loads((SKILLS_DIR / ".sync.json").read_text(encoding="utf-8"))
    local = {name for name, meta in sync["skills"].items() if meta.get("source") == "local"}
    assert local == set(sbom_mod.LOCAL_SKILLS), "scripts/sparknet-sbom.py's LOCAL_SKILLS drifted from .sync.json"


def test_role_catalog_fails_closed_on_a_malformed_inventory(tmp_path: Path) -> None:
    catalog = tmp_path / "peer-node" / ".opencode" / "skills"
    catalog.mkdir(parents=True)
    (catalog / ".inventory.json").write_text("{}", encoding="utf-8")
    try:
        sbom_mod._role_catalog(tmp_path, "peer")
    except ValueError as exc:
        assert "counts.skills" in str(exc)
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("a malformed role inventory was accepted")


def test_sbom_generation_is_deterministic() -> None:
    first = sbom_mod.render(sbom_mod.build(REPO_ROOT))
    second = sbom_mod.render(sbom_mod.build(REPO_ROOT))
    assert first == second
    assert first == SBOM.read_text(encoding="utf-8")


def test_sbom_does_not_embed_a_host_path() -> None:
    """The tree is relocatable; a generated file may not pin the dev checkout."""
    assert "/mnt/knowledge/sparknet" not in SBOM.read_text(encoding="utf-8")


def test_sbom_fails_closed_on_a_missing_version(tmp_path: Path) -> None:
    # build() reads VERSION before anything else, so an empty root is enough.
    try:
        sbom_mod.build(tmp_path)
    except ValueError as exc:
        assert "VERSION" in str(exc)
    else:  # pragma: no cover - the assertion above is the contract
        raise AssertionError("build() accepted a root with no VERSION")


# --- 3. the drift gate actually goes red ---------------------------------------


def test_check_fails_when_the_sbom_drifts(tmp_path: Path) -> None:
    out = tmp_path / "sparknet.cdx.json"
    assert subprocess.run([*SBOM_RUN, "--out", str(out)], cwd=REPO_ROOT).returncode == 0
    assert subprocess.run([*SBOM_RUN, "--check", "--out", str(out)], cwd=REPO_ROOT).returncode == 0

    out.write_text(out.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    drift = subprocess.run(
        [*SBOM_RUN, "--check", "--out", str(out)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert drift.returncode == 1
    assert "stale" in (drift.stdout + drift.stderr)


def test_check_fails_when_the_sbom_is_absent(tmp_path: Path) -> None:
    proc = subprocess.run(
        [*SBOM_RUN, "--check", "--out", str(tmp_path / "nope.json")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 1
    assert "missing" in (proc.stdout + proc.stderr)


def test_sbom_help_exits_zero_and_prints() -> None:
    proc = subprocess.run([*SBOM_RUN, "--help"], cwd=REPO_ROOT, capture_output=True, text=True)
    assert proc.returncode == 0
    assert proc.stdout.strip()


# --- 4. the CLI routes to the Makefile -----------------------------------------


def _run_cli(*args: str, dry: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    if dry:
        env["SPARKNET_DRY"] = "1"
    else:
        env.pop("SPARKNET_DRY", None)
    return subprocess.run(
        [str(CLI), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_is_executable() -> None:
    assert CLI.is_file()
    assert os.access(CLI, os.X_OK), "scripts/sparknet is not executable"


def test_cli_version_prints_the_version_file() -> None:
    proc = _run_cli("version", dry=False)
    assert proc.returncode == 0
    assert proc.stdout.strip() == _version()


def test_cli_help_exits_zero_and_prints() -> None:
    proc = _run_cli("--help")
    assert proc.returncode == 0
    assert "Usage:" in proc.stdout


def test_cli_routes_each_command_to_its_make_target() -> None:
    expected = {
        "validate": "validate",
        "test": "test-all",
        "contract-test": "contract-test",
        "lint": "lint",
        "format-check": "format-check",
        "render": "render",
        "render-check": "render-check",
        "drift-check": "drift-check",
        "sbom": "sbom",
        "sbom-check": "sbom-check",
        "keys-check": "keys-check",
        "shims-check": "shims-check",
        "wiki-verify": "wiki-verify",
        "layout": "layout",
    }
    for command, target in expected.items():
        proc = _run_cli(command)
        assert proc.returncode == 0, f"{command}: {proc.stderr}"
        assert f"make -C {REPO_ROOT} {target}" in proc.stdout, (
            f"`sparknet {command}` did not route to `make {target}`: {proc.stdout!r}"
        )


def test_cli_bundle_requires_a_known_role() -> None:
    ok = _run_cli("bundle", "peer")
    assert ok.returncode == 0
    assert f"make -C {REPO_ROOT} bundle ROLE=peer" in ok.stdout

    bad = _run_cli("bundle", "sidecar")
    assert bad.returncode == 2
    assert "peer|master" in bad.stderr


def test_cli_refuses_an_unknown_command() -> None:
    proc = _run_cli("frobnicate")
    assert proc.returncode == 2
    assert "unknown command" in proc.stderr


def test_cli_refuses_arguments_a_command_does_not_take() -> None:
    proc = _run_cli("validate", "--suites", "peer")
    assert proc.returncode == 2
    assert "unexpected argument" in proc.stderr


# --- 5. the bundle carries the data, not the fabric-root tools -----------------
# The staging and prune policy is now exercised through the release export
# module in tests/test_release_export.py; these source-text mirrors were the
# duplication the module exists to remove.
