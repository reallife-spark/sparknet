"""Guard for the KDE Connect notification plugin.

Ensures the plugin is present, has the right hooks, avoids hardcoding secrets or
vault paths, and — crucially — is NOT registered in any config scope that a role
worktree inherits. On opencode 1.18.35 a plugin in the deep-merged project config
makes opencode spin at ~40% CPU and hang whenever it starts from a nested
location (`peer-node/`, `master-node/`). The plugin is therefore injected only
into fabric-root sessions via `OPENCODE_CONFIG`; the guards below enforce both
that it exists and that it stays out of the inherited scopes.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGIN_FILE = REPO_ROOT / "scripts" / "plugins" / "kde-notify.ts"
NOTIF_CONFIG = REPO_ROOT / "scripts" / "plugins" / "kde-notif.opencode.json"
OPCODE_CONFIG = REPO_ROOT / "opencode.json"
AUTO_DISCOVERY_DIRS = (REPO_ROOT / ".opencode" / "plugin", REPO_ROOT / ".opencode" / "plugins")
ROLE_DIRS = (REPO_ROOT / "peer-node", REPO_ROOT / "master-node")


def test_kde_notify_plugin_exists():
    """The plugin must exist at scripts/plugins/kde-notify.ts."""
    assert PLUGIN_FILE.exists(), f"missing {PLUGIN_FILE}"


def test_kde_notify_not_in_any_inherited_scope():
    """Hang-regression guard: role worktrees must never resolve the plugin.

    `opencode.json` may use a `plugin` array for other things, but it must not
    reference kde-notify. And nothing may live in `.opencode/plugin*/`, which opencode
    auto-discovers at every project location. Either reintroduces the 1.18.35
    nested-location hang and breaks `opencode agent list` from the roles.
    """
    if OPCODE_CONFIG.exists():
        cfg = json.loads(OPCODE_CONFIG.read_text())
        declared = cfg.get("plugin") or []
        flat = [item if isinstance(item, str) else item[0] for item in declared]
        joined = " ".join(str(item).lower() for item in flat)
        assert "kde-notify" not in joined, (
            f"{OPCODE_CONFIG} registers kde-notify; a role worktree would inherit it "
            "and opencode 1.18.35 would hang. Register it via "
            "`scripts/plugins/kde-notif.opencode.json` (OPENCODE_CONFIG) instead."
        )
    for directory in AUTO_DISCOVERY_DIRS:
        assert not any(directory.rglob("kde-notify.*")), (
            f"{directory} auto-discovers plugins at every location; a kde-notify file "
            "there would hang role worktrees on opencode 1.18.35."
        )


def test_kde_notify_config_activates_plugin():
    """The dedicated config must wire the plugin, so notifications stay reachable."""
    assert NOTIF_CONFIG.exists(), (
        f"missing {NOTIF_CONFIG} — `make tui` and the documented OPENCODE_CONFIG "
        "launch depend on it"
    )
    body = NOTIF_CONFIG.read_text(encoding="utf-8")
    assert '"plugin"' in body, f"{NOTIF_CONFIG} must declare a plugin array"
    assert "kde-notify.ts" in body, (
        f"{NOTIF_CONFIG} must reference ./kde-notify.ts so fabric-root sessions load it"
    )


def test_kde_notify_has_required_hooks():
    """The plugin must define the three handlers: question, permission.ask, and session.idle."""
    content = PLUGIN_FILE.read_text(encoding="utf-8")

    has_execute_before = "tool.execute.before" in content
    has_permission_ask = '"permission.ask"' in content or "permission.ask" in content
    has_session_idle = 'session.idle' in content and "event.type === \"session.idle\"" in content
    has_question_tool = '"question"' in content

    assert has_execute_before, (
        f"{PLUGIN_FILE} missing tool.execute.before hook for question detection"
    )
    assert has_permission_ask, (
        f"{PLUGIN_FILE} missing permission.ask hook for permission prompts"
    )
    assert has_session_idle, (
        f"{PLUGIN_FILE} missing session.idle event handler for turn completion"
    )
    assert has_question_tool, (
        f"{PLUGIN_FILE} does not check input.tool === \"question\""
    )


def test_kde_notify_uses_shell_api():
    """The plugin must call kdeconnect-cli via the BunShell $ API."""
    content = PLUGIN_FILE.read_text(encoding="utf-8")

    has_templated_call = "$`kdeconnect-cli" in content
    assert has_templated_call, (
        f"{PLUGIN_FILE} must invoke kdeconnect-cli via the BunShell template literal API"
    )


def test_kde_notify_no_hardcoded_secrets():
    """The plugin must not hardcode any secrets, tokens, or keys."""
    content = PLUGIN_FILE.read_text(encoding="utf-8")

    forbidden_patterns = ["password", "bearer", "api_key", "API_KEY"]
    for pattern in forbidden_patterns:
        assert (
            pattern.lower() not in content.lower()
        ), f"{PLUGIN_FILE} must avoid hardcoding secrets; {pattern} found"


def test_kde_notify_no_hardcoded_vault_path():
    """The plugin must not hardcode any vault path."""
    content = PLUGIN_FILE.read_text(encoding="utf-8")

    forbidden_paths = ["/mnt/knowledge", "$VAULT_PATH"]
    for path in forbidden_paths:
        assert (
            path not in content
        ), f"{PLUGIN_FILE} must avoid hardcoding vault paths; {path} found"


def test_kde_notify_uses_buffer_text_api():
    """The plugin must use .text() on stdout buffer, not .trim()."""
    content = PLUGIN_FILE.read_text(encoding="utf-8")

    # Ensure we don't call .trim() on Buffer.stdout
    has_buffer_trim = "stdout.trim()" in content or ".stdout.trim()" in content
    assert not has_buffer_trim, (
        f"{PLUGIN_FILE} uses stdout.trim() which fails because Buffer has no trim(); "
        "use result.text() instead"
    )

    # Ensure we use .text() for string parsing
    has_text_call = ".text()" in content or "result.text()" in content
    assert has_text_call, (
        f"{PLUGIN_FILE} must use .text() on BunShell results to parse device IDs"
    )


def test_kde_notify_uses_nothrow():
    """The plugin must use .nothrow() to avoid session blocking."""
    content = PLUGIN_FILE.read_text(encoding="utf-8")

    has_nothrow = ".nothrow()" in content
    assert has_nothrow, (
        f"{PLUGIN_FILE} must call .nothrow() on kdeconnect-cli to prevent failures from blocking sessions"
    )


def test_kde_notify_supports_device_override():
    """The plugin must support the SPARKNET_KDE_DEVICES override."""
    content = PLUGIN_FILE.read_text(encoding="utf-8")

    assert "SPARKNET_KDE_DEVICES" in content, (
        f"{PLUGIN_FILE} must honour the SPARKNET_KDE_DEVICES environment override"
    )
    assert "-a --id-only" in content, (
        f"{PLUGIN_FILE} must fall back to `kdeconnect-cli -a --id-only` when the "
        "override is unset"
    )


@pytest.mark.parametrize("role_dir", [p for p in ROLE_DIRS if p.is_dir()])
def test_opencode_agent_list_does_not_hang_from_role_worktree(role_dir):
    """Integration guard for the 1.18.35 nested-location hang.

    With the plugin confined to the OPENCODE_CONFIG scope, `opencode agent list`
    must return from every role worktree instead of spinning for the full timeout.
    """
    if shutil.which("opencode") is None:
        pytest.skip("opencode CLI not on PATH; config-level guards above still apply")

    result = subprocess.run(
        ["opencode", "agent", "list"],
        cwd=role_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, (
        f"`opencode agent list` exited {result.returncode} from {role_dir}: "
        f"{result.stderr[:400]}"
    )