---
title: What PAIR membership implies for sparknet re-formation
updated: 2026-10-08
type: synthesis
---

# What PAIR's membership model implies for sparknet re-formation

A cross-cut between [[pair-architecture-review]] (`nvpair-cluster-manager`) and
the open re-formation section of `contracts/consensus-protocol.md`. The
conclusion: the chain properties PAIR uses for **membership** are exactly the
missing pieces for sparknet's **authority** re-formation, and they can be
adopted without adopting PAIR's trust model.

## The gap restated

`consensus-protocol.md` §Re-formation is blunt about two holes:

1. **The unsatisfiable reduced root.** With unanimity at n of n, a full cluster
   losing one member leaves two survivors who cannot form a new root; a pair
   leaves one. Re-formation is needed precisely when it is impossible.
2. **How a re-formed root reaches a peer.** The old root is locally
   indistinguishable from the new one, and announcing over a channel the
   superseded Master controls is how a rolled-back Master suppresses the news
   of its own replacement.

## What the PAIR chain gives each

**For (1):** PAIR's monotonic admission epoch + endorsement chain turns
"unanimity must hold for the roster to change" into "unanimity must hold at the
**epoch where a node joins or is named"**. A *reduction* is then not a new
membership — it is a signed removal, evidenced in the chain, verifiable offline
and surviving restart. Mapped to sparknet: a reduced root (survivors forming a
new root) descends from the old one by removing *exactly* the members whose
`revoked`/departure is evidenced in the chain, and a lone survivor holds a
tombstone, not a root — preserving "a cluster cannot survive below its minimum
of two".

This is option **B** (majority-to-reduce, unanimity-to-grant) given a concrete,
collusion-guarded shape: a Byzantine majority can only *shrink* (the denial
unilateral revoke already allows), never *add* authority. Options A and C stay
on the table as policy.

**For (2):** PAIR reaches a roster **fixpoint by re-scanning** — membership
changes are *pulled*, not pushed. Sparknet already has a pull-shaped channel
(the peer↔peer share handoff). A new root therefore reaches a peer through the
peer's *next pull from any member of the new root*, verified by the chain from
(1), rather than by a broadcast the superseded Master can suppress. The
lease-not-broadcast constraint is kept, but satisfied by *ordering* instead of
by channel monopoly.

## What does not transfer

- PAIR's central cluster-manager and its unilateral removal — replaced by the
  root carrying its own membership and the 1-sig revoke.
- Any fourth membership or authority widening — the 2..3 bound is untouched.
- Any claim of a working system: the design is a proposal, nothing in
  `contracts/` adopts it until an operator picks A/B/C.

Proposed owner decision path: `master-node/plans/PAIR_REFORMATION_DESIGN.md`.

Related: [[admission-epoch]], [[activity-trumps-eviction]],
[[two-personality-listener]], `contracts/consensus-protocol.md`,
`contracts/identity-schema.json`.