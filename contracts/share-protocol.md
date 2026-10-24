# Share protocol — the contract between two peers, arbitrated by a Master

Both roles implement this conversation. The peer side landed in
`peer-node/PLAN.md` Steps 6 and 8, the Master side in
`master-node/plans/MASTER_BUILD_PLAN.md` Steps 10–12, so the offer lifecycle, the
four clocks, the trust levels and the reconciliation rules are built and tested —
against in-process node pairs with injected clocks, on a host that has no
overlay.

What is **not** built is the deployment. `peer-node/manifests/share-regime.json`
records the status as `wired, not deployed`, and its `not_built_yet` names the
live 4201/4202/4203 listeners, the stanza application and nftables exception, the
Master's ratification service and the Master-hosted evidence repo; those are
target-node legs marked `DoD: confirm: user`. `contracts/ports.json` says the same
thing in its own vocabulary — 4201 and 4202 are `implemented` in code and
`not-listening` at runtime, and 4203 is still `spec-only`.

The normative machine-readable policy is `contracts/capabilities.json`
(`share_types`, `trust_levels`), `contracts/identity-schema.json` (`grant`),
`contracts/overlay.json` (`governance_mode`, `data_plane_stanza`) and
`contracts/ports.json`. This page is the narrative contract, and it says
nothing those files do not already say.

## What a share is, and what it is not

A share lets one node reach another node's material for a bounded time, under a
grant, with the whole exchange recorded. It is **not** an authority transfer. A
node on the receiving end of a `full` share still cannot sign anything, cannot
grant a capability, and cannot change its own protected files — because authority
comes from key possession and the signed envelope, never from being talked to.

This distinction is the whole reason the vocabulary in `capabilities.json` splits
share types from trust levels, and the reason a share type can be narrowed on
receipt without ever widening what the receiver believes.

## The asymmetry, restated for shares

A peer can **receive** a share and **offer** one, but it cannot **ratify** one.
Ratification needs the Master key. In a two-node mesh there is no Master
arbitration and the two peers are symmetric; that case is not a degraded mode,
it is the specified one, and it is reasoned in `overlay.json` under
`governance_mode.modes.peer_pair`.

## Offer lifecycle

```
sender drafts an offer naming a share type and a window
        │
        ▼
INVITE     recipient has 1 h to accept; after that the offer is dead
        │
        ▼
ACCEPT     both nodes are unauthenticated + flagged; share opens
        │
        ▼
RATIFY     Master has 2 h. Silence is a refusal.
        │        peer_pair: no Master step exists, and none is required
        ▼
IDLE       closes after 20 min without use, and always at 10 h
        │
        ▼
CLOSE      both endpoints log the close; the data-plane stanza is torn down
```

Every transition is a signed event in the ledger. A share whose open or close is
absent from the ledger is a detectable fault, not an unrecorded convenience.

## The four clocks

Four deadlines, and they are not interchangeable:

| Clock | Length | Whose it binds | Silent expiry means |
|---|---|---|---|
| Invite acceptance | 1 h | recipient | offer never happened |
| Idle close | 20 min | both | share lapsed |
| Master ratification | 2 h | Master | share was refused |
| Absolute share life | 10 h | both | share ended |

**All four are enforced locally by both peers against their own clocks, and all
four are clock-injected so their tests run in seconds rather than in hours.** An
unreachable Master must cause a share to expire, never to persist: the Master is
an arbiter of survival, not a holder of the lock. That is why the 2 h clock has
no "awaiting" state — the absence of an answer is an answer.

The absolute 10 h cap is not adjustable per share. A sender that wants longer
offers a new share after a human decision, rather than a longer window inside one
that no reviewer is watching.

## Isolation

Isolation severs the **fabric data plane** — KB sync, the peer mesh, and every
other node — while the **authority and evidence channel to the Master stays
open**.

This is a deliberate reading, and it is the one recorded in `overlay.json`. The
alternative reading, severing the Master link too, would make the review this
protocol exists to satisfy unsatisfiable: the Master's review agents could never
see the evidence the isolation was raised over, because the evidence channel is
what the isolation destroyed. The chosen reading is recorded so that if it proves
wrong, the alternative is visible rather than forgotten.

Isolation is not a revocation. It stops traffic; it does not change either node's
trust level, and it does not touch `revoked` in the registry.

## What isolation does not reach

The data-plane stanza that carries a share is separate from the authority plane,
and isolation does not widen or narrow the authority plane. Concretely:

- Registry distribution, guard approval, and every other authority-plane message
  remain Master-only at `10.100.0.1/32`. `overlay.json`'s single-address
  `AllowedIPs` rule is unchanged in every governance mode.
- A data-plane stanza's trust basis is a share grant naming the counterpart's
  fingerprint, never the fact that a packet arrived from an overlay address.
- A stanza grants no authority: a node reached over one can be persuaded to
  nothing its own operator could not also do.

The reason for the separation is source-address confusion. The authority plane
admits exactly one address precisely so that "arrived from the overlay" can mean
"arrived from the Master"; a sibling on the data plane would otherwise be able to
present itself as the Master.

## Ratified shares keep their flag

Ratification authorises the share. It does **not** clear the flag.

Both nodes enter an accepted share as `unauthenticated` and `flagged`. On
ratification they become `authorized` with the flag **retained for audit**. The
reasons, in `capabilities.json`:

- Approval is not evidence that nothing happened. Unapproved data crossed between
  nodes, and that is a fact about the world that survives the decision about it.
- The events worth reviewing are exactly the ones where someone expected review
  and did not get it. A flag that vanished on approval would make the review
  mechanism blind to its own most interesting input.
- An EU AI Act evidence request asks what happened and what was decided after.
  Both halves need the unapproved period to still be visible.

A trust level records a belief, never a permission. Only the Master moves them,
only as signed events in the registry with a reason, and a model's summary of the
evidence may inform that decision without ever being it.

## Two nodes, three nodes

Governance mode is computed from the signed registry's node count, never from
configuration, so a node cannot opt out of review by setting a flag.

- **Two nodes** — `peer_pair`, symmetric. They verify shared information against
  their existing knowledge base instead of arbitrating through a Master. KB
  reconciliation is additions and conflicts only; a receiver never silently
  overwrites an existing page.
- **Three or more** — `master_governed`. The Master arbitrates every cross-node
  share, peer-to-peer ones included.
- **A third node joining mid-share** re-evaluates that share rather than
  grandfathering it. The share ends and may be re-offered under the new mode.

## Reconciliation

On `kb-share`, arrival merges by additions and conflicts, never by silent
overwrite. A conflicting page is held for a human and flagged. Both directions
are recorded, because a share that only reports what the receiver gained is not
an audit trail.

## The proposal exchange rides these ports

The share ports also carry the **proposal exchange** — a sibling message family,
not a share type. A proposal, a review and a decision
(`contracts/proposal-schema.json`) travel as `proposal.submit`,
`proposal.review` and `proposal.decide` on ports 4201 (`share-intake`) / 4202
(`session-transfer`). No new port is opened, and `capabilities.share_types` stays
closed: a share type states what a share *conveys* (a knowledge read or a copy),
and a proposal conveys neither, so admitting one would put a member in the
narrowing relation that cannot be ordered against `kb-view` or `session-handoff`.

The two families share a transport but not a lifecycle. A share is clocked and
ratified; a proposal is ordered and countersigned. The message carries a
**bundle** — the ordered list of proposal/review/decision records exchanged so
far — and each node appends only the records it authors (the proposal stays on
the proposer's ledger, a review on its reviewer's, the decision on the owner's).
`shared/sparknet-proposal.py` `verify_proposal_chain` checks the union, so a
receiver verifies a chain whose records live on other nodes before it signs
anything; a bundle that fails the ladder is refused and appends nothing.

A verified proposal chain grants no authority, exactly as a share does not: an
approved proposal records the owner's verdict and still needs a signed,
grant-scoped write to change anything.

## What is not contracted here

- **Delivery of the shared material.** Transport, encryption and compression are
  peer-side implementation, constrained by `data_plane_stanza` but not specified
  by it.
- **Which pages a share covers.** That is `vault_scope` on the grant, signed per
  share, not a property of the type.
- **Any offline behaviour.** Offline signing exists while the Master is unbuilt,
  but it has no revocation channel, and `identity-schema.json` records it as
  weaker rather than equivalent.
