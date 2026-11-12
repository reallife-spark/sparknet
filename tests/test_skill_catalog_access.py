"""The skill catalog is deterministic, role-scoped and safe to load."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "shared"))

from skill_catalog import engine  # noqa: E402

CATALOG = load_by_path("skill_catalog_access_reader", REPO_ROOT / "shared" / "sparknet-skill-catalog.py")
POLICY = json.loads((REPO_ROOT / "contracts" / "skill-policy.json").read_text(encoding="utf-8"))

pytestmark = pytest.mark.layout


def _skill(root: Path, name: str, description: str = "Use when testing.", group_manifest: str = "") -> Path:
    path = root / name
    path.mkdir(parents=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    (path / "references").mkdir()
    (path / "references" / "guide.md").write_text("guide\n", encoding="utf-8")
    return path


def test_catalog_is_sorted_group_then_id(tmp_path: Path) -> None:
    _skill(tmp_path, "zeta")
    _skill(tmp_path, "alpha")
    catalog = engine.build_catalog(
        tmp_path,
        role="base",
        group_for=lambda name, source: "wiki" if name.startswith("a") else "engineering",
        metadata_for=lambda name: {"license": "MIT", "source_repo": "local"},
        group_order=("wiki", "engineering"),
    )
    assert catalog["order"] == ["alpha", "zeta"]
    assert catalog["groups"]["wiki"]["skills"] == ["alpha"]
    assert catalog["groups"]["engineering"]["skills"] == ["zeta"]
    assert catalog["skills"]["alpha"]["path"] == "alpha/SKILL.md"
    assert catalog["skills"]["alpha"]["sha256"] == engine.file_digest(tmp_path / "alpha" / "SKILL.md")


def test_catalog_rejects_a_skill_without_description(tmp_path: Path) -> None:
    skill = tmp_path / "empty"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: empty\n---\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing description"):
        engine.catalog_entry(skill, role="base", source_repo="local", license="MIT", group="other")


def test_catalog_refuses_a_path_escape(tmp_path: Path) -> None:
    _skill(tmp_path, "safe")
    catalog = engine.build_catalog(
        tmp_path,
        role="base",
        group_for=lambda _name, _source: "other",
        metadata_for=lambda _name: {},
    )
    catalog["skills"]["safe"]["path"] = "../outside/SKILL.md"
    path = tmp_path / ".catalog.json"
    engine.write_catalog(path, catalog)
    reader = CATALOG.Catalog([path])
    with pytest.raises(CATALOG.CatalogError, match="escapes"):
        reader.path("safe")


def test_denied_group_is_not_visible(tmp_path: Path) -> None:
    _skill(tmp_path, "redteam-skill")
    catalog = engine.build_catalog(
        tmp_path,
        role="master",
        group_for=lambda _name, _source: "redteam",
        metadata_for=lambda _name: {},
    )
    path = tmp_path / ".catalog.json"
    engine.write_catalog(path, catalog)
    assert "redteam-skill" in CATALOG.Catalog([path]).entries
    assert "redteam-skill" not in CATALOG.Catalog([path], denied_groups=["redteam"]).entries


def test_search_and_load_round_trip(tmp_path: Path) -> None:
    _skill(tmp_path, "wiki-ingest", "Ingest a source into the wiki.")
    catalog = engine.build_catalog(
        tmp_path,
        role="base",
        group_for=lambda _name, _source: "wiki",
        metadata_for=lambda _name: {},
    )
    path = tmp_path / ".catalog.json"
    engine.write_catalog(path, catalog)
    reader = CATALOG.Catalog([path])
    assert reader.search("wiki ingest", 3)[0]["id"] == "wiki-ingest"
    body, skill_dir = reader.load("wiki-ingest")
    assert body.startswith("---")
    assert (skill_dir / "references" / "guide.md").is_file()
    body, _ = reader.load("wiki-ingest", "references/guide.md")
    assert "guide" in body


def test_mcp_search_and_load() -> None:
    request = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "skills_search", "arguments": {"query": "wiki ingest", "limit": 1}},
                }
            ),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "skills_load", "arguments": {"name": "wiki-ingest"}},
                }
            ),
        ]
    )
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "shared" / "sparknet-skills-mcp.py"),
            "--catalog",
            str(REPO_ROOT / ".opencode" / "skills" / ".catalog.json"),
        ],
        input=request + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    replies = {json.loads(line)["id"]: json.loads(line) for line in result.stdout.splitlines() if line.strip()}
    assert "wiki-ingest" in replies[2]["result"]["content"][0]["text"]
    assert "<skill_content" in replies[3]["result"]["content"][0]["text"]


def test_repository_catalogs_are_current() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "sparknet-skills.py"), "check", "--role", "all"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_featured_ids_exist_in_the_effective_catalog() -> None:
    for role in ("base", "peer", "master"):
        paths = [REPO_ROOT / ".opencode" / "skills" / ".catalog.json"]
        if role != "base":
            paths.append(REPO_ROOT / f"{role}-node" / ".opencode" / "skills" / ".catalog.json")
        reader = CATALOG.Catalog(paths)
        featured = [*POLICY["featured"]["base"], *POLICY["featured"].get(role, [])][: POLICY["featured_limit"]]
        for name in featured:
            assert name in reader.entries, f"{role}: featured skill not installed: {name}"


@pytest.mark.parametrize("role", ["base", "peer", "master"])
def test_opencode_allows_only_the_featured_set(role: str) -> None:
    path = REPO_ROOT / "opencode.json" if role == "base" else REPO_ROOT / f"{role}-node" / "opencode.json"
    config = json.loads(path.read_text(encoding="utf-8"))
    allowed = {name for name, effect in config["permission"]["skill"].items() if name != "*" and effect == "allow"}
    featured = [*POLICY["featured"]["base"], *POLICY["featured"].get(role, [])][: POLICY["featured_limit"]]
    assert allowed == set(featured), f"{role}: permission.skill drifted from skill-policy.json"


@pytest.mark.parametrize("role", ["peer", "master"])
def test_role_configs_include_the_base_suite(role: str) -> None:
    config = json.loads((REPO_ROOT / f"{role}-node" / "opencode.json").read_text(encoding="utf-8"))
    assert "../.opencode/skills" in config["skills"]["paths"]


def test_engine_skill_runtime_is_role_scoped(tmp_path: Path) -> None:
    import argparse

    engine_module = load_by_path(
        "skill_catalog_engine_access",
        REPO_ROOT / "peer-node" / "services" / "sparknet-opencode-engine.py",
    )
    args = argparse.Namespace(
        role="master",
        knowledge_root=str(tmp_path / "knowledge"),
        single_vault="",
        state_root=str(tmp_path / "state"),
        image="sparknet-opencode-runtime:2.2.5",
        docker="docker",
        sandbox_backend="docker",
        openshell="openshell",
        openshell_user="",
        openshell_owner_file="",
        vm_image="x",
        forward_base=14200,
        port_base=4300,
        proxy_port=11500,
        model_upstream="http://127.0.0.1:11434",
        sandbox_memory="2g",
        sandbox_cpus="2",
        idle_seconds=1800,
        config_template=str(REPO_ROOT / "peer-node" / "configs" / "opencode-engine" / "opencode.json.template"),
        model_id="m",
        small_model="s",
    )
    manager = engine_module.SandboxManager(args)
    mcp, permission = manager._skill_runtime()
    assert mcp["type"] == "local"
    assert "/opt/sparknet/skill-catalog/base/.catalog.json" in mcp["command"]
    assert "/opt/sparknet/skill-catalog/role/.catalog.json" in mcp["command"]
    assert "--deny-group" in mcp["command"]
    assert "security" in mcp["command"]
    assert permission["*"] == "deny"
    assert sum(1 for name in permission if name != "*") == POLICY["featured_limit"]
