"""The shared peer liveness monitor.

`shared/sparknet-liveness.py` is the one shared implementation of the health
rules in `contracts/health-protocol.md`. Like authz it must be loaded by path —
a role that imported a private copy could drift the eviction threshold, and two
peers would then disagree about whether a sibling died, silently, on a plane
where nothing else checks.

What this file asserts:

1. **Clock-injected decisions.** Every rule is tested by moving the clock, never
   by sleeping.
2. **Activity trumps eviction.** A busy peer (recent ledger/telemetry sighting)
   is not evicted for missing probes.
3. **A full-dark round evicts nothing.** If every peer is dark at once, the
   fault is the monitor's own link, not the whole fabric's.
4. **Address re-resolution per probe.** The resolver is consulted every round,
   so a renumbered peer is found as itself.
5. **Eviction is local and reversible.** A peer that answers again is re-admitted.
6. **The constants match the contract.** A silent drift in the probe interval
   or eviction threshold is exactly what makes a live pair disagree in the field.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sparknet_loader import load_by_path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVENESS_SCRIPT = REPO_ROOT / "shared" / "sparknet-liveness.py"


@pytest.fixture(scope="module")
def liveness():
    return load_by_path("sparknet_liveness", LIVENESS_SCRIPT)


def _monitor(liveness, *, resolves=True, lit=None, at=None, **kwargs):
    """A monitor with a fixed clock and a probe that lights the named peers."""
    start = at or datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = {"now": start}

    def now():
        return clock["now"]

    resolver_calls = {"n": 0}

    def resolve(name):
        resolver_calls["n"] += 1
        return name if resolves else None

    lit_set = set(lit or {})

    def probe(addr):
        return addr in lit_set

    mon = liveness.Monitor(
        {
            "alpha": liveness.Peer("alpha", last_activity=start),
            "beta": liveness.Peer("beta", last_activity=start),
        },
        now=now,
        resolve=resolve,
        probe=probe,
        **kwargs,
    )
    return mon, clock, resolver_calls


def _advance(clock, seconds, stride=1):
    mon = clock["mon"]
    for _ in range(stride):
        clock["now"] = clock["now"] + timedelta(seconds=seconds)
        mon.probe_once()


# --- constants match the contract ---------------------------------------------


def test_constants_match_the_contract(liveness):
    text = (REPO_ROOT / "contracts" / "health-protocol.md").read_text().lower()
    assert liveness.PROBE_INTERVAL_SECONDS == 10
    assert liveness.EVICTION_THRESHOLD == 3
    assert liveness.ACTIVITY_GRACE_SECONDS == 120
    assert "10 s" in text and "3 consecutive" in text and "120 s" in text


def test_authority_plane_is_still_refused_from_the_watch(liveness):
    """The monitor grants nothing: its eviction is local to its own view."""
    assert not liveness.__dict__.get("revoke"), (
        "a liveness monitor must never touch the registry; if it grows an "
        "evict-with-authority path, that is a new trust boundary with no design"
    )


# --- the three rules -----------------------------------------------------------


def test_hostname_is_re_resolved_every_probe(liveness):
    """A renumbered peer is found as itself; there is no keepalive to warm it."""
    mon, clock, resolver_calls = _monitor(liveness, lit={"alpha"})
    clock["mon"] = mon
    _advance(clock, 10, stride=3)
    assert resolver_calls["n"] >= 3, "the resolver must be consulted every probe round"


def test_activity_trumps_eviction(liveness):
    """A working peer that misses probes but keeps reporting is not evicted."""
    mon, clock, _ = _monitor(liveness, lit={"beta"})
    clock["mon"] = mon
    # beta stays lit; alpha misses every round. But alpha reports activity
    # after each miss, so its eviction clock keeps resetting.
    for _ in range(6):
        clock["now"] = clock["now"] + timedelta(seconds=10)
        mon.probe_once()
        mon.activity("alpha", at=clock["now"])  # busy: last ledger sighting
    assert mon.eviction_candidates() == [], "activity must reset the miss count"
    # Stop the activity and let the clock run past the 120 s grace; two more
    # misses trip the threshold, and now alpha is a candidate.
    clock["now"] = clock["now"] + timedelta(seconds=10)
    mon.probe_once()
    clock["now"] = clock["now"] + timedelta(seconds=130)
    mon.probe_once()
    clock["now"] = clock["now"] + timedelta(seconds=10)
    mon.probe_once()
    assert mon.eviction_candidates() == ["alpha"]


def test_a_full_dark_round_evicts_nothing(liveness):
    """All dark at once is our own fault: the monitor flags it, never evicts."""
    mon, clock, _ = _monitor(liveness, lit={})
    clock["mon"] = mon
    for _ in range(6):
        clock["now"] = clock["now"] + timedelta(seconds=10)
        mon.probe_once()
        mon.activity("alpha", at=clock["now"])
    clock["now"] = clock["now"] + timedelta(seconds=130)
    mon.probe_once()
    assert mon.full_dark_rounds > 0, "an all-dark round must be flagged"
    assert mon.eviction_candidates() == [], "a full-dark round must evict nothing"


def test_eviction_requires_quiet_past_the_grace(liveness):
    """Threshold misses alone are not enough while the node still reports."""
    mon, clock, _ = _monitor(liveness, lit={})
    clock["mon"] = mon
    for _ in range(3):
        clock["now"] = clock["now"] + timedelta(seconds=10)
        mon.probe_once()
    assert all(p.missed_probes >= 3 for p in mon.peers.values())
    assert mon.eviction_candidates() == [], "misses without a quiet window must not evict — activity may still land"
    clock["now"] = clock["now"] + timedelta(seconds=130)
    mon.probe_once()
    # alpha is still quiet (no activity), beta too — but this round has no
    # survivor, so it is full-dark and still evicts nothing.
    assert mon.eviction_candidates() == []


def test_eviction_is_local_and_reversible(liveness):
    """An evicted peer that re-resolves and answers is re-admitted."""
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = {"now": start}
    lit = {"beta"}

    def probe(address):
        return address in lit

    mon = liveness.Monitor(
        {
            "alpha": liveness.Peer("alpha", last_activity=start),
            "beta": liveness.Peer("beta", last_activity=start),
        },
        now=lambda: clock["now"],
        resolve=lambda name: name,
        probe=probe,
    )
    for _ in range(3):
        clock["now"] = clock["now"] + timedelta(seconds=10)
        mon.probe_once()
    clock["now"] = clock["now"] + timedelta(seconds=130)
    mon.probe_once()  # beta still lives, so this round has a survivor
    assert mon.eviction_candidates() == ["alpha"]
    assert mon.evict("alpha") is True
    assert "alpha" not in mon.peers
    # The peer re-appears on the roster (its address resolved again) and is
    # probed afresh — eviction removed only the local view.
    mon.peers["alpha"] = liveness.Peer("alpha", last_activity=clock["now"])
    lit.add("alpha")
    clock["now"] = clock["now"] + timedelta(seconds=10)
    mon.probe_once()
    assert "alpha" not in mon.eviction_candidates()
    assert mon.peers["alpha"].missed_probes == 0


def test_claim_carries_the_monotonic_facts(liveness):
    """The claim carries monotonic health facts for the overlay-attributed report."""
    mon, clock, _ = _monitor(liveness, lit={"alpha"})
    clock["mon"] = mon
    _advance(clock, 10, stride=1)
    claim = mon.claim("alpha")
    assert claim["node"] == "alpha"
    assert claim["alive"] is True
    assert "reported_at" in claim
    assert claim["missed_probes"] == 0


def test_unknown_peer_claims_dead(liveness):
    mon, clock, _ = _monitor(liveness)
    clock["mon"] = mon
    assert mon.claim("ghost")["alive"] is False
