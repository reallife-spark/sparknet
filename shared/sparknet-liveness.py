#!/usr/bin/env python3
"""Clock-injected peer liveness monitor — the one shared implementation.

Why it is shared and single.  The health rules in ``contracts/health-protocol.md``
must be read identically by every peer that watches a sibling, exactly as the
authz vocabulary must be.  Two monitors drifting on the eviction threshold
would disagree about whether a peer died — silently, and on the data plane
where nothing else checks.  So the monitor lives here once, next to the
transport that signs its claims, and is loaded by path.

Nothing here reaches the network.  ``Monitor.probe_once`` calls a ``probe``
callback the caller supplies (typically ``socket.create_connection`` against a
re-resolved address), and every decision is clock-injected so a test can move
time by a decade without sleeping.  This is the same testability contract the
election module and the transport already use.

The rules (translated from NVIDIA PAIR's scanner and manual-nodes after review;
see contracts/health-protocol.md for the full mapping):

1. **Activity trumps eviction** — a busy node is the least likely to answer an
   announcement, so recent activity resets its missed-probe count.
2. **A scan that loses everything is our own fault** — if a probe round finds
   *every* known peer dark, the fault is the monitor's own link, not the whole
   fabric's; a full-dark round evicts nothing.
3. **Probe the non-serving port** — the monitor never touches the serving path,
   so the thing being watched cannot become the thing watching.
"""

from __future__ import annotations

import threading

try:  # Python 3.9+
    from collections.abc import Callable
except ImportError:  # pragma: no cover - Python 3.8
    from typing import Callable  # noqa: UP035

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

PROBE_INTERVAL_SECONDS = 10
EVICTION_THRESHOLD = 3
ACTIVITY_GRACE_SECONDS = 120
STALE_AGE_SECONDS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Peer:
    """One watched peer. Presence is monotonic; eviction is local and reversible."""

    hostname: str
    alive: bool = True
    last_activity: datetime = field(default_factory=_now)
    missed_probes: int = 0
    evicted: bool = False

    def quiet_for(self, now: datetime) -> bool:
        """True once the peer has been silent past the activity grace."""
        return now - self.last_activity >= timedelta(seconds=ACTIVITY_GRACE_SECONDS)


class Monitor:
    """Owns the probe rhythm and the eviction decision for a set of peers.

    ``resolve`` maps a peer name to a probe address and is called **every**
    probe round, so a renumbered peer is found as itself — there is no
    keepalive to keep a stale mapping warm. ``probe`` is the callback asked to
    reach the peer; it is an address probe against a non-serving port, never a
    live request on the serving path.
    """

    def __init__(
        self,
        peers: dict[str, Peer] | None = None,
        *,
        now: Callable[[], datetime] | None = None,
        resolve: Callable[[str], str | None] | None = None,
        probe: Callable[[str], bool] | None = None,
        probe_interval: int = PROBE_INTERVAL_SECONDS,
        eviction_threshold: int = EVICTION_THRESHOLD,
        activity_grace: int = ACTIVITY_GRACE_SECONDS,
    ) -> None:
        self.peers: dict[str, Peer] = peers if peers is not None else {}
        self.clock = now or _now
        self.resolve = resolve or (lambda name: name)
        self.probe = probe or (lambda _addr: False)
        self.probe_interval = probe_interval
        self.eviction_threshold = eviction_threshold
        self.activity_grace = activity_grace
        self.full_dark_rounds = 0
        self._probe_count = 0
        self._lock = threading.RLock()

    # --- observation ----------------------------------------------------------

    def activity(self, name: str, at: datetime | None = None) -> None:
        """A ledger or telemetry sighting of ``name`` — resets its eviction clock.

        A busy node is the least likely to answer an announcement, so activity
        trumps eviction: the missed-probe count drops back to zero.
        """
        with self._lock:
            peer = self.peers.get(name)
            if peer is None:
                return
            peer.last_activity = at or self.clock()
            peer.missed_probes = 0
            peer.alive = True

    def probe_once(self, at: datetime | None = None) -> dict[str, bool]:
        """One probe round across every watched peer.

        Returns ``{name: alive}`` for the round. A round in which every peer is
        dark is a full-dark round: the fault is the monitor's own link, so it
        records the flag and evicts nothing.
        """
        with self._lock:
            results: dict[str, bool] = {}
            for name in list(self.peers):
                address = self.resolve(name)
                if address is None:
                    results[name] = False
                    continue
                results[name] = self.probe(address)

            self._probe_count += 1
            authors = list(results.values())
            if authors and not any(authors):
                self.full_dark_rounds += 1
            else:
                self.full_dark_rounds = 0

            for name, alive in results.items():
                peer = self.peers.get(name)
                if peer is None:
                    continue
                peer.alive = alive
                if alive:
                    peer.missed_probes = 0
                    peer.evicted = False
                else:
                    peer.missed_probes += 1
            return results

    # --- eviction -------------------------------------------------------------

    def eviction_candidates(self, at: datetime | None = None) -> list[str]:
        """Peers that may be dropped from the next probe round.

        Three conditions, all required: the round that observed them was not
        full-dark, they have been quiet past the grace, and they have missed
        probes up to the threshold.
        """
        with self._lock:
            stamp = at or self.clock()
            if self.full_dark_rounds > 0:
                return []
            return [
                name
                for name, peer in self.peers.items()
                if peer.quiet_for(stamp) and peer.missed_probes >= self.eviction_threshold
            ]

    def evict(self, name: str, at: datetime | None = None) -> bool:
        """Evict ``name`` from this monitor's view. Local and reversible."""
        with self._lock:
            if name not in self.eviction_candidates(at):
                return False
            peer = self.peers[name]
            peer.evicted = True
            peer.alive = False
            del self.peers[name]
            return True

    # --- claims ---------------------------------------------------------------

    def claim(self, name: str, at: datetime | None = None) -> dict[str, object]:
        """This monitor's liveness claim for ``name``.

        The claim carries the same monotonic, eviction-safe facts the monitor
        holds. It is not signed: the service pushes it as an unsigned,
        overlay-attributed ``kind=liveness`` telemetry report, and the Master
        attributes it by the authenticated source address
        (``contracts/health-protocol.md``).
        """
        with self._lock:
            stamp = at or self.clock()
            peer = self.peers.get(name)
            if peer is None:
                return {"node": name, "alive": False, "reported_at": stamp.isoformat()}
            return {
                "node": name,
                "alive": peer.alive,
                "missed_probes": peer.missed_probes,
                "full_dark_rounds": self.full_dark_rounds,
                "probe_count": self._probe_count,
                "reported_at": stamp.isoformat(),
            }


class ContinuousMonitor(Monitor):
    """A probe loop for a service: one thread, injected clock, graceful stop."""

    def __init__(
        self,
        *args: object,
        on_round: Callable[[], None] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.on_round = on_round
        self.last_error: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.probe_once()
                self.last_error = None
            except Exception as exc:  # a probe failure must not kill the monitor
                self.last_error = str(exc)
            if self.on_round is not None:
                try:
                    self.on_round()
                except Exception as exc:
                    self.last_error = str(exc)
            self._stop.wait(self.probe_interval)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
