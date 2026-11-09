"""Step 9B: idle evidence is measured, fail-closed, and carries no authority.

The collector is deliberately separate from the scheduler: it reports facts and
``None`` for a probe that could not answer. These tests drive it through a fake
command runner so a missing ``nvidia-smi`` on the fleet, an unreadable
WireGuard interface, or a malformed logind session cannot be mistaken for zero.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from sparknet_loader import load_by_path

FABRIC_ROOT = Path(__file__).resolve().parent.parent
IDLE_PATH = FABRIC_ROOT / "shared" / "sparknet-idle.py"


def _load() -> ModuleType:
    return load_by_path("sparknet_idle_for_tests", IDLE_PATH)


idle = _load()


def _done(argv: list[str], stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")


class _Runner:
    def __init__(self, responses: dict[tuple[str, ...], object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        key = tuple(argv)
        self.calls.append(key)
        answer = self.responses.get(key)
        if isinstance(answer, Exception):
            raise answer
        if answer is None:
            raise AssertionError(f"unexpected command: {argv}")
        return answer


def _full_runner(wg_returncode: int = 0) -> _Runner:
    return _Runner(
        {
            ("loginctl", "list-sessions", "--no-legend"): _done(
                ["loginctl", "list-sessions", "--no-legend"], " 2 1000 spark tty1\n"
            ),
            (
                "loginctl",
                "show-session",
                "2",
                "-p",
                "Class",
                "-p",
                "User",
                "-p",
                "Remote",
                "-p",
                "Service",
            ): _done(
                [],
                "User=1000\nClass=user\nRemote=yes\nService=sshd\n",
            ),
            ("nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"): _done([], "0\n"),
            ("wg", "show", "wg1", "transfer"): _done(
                [], "peer-a\t100\t50\npeer-b\t200\t10\n", returncode=wg_returncode
            ),
        }
    )


def test_parse_loginctl_list_keeps_only_session_ids() -> None:
    assert idle.parse_loginctl_list("  2 1000 spark tty1\nnot-a-session\n77 1001 op tty2\n") == ["2", "77"]


def test_manager_session_is_not_a_person_and_ssh_is_counted() -> None:
    sessions = [
        {"Class": "manager", "User": "1000", "Service": "systemd-user"},
        {"Class": "user", "User": "1000", "Remote": "yes", "Service": "sshd"},
        {"Class": "user", "User": "1001", "Remote": "no", "Service": "login"},
    ]
    assert idle.count_sessions(sessions) == (2, 1)
    assert idle.count_sessions(sessions, ignore_users=["1001"]) == (1, 1)


def test_a_malformed_session_is_an_error_not_zero() -> None:
    try:
        idle.count_sessions([{"Class": "user"}])
    except ValueError:
        pass
    else:
        raise AssertionError("a session without User must not be counted as idle")


def test_gpu_parsers_take_the_worst_sample() -> None:
    assert idle.parse_nvidia_smi("0\n27\n[N/A]\n") == 27.0
    assert idle.parse_tegrastats("RAM 100/100 GR3D_FREQ 0% GR3D_FREQ 34%\n") == 34.0
    assert idle.parse_nvidia_smi("[N/A]\n") is None


def test_tegrastats_timeout_still_uses_the_sample_it_captured() -> None:
    def fake(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
        if argv[0] == "nvidia-smi":
            raise FileNotFoundError
        raise subprocess.TimeoutExpired(argv, timeout, output="GR3D_FREQ 7%")

    assert idle.collect_gpu(fake) == ("tegrastats", 7.0, None)


def test_wireguard_transfer_sums_the_peer_rows() -> None:
    assert idle.parse_wg_transfer("peer-a\t100\t50\npeer-b\t200\t10\n") == (300, 60, 2)


def test_a_full_sample_reports_each_probe_and_a_timestamp() -> None:
    sample = idle.collect_idle_evidence(
        interface="wg1",
        run=_full_runner(),
        now=datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc),
    )
    assert sample["schema_version"] == "sparknet-idle/1"
    assert sample["sampled_at"] == "2026-10-25T04:00:00Z"
    assert sample["interactive_sessions"] == 1
    assert sample["ssh_sessions"] == 1
    assert sample["gpu_probe"] == "nvidia-smi"
    assert sample["gpu_util_pct"] == 0.0
    assert (sample["wg_rx_bytes"], sample["wg_tx_bytes"], sample["wg_peer_count"]) == (300, 60, 2)
    assert sample["errors"] == []


def test_unreadable_wireguard_is_null_plus_an_error_not_a_zero() -> None:
    sample = idle.collect_idle_evidence(interface="wg1", run=_full_runner(wg_returncode=1))
    assert sample["wg_rx_bytes"] is None
    assert sample["wg_tx_bytes"] is None
    assert "wireguard_unreadable" in sample["errors"]
    assert sample["interactive_sessions"] == 1


def test_missing_gpu_probe_is_null_plus_an_error() -> None:
    responses = _full_runner().responses
    responses[("nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits")] = FileNotFoundError()
    responses[("tegrastats", "--interval", "1000")] = FileNotFoundError()
    sample = idle.collect_idle_evidence(interface="wg1", run=_Runner(responses))
    assert sample["gpu_probe"] is None
    assert sample["gpu_util_pct"] is None
    assert "gpu_probe_unavailable" in sample["errors"]


def test_the_collector_carries_no_authority_vocabulary() -> None:
    source = IDLE_PATH.read_text()
    for verb in ("sign_authorization", "verify_telemetry", "grant(", "revoke("):
        assert verb not in source
    assert "never decides" in source
