---
title: Admission epoch
updated: 2026-10-08
type: concept
---

# Admission epoch

A strictly increasing counter on a cluster's membership roster that advances on
every change, so **two rosters are ordered by their epochs without a global
clock**. From NVIDIA PAIR's `nvpair-cluster-manager` `spec.md`, where it is
paired with two other properties sparknet's re-formation currently lacks:

1. **Endorsement chains** — each change is endorsed by the members authorised
   at the *previous* epoch, so roster history is a chain, not a set.
2. **Removal proofs that survive restart** — the evidence of a removal is
   durable and offline-verifiable, and the removed node must present it before
   acting again ("proof before re-pin").

Sparknet's trust root already has the raw material: `nonce` seeds uniqueness,
the 1-signature revoke is a safe denial, and `check-not-reverted` keys the
signer on `root_id`. What is missing is the **ordering** — two roots with
different nonces are only ordered by something outside themselves (the open gap
in `contracts/consensus-protocol.md` §Re-formation).

The design proposal that maps the epoch onto sparknet's unanimity lives at
`master-node/plans/PAIR_REFORMATION_DESIGN.md`. The mapping is not a copy:
PAIR's unilateral removal falls away in favour of the 1-sig revoke, and its
central cluster-manager falls away in favour of the root carrying its own
membership. Three policy options (A keep-count / B majority-to-reduce /
C join-first) remain a human decision; this concept is the *shape* option B
would take.

Related: `[[pair-architecture-review]]`,
`[[what-pair-membership-implies-for-sparknet-reformation]]`,
`contracts/consensus-protocol.md`, `contracts/identity-schema.json`
(`cluster_trust_root`).