"""The identity pages are part of the template, not deployment state.

`MISSION.md` says why a scope exists; `INTENT.md` is the design contract behind
it. Both ship at a role root, both are unsigned governance (not provenance-signed
notes), and both must be present in the fabric root, `peer-node/` and
`master-node/` before a deployment can be called runnable.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.layout


REPO_ROOT = Path(__file__).resolve().parent.parent
SCOPES = {
    "fabric": REPO_ROOT,
    "peer": REPO_ROOT / "peer-node",
    "master": REPO_ROOT / "master-node",
}
IDENTITY_FILES = ("MISSION.md", "INTENT.md")
BUILD_STATUSES = ("built", "partially-built", "unbuilt", "preserved-not-wired")


def frontmatter(path: Path) -> dict[str, str]:
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


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("name", IDENTITY_FILES)
def test_identity_page_exists_at_the_scope_root(scope: str, name: str) -> None:
    path = SCOPES[scope] / name
    assert path.is_file(), f"{path.relative_to(REPO_ROOT)} is missing"
    assert path.stat().st_size > 0, f"{path.relative_to(REPO_ROOT)} is empty"


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("name", IDENTITY_FILES)
def test_identity_page_declares_its_role_and_template_flag(scope: str, name: str) -> None:
    fields = frontmatter(SCOPES[scope] / name)
    assert fields.get("role") == scope, f"{scope}/{name} must declare role: {scope}, found {fields.get('role')!r}"
    assert fields.get("template") == "true", (
        f"{scope}/{name} must declare template: true so it is not mistaken for live state"
    )


@pytest.mark.parametrize("scope", SCOPES)
def test_intent_declares_a_design_contract(scope: str) -> None:
    fields = frontmatter(SCOPES[scope] / "INTENT.md")
    assert fields.get("intent") == "design-contract", f"{scope}/INTENT.md must declare intent: design-contract"


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("name", IDENTITY_FILES)
def test_identity_page_has_no_absolute_host_path(scope: str, name: str) -> None:
    text = (SCOPES[scope] / name).read_text(encoding="utf-8")
    assert "/mnt/knowledge" not in text, (
        f"{scope}/{name} hard-codes the development checkout path; resolve the vault at runtime"
    )


@pytest.mark.parametrize("scope", SCOPES)
def test_intent_is_unsigned_root_governance(scope: str) -> None:
    """INTENT is a role declaration, not a note in the signed vault."""
    fields = frontmatter(SCOPES[scope] / "INTENT.md")
    assert "tracking" not in fields, f"{scope}/INTENT.md must not carry a tracking block"
    assert "signature" not in fields, f"{scope}/INTENT.md must not carry a signature"


def test_master_mission_keeps_its_build_status_contract() -> None:
    """The master MISSION declares status in frontmatter, not in prose."""
    fields = frontmatter(SCOPES["master"] / "MISSION.md")
    assert fields.get("status") in BUILD_STATUSES, (
        "master-node/MISSION.md must keep a build status from the closed vocabulary"
    )


@pytest.mark.parametrize("scope", ("peer", "master"))
def test_role_config_loads_the_identity_pages(scope: str) -> None:
    """A role session must get the role's own charter, purpose and contract."""
    config = json.loads((SCOPES[scope] / "opencode.json").read_text(encoding="utf-8"))
    assert {"CONTEXT.md", "AGENTS.md", "MISSION.md", "INTENT.md"} <= set(config["instructions"]), (
        f"{scope}/opencode.json must load AGENTS.md, MISSION.md and INTENT.md"
    )
    assert config["references"]["knowledge"]["path"] == ".", (
        f"{scope}/opencode.json must point the knowledge reference at the role vault"
    )


def test_role_configs_deny_editing_the_other_role() -> None:
    peer = json.loads((SCOPES["peer"] / "opencode.json").read_text(encoding="utf-8"))
    master = json.loads((SCOPES["master"] / "opencode.json").read_text(encoding="utf-8"))
    assert peer["permission"]["edit"]["../master-node/**"] == "deny"
    assert master["permission"]["edit"]["../peer-node/**"] == "deny"
