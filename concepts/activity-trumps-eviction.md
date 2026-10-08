---
title: Activity trumps eviction
updated: 2026-10-08
type: concept
---

# Activity trumps eviction

The liveness rule that a **busy node is the least likely to answer an
announcement**, so recent activity resets its eviction clock. From NVIDIA
PAIR's `nvpair-node-scanner` README, and the reason a node that is *working* is
not punished for failing a status ping.

Sparknet form (`contracts/health-protocol.md`, `shared/sparknet-liveness.py`):

- a probe misses are **consecutive** and measured by an injected clock;
- any ledger or telemetry sighting of a peer resets its missed-probe count;
- eviction still needs three conditions: the round had survivors, the peer has
  been quiet past the activity grace (120 s), and the misses reached the
  threshold (3).

Its two companion rules keep it honest:

1. **A scan that loses everything is our own fault.** If a probe round finds
   every known peer dark at once, the monitor's own link is broken, not the
   whole fabric's — a full-dark round evicts nothing and flags itself.
2. **Probe the non-serving port.** The monitor must never touch the serving
   path, so the thing being watched cannot become the thing watching.

Eviction is **local and reversible**: it only drops a peer from the next probe
round, never from the registry, and a peer whose address re-resolves is
re-probed and re-admitted. Eviction grants nothing — it is data-plane belief,
deliberately not an authority effect.

Related: `[[two-personality-listener]]`, `[[pair-architecture-review]]`,
`contracts/health-protocol.md`, `shared/sparknet-liveness.py`.