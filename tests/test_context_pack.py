"""The generated operating context is present, current and loaded everywhere."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "sparknet-context-pack.py"
SCOPES = {
    "fabric": REPO_ROOT,
    "peer": REPO_ROOT / "peer-node",
    "master": REPO_ROOT / "master-node",
}


def _load() -> object:
    return load_by_path("sparknet_context_pack_test", SCRIPT)


def test_the_check_command_is_current_for_every_scope() -> None:
    module = _load()
    for role, root in SCOPES.items():
        assert module.main(["--root", str(root), "--role", role, "--check"]) == 0


def test_every_scope_has_the_required_sections_and_no_secret_or_host_path() -> None:
    for role, root in SCOPES.items():
        text = (root / "CONTEXT.md").read_text(encoding="utf-8")
        assert f"role: {role}" in text
        assert "generated: true" in text
        assert "source_sha256:" in text
        assert "Authority in one paragraph" in text
        assert "Knowledge rules" in text
        assert "Self-healing rules" in text
        assert "/mnt/knowledge" not in text, f"{role} context hard-codes the development path"
        assert "BEGIN PRIVATE KEY" not in text
        assert "sk-" not in text
        assert len(text.splitlines()) <= 160


def test_the_consumers_all_name_the_context_pack() -> None:
    for rel in ("opencode.json", "peer-node/opencode.json", "master-node/opencode.json"):
        config = json.loads((REPO_ROOT / rel).read_text(encoding="utf-8"))
        assert "CONTEXT.md" in config["instructions"], rel
    admin = json.loads((REPO_ROOT / "master-node" / "configs" / "admin-surface" / "opencode.json").read_text())
    assert "CONTEXT.md" in admin["instructions"]
    rag = (REPO_ROOT / "scripts" / "sparknet-rag-corpus.py").read_text()
    assert '"CONTEXT.md"' in rag
    provisioner = (REPO_ROOT / "peer-node" / "services" / "sparknet-vault-provisioner.py").read_text()
    assert '"CONTEXT.md"' in provisioner
    entrypoint = (REPO_ROOT / "spark-entrypoint.py").read_text()
    assert "CONTEXT.md" in entrypoint


def test_the_pack_does_not_duplicate_live_state() -> None:
    text = (REPO_ROOT / "peer-node" / "CONTEXT.md").read_text(encoding="utf-8")
    assert "Deployment-specific state belongs" not in text
    assert "current: " not in text
    assert "agx64" not in text and "MEMORY.md" in text, (
        "the peer context points at MEMORY for host state instead of hard-coding it"
    )
