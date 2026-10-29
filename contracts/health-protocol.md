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
carrying its traffic the moment the registry says so), which is why a probe is
answered on a port that carries no authority at all and why this protocol only
ever proposes eviction *of the local monitor's view* — never a registry edit,
never a capability change. The claim a monitor sends is attributed by the
authenticated overlay, not by a signature this fabric cannot bind (see
Security properties).

## Probe rhythm

A monitor probes its known peers on a fixed rhythm:

| Rule | Value | Why |
|---|---|---|
| Probe interval | 10 s | long enough not to fight share churn, short enough to notice a death within the 20 min idle-close window |
| Probe target | address-only; **hostname re-resolved per probe** | a renumbered peer is found as itself, not remembered as a dead address — there is no keepalive to keep a stale mapping warm |
| Probe port | **4211**, a contracted non-serving probe port, never the serving path | the monitor must not make the service it watches do work, and a serving 500 must not look like death. 4211's only listener accepts a connection and closes it without reading or writing a byte |
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
monitor probes next cycle. The deployed service holds one roster built from the
signed registry, so an evicted peer is re-admitted when that registry is
republished (the roster's file changes) or the service restarts; a re-admitted
peer starts with a fresh missed-probe count. Eviction never writes the registry
and never touches `revoked`.

## Security properties

- **Attribution is the overlay; claims are unsigned.** A liveness claim is a
  `kind=liveness` telemetry report (`contracts/telemetry-schema.json`). Nothing
  in the fabric binds a peer fingerprint to a node signing key (Step 68A), so a
  node-key signature would be unverifiable theatre. The Master derives the
  sender's fingerprint from the WireGuard-authenticated source address via its
  own registry and refuses a report whose `peer_fingerprint` field disagrees
  (`wrong_peer`). The probe itself carries no envelope at all: it is a TCP
  connect to 4211 and an immediate close.
- **No new trust path.** Liveness arrives on the same Master 8090 intake as
  status and metrics, is gated by the same peer-held `telemetry` capability,
  and shares the same nonce/expiry freshness guard. Nothing here introduces a
  second signing vocabulary or a new authority-plane listener.
- **Privilege is unchanged.** A peer does not gain the ability to evict anyone
  real. A master does not gain the ability to revoke by another name. The
  protocol's eviction has no authority-plane effect, stated plainly so it is
  never mistaken for one.

## Implementation state

**Built, unit-staged, not running here.** `shared/sparknet-liveness.py` is the
one state machine (injected clock, the three rules pinned as constants);
`tests/test_liveness.py` exercises each rule. The peer service
`peer-node/services/sparknet-liveness-monitor.py` runs `ContinuousMonitor`
against registry-derived, signature-checked peers, binds the contracted
non-serving port **4211** (accept-and-close, no reads or writes), records an
inbound probe as activity, and pushes `kind=liveness` over the 70A telemetry
channel. Its unit is
`peer-node/systemd/sparknet-liveness-monitor.service`, wired through all three
installer touch points; `contracts/ports.json` marks 4211 `implemented` and
`not-verifiable-here` (this host has no overlay). Tests:
`tests/test_liveness.py` (rules) and `tests/test_liveness_service.py` (real
listener, registry roster, claim accepted by the real 8090 intake).

What is **not** confirmed here: cross-node behaviour (what a peer does when a
sibling it probes dies) is **DoD: confirm: user** — it depends on a live pair,
and no amount of clock-injected unit tests can claim it. The honest pair is the
same one the rest of the repo uses: the code is implemented and unit-tested,
nothing is deployed on this host, and the cross-node leg is a human's to confirm.
