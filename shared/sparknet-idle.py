#!/usr/bin/env python3
"""Node-local idle evidence for the nocturnal batch scheduler.

This module measures; it never decides that a node is idle and never carries
authority. The scheduler owns the thresholds and the all-nodes conjunction.
A probe that cannot answer reports ``None`` plus an error, because "could not
read" is not the same fact as "zero".

Design: ``master-node/plans/NOCTURNAL_BATCH_DESIGN.md``. The fleet has no
``nvidia-smi``, so the GPU path falls back to ``tegrastats`` and reports which
probe answered. WireGuard counters are read where the process has permission;
on the live userspace-WireGuard peer the service account does not, so the field
is null and the error is explicit rather than a fabricated zero.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "sparknet-idle/1"
DEFAULT_INTERFACES = ("wg1", "wg0")
GPU_TIMEOUT = 3.0
PROBE_TIMEOUT = 5.0

CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[str]]

_GR3D = re.compile(r"GR3D_FREQ\s+(\d+)%")


def _run(argv: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(argv), capture_output=True, text=True, check=False, timeout=timeout)


def parse_loginctl_list(text: str) -> list[str]:
    """Session ids from ``loginctl list-sessions --no-legend``."""
    ids: list[str] = []
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0].isdigit():
            ids.append(parts[0])
    return ids


def parse_loginctl_session(text: str) -> dict[str, str]:
    """``key=value`` properties from ``loginctl show-session``."""
    props: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip():
            props[key.strip()] = value.strip()
    return props


def count_sessions(sessions: Sequence[dict[str, str]], ignore_users: Sequence[str] = ()) -> tuple[int, int]:
    """Return ``(interactive, ssh)`` from parsed logind sessions.

    ``manager`` is a systemd --user manager, not a person at a console. Every
    other class (``user``, ``greeter``, ``login``, ``lock-screen``) counts, and
    a session is SSH when the remote flag is set or sshd owns it. Missing
    identity fields raise, because an unreadable session must not become zero.
    """
    ignored = set(ignore_users)
    interactive = 0
    ssh = 0
    for session in sessions:
        session_class = session.get("Class", "")
        user = session.get("User", "")
        if not session_class or not user:
            raise ValueError("logind session is missing Class or User")
        if session_class == "manager" or user in ignored:
            continue
        interactive += 1
        service = session.get("Service", "").lower()
        if session.get("Remote", "").lower() == "yes" or "sshd" in service:
            ssh += 1
    return interactive, ssh


def collect_sessions(
    run: CommandRunner = _run, ignore_users: Sequence[str] = ()
) -> tuple[int | None, int | None, str | None]:
    """Read interactive SSH/local sessions, or return ``(None, None, error)``."""
    try:
        listed = run(["loginctl", "list-sessions", "--no-legend"], PROBE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None, None, "loginctl_unavailable"
    if listed.returncode != 0:
        return None, None, "loginctl_unavailable"
    sessions: list[dict[str, str]] = []
    for session_id in parse_loginctl_list(listed.stdout):
        try:
            shown = run(
                ["loginctl", "show-session", session_id, "-p", "Class", "-p", "User", "-p", "Remote", "-p", "Service"],
                PROBE_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None, None, "loginctl_unavailable"
        if shown.returncode != 0:
            return None, None, "loginctl_unavailable"
        sessions.append(parse_loginctl_session(shown.stdout))
    try:
        interactive, ssh = count_sessions(sessions, ignore_users)
    except ValueError:
        return None, None, "loginctl_malformed"
    return interactive, ssh, None


def parse_nvidia_smi(text: str) -> float | None:
    values: list[float] = []
    for line in text.splitlines():
        token = line.strip()
        if not token or token.lower() in {"n/a", "[n/a]"}:
            continue
        try:
            values.append(float(token))
        except ValueError:
            continue
    return max(values) if values else None


def parse_tegrastats(text: str) -> float | None:
    values = [float(match.group(1)) for match in _GR3D.finditer(text)]
    return max(values) if values else None


def collect_gpu(run: CommandRunner = _run) -> tuple[str | None, float | None, str | None]:
    """Return ``(probe, utilisation_percent, error)``; missing is not zero."""
    try:
        nvidia = run(
            ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            GPU_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        nvidia = None
    if nvidia is not None and nvidia.returncode == 0:
        util = parse_nvidia_smi(nvidia.stdout)
        if util is not None:
            return "nvidia-smi", util, None

    try:
        tegrastats = run(["tegrastats", "--interval", "1000"], GPU_TIMEOUT)
        output = tegrastats.stdout
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
    except OSError:
        return None, None, "gpu_probe_unavailable"
    if isinstance(output, bytes):
        output = output.decode("utf-8", "replace")
    util = parse_tegrastats(output or "")
    if util is None:
        return None, None, "gpu_probe_unavailable"
    return "tegrastats", util, None


def parse_wg_transfer(text: str) -> tuple[int, int, int]:
    """Sum ``(rx_bytes, tx_bytes, peer_count)`` from ``wg show <if> transfer``."""
    rx = 0
    tx = 0
    peers = 0
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if len(parts) < 3:
            raise ValueError("wg transfer row is not peer/rx/tx")
        try:
            row_rx = int(parts[-2])
            row_tx = int(parts[-1])
        except ValueError as exc:
            raise ValueError("wg transfer row has non-numeric counters") from exc
        rx += row_rx
        tx += row_tx
        peers += 1
    return rx, tx, peers


def wireguard_interface(explicit: str | None = None) -> str | None:
    """The configured interface, else the first of ``wg1``/``wg0`` that exists."""
    if explicit:
        return explicit
    env = os.environ.get("SPARKNET_WG_INTERFACE", "").strip()
    if env:
        return env
    for name in DEFAULT_INTERFACES:
        if Path(f"/sys/class/net/{name}").is_dir():
            return name
    return None


def collect_wireguard(
    interface: str | None, run: CommandRunner = _run
) -> tuple[str | None, int | None, int | None, int | None, str | None]:
    """Read the local WireGuard counters; no interface or permission is an error."""
    if not interface:
        return None, None, None, None, "wireguard_interface_unset"
    try:
        result = run(["wg", "show", interface, "transfer"], PROBE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return interface, None, None, None, "wireguard_unavailable"
    if result.returncode != 0:
        return interface, None, None, None, "wireguard_unreadable"
    try:
        rx, tx, peers = parse_wg_transfer(result.stdout)
    except ValueError:
        return interface, None, None, None, "wireguard_malformed"
    return interface, rx, tx, peers, None


def _sampled_at(now: datetime | None) -> str:
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def collect_idle_evidence(
    *,
    interface: str | None = None,
    run: CommandRunner = _run,
    ignore_users: Sequence[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect the local evidence the scheduler evaluates. No verdict, no authority."""
    if ignore_users is None:
        configured = os.environ.get("SPARKNET_IDLE_IGNORE_USERS", "")
        ignore_users = [name.strip() for name in configured.split(",") if name.strip()]
    iface = wireguard_interface(interface)
    interactive, ssh, session_error = collect_sessions(run, ignore_users)
    gpu_probe, gpu_util, gpu_error = collect_gpu(run)
    wg_iface, wg_rx, wg_tx, wg_peers, wg_error = collect_wireguard(iface, run)
    errors = [error for error in (session_error, gpu_error, wg_error) if error]
    return {
        "schema_version": SCHEMA_VERSION,
        "sampled_at": _sampled_at(now),
        "interactive_sessions": interactive,
        "ssh_sessions": ssh,
        "gpu_probe": gpu_probe,
        "gpu_util_pct": gpu_util,
        "wg_interface": wg_iface,
        "wg_rx_bytes": wg_rx,
        "wg_tx_bytes": wg_tx,
        "wg_peer_count": wg_peers,
        "errors": errors,
    }


__all__ = [
    "SCHEMA_VERSION",
    "collect_gpu",
    "collect_idle_evidence",
    "collect_sessions",
    "collect_wireguard",
    "count_sessions",
    "parse_loginctl_list",
    "parse_loginctl_session",
    "parse_nvidia_smi",
    "parse_tegrastats",
    "parse_wg_transfer",
    "wireguard_interface",
]
