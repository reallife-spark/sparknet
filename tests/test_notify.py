"""The node-local arrival notifier (fabric Step 67B).

Acceptance is a human act, so an item that lands in ``01_Inbox/`` has to reach a
person, not merely be recorded. These tests pin the two channels and the invariant
that matters most: a notification is a courtesy that **never** raises and never
stands between an arrived item and the human — a missing binary, an unwritable
spool or a failed ping degrades to nothing rather than to an error.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

import pytest
from sparknet_loader import load_by_path

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTIFY_PATH = REPO_ROOT / "shared" / "sparknet-notify.py"


@pytest.fixture(scope="module")
def notify() -> ModuleType:
    return load_by_path("sparknet_notify_under_test", NOTIFY_PATH)


class _Run:
    """A fake subprocess.run: records calls, returns a canned completed process."""

    def __init__(self, *, returncode: int = 0, stdout: str = "") -> None:
        self.calls: list[list] = []
        self.returncode = returncode
        self.stdout = stdout

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return type("R", (), {"returncode": self.returncode, "stdout": self.stdout})()


# --- the spool: the durable half ----------------------------------------------


def test_an_arrival_is_spooled_as_one_json_line(notify: ModuleType, tmp_path: Path, monkeypatch) -> None:
    state = tmp_path / "state"
    monkeypatch.setenv("SPARKNET_STATE_DIR", str(state))
    vault = tmp_path / "vault"
    vault.mkdir()

    record = notify.record_arrival(vault, item="01_Inbox/answer.md", source="master-node", request_id="RFI-1")
    assert record is not None
    assert record["event"] == "inbox_arrival"
    assert record["item"] == "01_Inbox/answer.md"
    assert record["request_id"] == "RFI-1"

    spool = notify.arrival_spool_path(vault)
    assert spool == state / "notifications" / "arrivals.jsonl"
    assert spool.is_file()
    # 0600: the spool names what arrived on this node; it is not world-readable.
    assert oct(spool.stat().st_mode & 0o777) == "0o600"
    lines = spool.read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["item"] == "01_Inbox/answer.md"


def test_arrivals_accumulate_and_read_back(notify: ModuleType, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_STATE_DIR", str(tmp_path / "state"))
    vault = tmp_path / "vault"
    vault.mkdir()
    notify.record_arrival(vault, item="01_Inbox/a.md", source="master-node", request_id="RFI-1")
    notify.record_arrival(vault, item="01_Inbox/b.md", source="master-node", request_id="RFI-2")
    rows = notify.read_arrivals(vault)
    assert [r["request_id"] for r in rows] == ["RFI-1", "RFI-2"]


def test_a_corrupt_spool_row_is_skipped_not_fatal(notify: ModuleType, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_STATE_DIR", str(tmp_path / "state"))
    vault = tmp_path / "vault"
    vault.mkdir()
    notify.record_arrival(vault, item="01_Inbox/a.md", source="master-node", request_id="RFI-1")
    spool = notify.arrival_spool_path(vault)
    spool.write_text("{not json\n" + spool.read_text())
    rows = notify.read_arrivals(vault)
    assert len(rows) == 1 and rows[0]["request_id"] == "RFI-1"


def test_the_spool_defaults_to_the_peer_state_dir(notify: ModuleType, tmp_path: Path, monkeypatch) -> None:
    """No SPARKNET_STATE_DIR -> <vault>/.state, the peer's convention."""
    monkeypatch.delenv("SPARKNET_STATE_DIR", raising=False)
    vault = tmp_path / "vault"
    vault.mkdir()
    assert notify.arrival_spool_path(vault) == vault / ".state" / "notifications" / "arrivals.jsonl"


def test_an_unwritable_spool_returns_none_and_never_raises(notify: ModuleType, tmp_path: Path, monkeypatch) -> None:
    """A node that cannot write the spool still must not fail the install."""
    # Point the state dir at a path that cannot be created (a file in the way).
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.setenv("SPARKNET_STATE_DIR", str(blocker / "notifications"))
    vault = tmp_path / "vault"
    vault.mkdir()
    assert notify.record_arrival(vault, item="01_Inbox/a.md", source="master-node") is None
    outcome = notify.notify_inbox_arrival(vault, item="01_Inbox/a.md", source="master-node", which=lambda n: None)
    assert outcome == {"spooled": False, "notified": False, "record": None}


# --- the KDE ping: the best-effort half ---------------------------------------


def test_notify_kde_builds_the_plugin_command(notify: ModuleType) -> None:
    run = _Run()
    ok = notify.notify_kde("inbox: x arrived", devices=["dev-1"], which=lambda n: "/usr/bin/" + n, run=run)
    assert ok is True
    assert run.calls == [["kdeconnect-cli", "-d", "dev-1", "--ping-msg", "sparknet: inbox: x arrived"]]


def test_notify_kde_is_a_noop_without_the_binary(notify: ModuleType) -> None:
    assert notify.notify_kde("x", which=lambda n: None, run=lambda *a, **k: None) is False


def test_notify_kde_discovers_devices_when_none_configured(notify: ModuleType) -> None:
    run = _Run(stdout="dev-a\ndev-b\n")
    ok = notify.notify_kde("x", which=lambda n: "/usr/bin/" + n, run=run)
    assert ok is True
    # First call discovers, then one ping per discovered device.
    assert run.calls[0] == ["kdeconnect-cli", "-a", "--id-only"]
    assert ["kdeconnect-cli", "-d", "dev-a", "--ping-msg", "sparknet: x"] in run.calls
    assert ["kdeconnect-cli", "-d", "dev-b", "--ping-msg", "sparknet: x"] in run.calls


def test_kde_devices_from_env_parses(notify: ModuleType) -> None:
    assert notify.kde_devices_from_env({"SPARKNET_KDE_DEVICES": "a, b ,c"}) == ["a", "b", "c"]
    assert notify.kde_devices_from_env({}) == []


def test_a_failed_ping_does_not_raise(notify: ModuleType) -> None:
    def boom(argv, **kwargs):
        raise OSError("device went away")

    # The per-device ping is swallowed; the call still returns without raising.
    assert notify.notify_kde("x", devices=["dev-1"], which=lambda n: "/usr/bin/" + n, run=boom) is True


# --- the one call an arrival path makes ---------------------------------------


def test_notify_inbox_arrival_records_even_when_no_device_is_reachable(
    notify: ModuleType, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SPARKNET_STATE_DIR", str(tmp_path / "state"))
    vault = tmp_path / "vault"
    vault.mkdir()
    outcome = notify.notify_inbox_arrival(
        vault, item="01_Inbox/answer.md", source="master-node", request_id="RFI-9", which=lambda n: None
    )
    # A headless peer: no ping, but the durable row is still there.
    assert outcome["notified"] is False
    assert outcome["spooled"] is True
    rows = notify.read_arrivals(vault)
    assert rows[0]["request_id"] == "RFI-9" and rows[0]["notified"] is False


def test_notify_inbox_arrival_sets_notified_when_a_device_is_pinged(
    notify: ModuleType, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SPARKNET_STATE_DIR", str(tmp_path / "state"))
    # notify_inbox_arrival reads the device list from the environment, so configure
    # one; a _Run() with no discovery output would otherwise find no devices.
    monkeypatch.setenv("SPARKNET_KDE_DEVICES", "dev-1")
    vault = tmp_path / "vault"
    vault.mkdir()
    run = _Run()
    outcome = notify.notify_inbox_arrival(
        vault,
        item="01_Inbox/answer.md",
        source="master-node",
        which=lambda n: "/usr/bin/" + n,
        run=run,
    )
    assert outcome["notified"] is True
    assert notify.read_arrivals(vault)[0]["notified"] is True
    assert run.calls == [
        ["kdeconnect-cli", "-d", "dev-1", "--ping-msg", "sparknet: inbox: 01_Inbox/answer.md arrived from master-node"]
    ]


def test_the_notifier_does_not_reimplement_the_shared_loader() -> None:
    """It is a plain library: no spec_from_file_location, no second loader copy.

    `test_only_one_shared_loader_exists` fails the build if any shared module
    reimplements the by-path loader; the notifier is loaded *by* the guard and the
    console, so it must not carry one itself.
    """
    assert "spec_from_file_location" not in NOTIFY_PATH.read_text()
