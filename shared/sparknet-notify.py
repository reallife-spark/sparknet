#!/usr/bin/env python3
"""Node-local notification when an item arrives in ``01_Inbox/`` (fabric Step 67B).

Acceptance is a human act, so an unnoticed item is an unaccepted one: whatever
lands in a node's inbox has to *reach* the operator, not merely be recorded. The
fabric root has ``scripts/plugins/kde-notify.ts``, but it is deliberately **not**
bundled into nodes, so a node needs its own mechanism. This module is that
mechanism, and it lives in ``shared/`` so there is **one** copy: the peer guard
calls :func:`notify_inbox_arrival` when an RFI answer lands, and the Master admin
console's KDE ping delegates here too. Before this the console carried its own
``notify_kde`` — the same drift the repo forbids for ``sparknet-authz.py`` and the
install rules: two copies of "how a node tells the human something" would diverge,
and the divergence is invisible until the channel that is wrong is the one you need.

Two channels, each degrading to nothing:

* **A durable spool** — one JSON line per arrival under
  ``<state-dir>/notifications/arrivals.jsonl`` (0600), the same shape and location
  convention as the admin agent's event spool. This is the *alert queue* the node's
  admin surface or an operator reads. It is **not** the audit trail — the signed
  ``inbox_acceptance`` ledger block (``sparknet-provenance.py``) is that. One says
  "tell the human"; the other proves what happened.
* **A best-effort KDE Connect ping** — the node-local twin of the fabric-root
  plugin. A headless node with no ``kdeconnect-cli`` and no paired device is a
  no-op, which is the honest common case for a peer.

A notification never raises and never blocks the install: it is a courtesy, and an
item that landed must stay landed even if nobody could be pinged. Real-time push to
a *remote* operator from a headless peer is not this module's job — a peer egresses
only to the Master, so that rides telemetry to the Master's admin surface (Step 70F,
`kind=inbox_alert` from the guard), not a local ping. That report is unsigned and
overlay-attributed, and it carries no authority. Claiming otherwise would be the
overclaim the phase-boundary rule exists to prevent.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Where a node records the arrivals it must tell the human about, under the state
#: dir (the peer keeps ``<vault>/.state``; the Master points ``SPARKNET_STATE_DIR``
#: outside the vault). Mirrors the admin agent's ``admin-events/events.jsonl``.
ARRIVAL_SPOOL_RELPATH = Path("notifications") / "arrivals.jsonl"

#: The ping title, matching the fabric-root plugin so a device shows one voice.
NOTIFIER_TITLE = "sparknet"


# --- the state dir -------------------------------------------------------------


def _state_dir(vault_root: Path) -> Path:
    """The same split ``sparknet-provenance.py::_state_dir`` encodes: an explicit
    ``SPARKNET_STATE_DIR`` wins (the Master keeps state outside the vault); a peer
    defaults to ``<vault>/.state``. Duplicated as two lines rather than imported so
    this library stays dependency-free and loadable on its own."""
    env = os.environ.get("SPARKNET_STATE_DIR")
    if env:
        return Path(env)
    return Path(vault_root) / ".state"


# --- KDE Connect (the node-local twin of scripts/plugins/kde-notify.ts) ---------


def kde_devices_from_env(env: dict[str, str] | None = None) -> list[str]:
    raw = (env if env is not None else os.environ).get("SPARKNET_KDE_DEVICES", "")
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def discover_kde_devices(*, which: Any = None, run: Any = None) -> list[str]:
    """The plugin's discovery, in Python: ask kdeconnect-cli for reachable ids."""
    which = which or shutil.which
    run = run or subprocess.run
    if which("kdeconnect-cli") is None:
        return []
    try:
        result = run(["kdeconnect-cli", "-a", "--id-only"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def notify_kde(
    body: str,
    *,
    devices: list[str] | None = None,
    which: Any = None,
    run: Any = None,
    timeout: float = 10.0,
) -> bool:
    """Ping paired devices. A missing binary or a failed ping is a no-op, never an
    error: a notification is a courtesy and must not block the caller."""
    which = which or shutil.which
    run = run or subprocess.run
    if which("kdeconnect-cli") is None:
        return False
    ids = list(devices) if devices is not None else discover_kde_devices(which=which, run=run)
    if not ids:
        return False
    for device in ids:
        try:
            run(
                ["kdeconnect-cli", "-d", device, "--ping-msg", f"{NOTIFIER_TITLE}: {body}"],
                capture_output=True,
                timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError):
            continue
    return True


# --- the arrival spool ---------------------------------------------------------


def arrival_spool_path(vault_root: Path) -> Path:
    return _state_dir(vault_root) / ARRIVAL_SPOOL_RELPATH


def record_arrival(
    vault_root: Path,
    *,
    item: str,
    source: str,
    request_id: str = "",
    notified: bool = False,
    clock: Any = None,
) -> dict[str, Any] | None:
    """Append one arrival to the spool (0600, one object per line).

    Returns the record, or ``None`` if it could not be written. It never raises: a
    spool the node cannot write (a read-only state dir, a full disk) must not turn
    a successful install into a failure — the item is already in the inbox and the
    ``inbox_acceptance`` ledger block is already the durable proof.
    """
    moment = (clock or (lambda: datetime.now(timezone.utc)))()
    record = {
        "event": "inbox_arrival",
        "ts": moment.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "node": os.uname().nodename,
        "item": str(item),
        "source": str(source),
        "request_id": str(request_id),
        "notified": bool(notified),
    }
    spool = arrival_spool_path(vault_root)
    try:
        spool.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with spool.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        with contextlib.suppress(OSError):
            os.chmod(spool, 0o600)
    except OSError:
        return None
    return record


def read_arrivals(vault_root: Path) -> list[dict[str, Any]]:
    """Spool rows as parsed objects; a corrupt row is skipped, not fatal — the same
    posture as the admin agent's spool and the RFI install record."""
    spool = arrival_spool_path(vault_root)
    if not spool.exists():
        return []
    try:
        lines = spool.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


# --- the one call an arrival path makes ----------------------------------------


def notify_inbox_arrival(
    vault_root: Path,
    *,
    item: str,
    source: str,
    request_id: str = "",
    which: Any = None,
    run: Any = None,
    clock: Any = None,
) -> dict[str, Any]:
    """Tell the human an item landed: best-effort ping, then a durable spool row.

    Never raises. Returns ``{"spooled": bool, "notified": bool, "record": dict|None}``
    so a caller can log the outcome without depending on it. The ping runs first so
    the spool row can record whether a device was actually reached; both halves are
    independent, so a node with no KDE Connect still leaves the durable record.
    """
    notified = False
    try:
        notified = notify_kde(
            f"inbox: {item} arrived from {source}",
            devices=kde_devices_from_env() or None,
            which=which,
            run=run,
        )
    except Exception:  # pragma: no cover - notify_kde already swallows its errors
        notified = False
    record = record_arrival(vault_root, item=item, source=source, request_id=request_id, notified=notified, clock=clock)
    return {"spooled": record is not None, "notified": notified, "record": record}
