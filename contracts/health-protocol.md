# Health protocol — peer liveness, probing and eviction

The narrative contract for how a peer treats a sibling's *presence* on the
overlay, distinct from the authority plane. Presence is data-plane belief:
whether a node answered a probe recently, not whether it may sign anything.

Adapted from NVIDIA Personal-AI-Router's `nvpair-node-scanner` (probe rhythm)
and `nvpair-manual-nodes` (operator-pinned nodes) after review of the PAIR
repository (Apache-2.0; transcript and mapping in the fabric knowledge vault).
The rules survive translation to WireGuard wholesale; only the *discovery
mechanism* changes, because mDNS multicast cannot cross the gateway. Sparknet
peers are discovered by signed registry entry, not by a LAN broadcast.

## Why there is no liveness today, and why there is now a floor

Before this protocol, a peer had share clocks but no notion of whether the
node at the other end of a share still *exists*. A grant could be issued to a
node that had been replaced months ago; nothing expired a peer from the local
view. This contract is the first rule *version* of that gap: it makes presence
a monotonic, probeable, evictable fact without leaning on the authority plane
for anything.

It deliberately grants no authority. Liveness is a belief about a data-plane
address. A revoked node can still answer a probe (the overlay does not stop
carrying its traffic the moment the registry says so), which is why probes are
signed and why this protocol only ever proposes eviction *of the local
monitor's view* — never a registry edit, never a capability change.

## Probe rhythm

A monitor probes its known peers on a fixed rhythm:

| Rule | Value | Why |
|---|---|---|
| Probe interval | 10 s | long enough not to fight share churn, short enough to notice a death within the 20 min idle-close window |
| Probe target | address-only; **hostname re-resolved per probe** | a renumbered peer is found as itself, not remembered as a dead address — there is no keepalive to keep a stale mapping warm |
| Probe port | a non-serving probe port, never the serving path | the monitor must not make the service it watches do work, and a serving 500 must not look like death |
| Probe failure | consecutive misses, clock-measured | one dropped packet is noise; N consecutive misses is a fact |

## The three rules that keep it honest

These are the two scanner clauses and one manual-nodes clause, translated.

1. **Activity trumps eviction.** A busy node is the one least likely to answer
   an announcement. Any recent ledger or telemetry activity from a peer resets
   its missed-probe count, so a node that is *working* is not punished for not
   answering a status ping while it works.
2. **A scan that loses everything is our own fault.** If a probe round finds
   *every* known peer dark at once, the fault is the monitor's own link, not
   the whole fabric's. A full-dark round evicts nothing and flags itself; only
   a round with at least one survivor may consider eviction.
3. **Probe the non-serving port.** A monitor probes a port kept for probes,
   separate from the serving path. The thing being watched must not be able to
   become the thing watching.

## Eviction

A peer is evicted from the local monitor's view when, at a probe round that
has survivors:

- its missed-probe count reached the threshold (**3 consecutive**), and
- it has been quiet for at least the activity grace (**120 s**) since its last
  ledger or telemetry activity, and
- the round is not a full-dark round.

Eviction is **local and reversible**: it only removes the peer from what this
monitor probes next cycle. If the peer's address resolves again it is probed
again and, on success, re-admitted with a fresh missed-probe count. Eviction
never writes the registry and never touches `revoked`.

## Security properties

- **Probed and probing are signed.** A liveness claim is a signed envelope
  like any other (the shared transport refuses unsigned traffic), so a node
  that the registry no longer trusts cannot fabricate a clean bill of health —
  the capability gate for *claims* is the same one that gates everything.
- **No new trust path.** Liveness arrives over the overlay and is verified by
  the same key the peer already trusts; nothing here introduces a second
  signing vocabulary.
- **Privilege is unchanged.** A peer does not gain the ability to evict anyone
  real. A master does not gain the ability to revoke by another name. The
  protocol's eviction has no authority-plane effect, stated plainly so it is
  never mistaken for one.

## Implementation state

**Designed, with a shared reference monitor.** `shared/sparknet-liveness.py`
implements the probe+eviction state machine with an injected clock and the
three rules above pinned as constants; `tests/test_liveness.py` exercises each
rule. What is **not** built yet:

- a live probe service or systemd unit on either role that runs the monitor
  against a real overlay (there is no overlay on the development host);
- a signed liveness *endpoint* on a peer (the natural host is the guard's
  `/api/v1/status` family, extended to the shared transport);
- cross-node behaviour (what a peer does when a sibling it probes dies) is
  **DoD: confirm: user** — it depends on a live pair, and no amount of
  clock-injected unit tests can claim it.

The honest pair is the same one the rest of the repo uses: `implemented`
reference code, nothing deployed here, and the cross-node leg explicitly
confirmed by a human on a live pair.