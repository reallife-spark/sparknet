# proposal-protocol.md

The narrative behind `contracts/proposal-schema.json`: why a cross-user review
needs a first-class object, what the three records carry, how the lifecycle stays
fail-closed, and what a verified chain does and does not authorise.

## The gap this closes

A signed note already says *who wrote what, from which conversation*. It does
not say *here is a change I propose, here is what my peers think of it, and here
is the owner's decision*. That conversation, if it happens at all, happens in
chat — attributable to nobody in particular and gone by tomorrow.

A proposal is that conversation as data. Three records, each a signed ledger
block, each naming its agent and model, so the whole review is as auditable as a
note: the originating agent's work, every reviewer's verdict, and the boss's
approve/deny.

The peer event vocabulary gains exactly three events — `proposal`, `review`,
`decision` (`contracts/tracking-schema.json`). They are **peer** events: a peer
proposes and reviews; a master does not. The peer and master vocabularies stay
disjoint, which is the property a test pins.

## The lifecycle

```
draft ──submit──▶ submitted ──review──▶ reviewed ──decide──▶ decided
```

- **draft** is local and uncommitted. `build_proposal` produces it;
  `submit_proposal` consumes it. Nothing about an intention belongs on a chain
  that records commitments.
- **submitted** is the `proposal` block, signed and appended. The transition
  happens once: a record that is not a `draft`, or one already signed, is
  refused.
- **reviewed** is the arrival of the first `review` block.
- **decided** is the `decision` block.

Every transition re-reads the ledger and refuses out of order, before it appends
anything:

| Attempt | Refusal |
|---|---|
| review that names no proposal | no proposal block |
| review after a decision | the proposal is already decided |
| decision with no review | a decision needs at least one review |
| second decision | the proposal is already decided |

Because the ledger is append-only and its blocks are header-signed and chained,
the *physical* order cannot be rearranged. `verify_proposal_chain` enforces the
*logical* order on a bare list of records, so the same rules hold for a bundle
that arrived over the wire (Step 36) as for the local chain.

## The records

Each record is self-contained, and each carries the same dual-control envelope an
approval carries:

- `signatures.user` — the user key over the record: **consent / attribution**.
- `signatures.node` — the node identity key over the same bytes: **attestation**
  that this node recorded it.

Then `append_block` adds a third, independent node signature over the whole block
header, and the block `hash` binds that signed block into the chain. Three keys,
three meanings, one block — no new signature scheme.

A **proposal** carries the originating agent's work: `title`, `summary`, the
`agent` and `model`, and the `conversation` that produced it. The conversation is
committed by its RFC 6962 `conversation_root` (the same root Step 35 added to
notes), one line of the signed message, so appending, editing or dropping an
entry moves the root and invalidates the record.

A **review** carries the reviewer's `verdict` (`approve` / `reject` /
`request_changes`), their `reason` verbatim, and the reviewing `agent` and
`model` — so an opinion is never anonymous.

A **decision** carries the owner's `decision` (`approved` / `denied`), their
`reason`, and the recording `agent`/`model`. The `owner_id` is the boss; a
decision is the owner's to make.

## Why the keys travel inline

A note verifies against the *local* `user.md`, because it never leaves the vault.
A proposal is meant to cross nodes, so its records carry
`user_public_key_b64` + `user_key_fingerprint` and `node_pubkey_b64` inline. A
receiver verifies the bytes with no local key material — the same reasoning the
co-signature entry in `tracking-schema.json` gives.

This separates **integrity** from **identity**, exactly as a co-signature does.
A byte-intact record proves three things: the conversation re-roots, the
fingerprint matches the key, and both signatures verify over the bytes. It does
not, by itself, prove *who* the signer is. Identity is resolved separately
against the Master-signed registry or a `user.md` snapshot — the same two
resolvers co-signatures use. `verify_proposal_chain` owns integrity and order; it
returns the signer identities for the caller to resolve.

## What a verified chain is not

A verified chain is not an executed change. A proposal records an intention, a
review records an opinion, a decision records the owner's verdict. **None of them
edits a note or grants a capability.** Acting on an approved proposal is a
separate, grant-scoped write (`grant_use`, Step 3), so the review is a decision
*record*, not an authority to write. The capability contract is unmoved: an
approved proposal still needs a signed session grant to change anything.

## Transport

The records are self-contained precisely so the exchange can carry them over the
existing share ports (4201 `share-intake` / 4202 `session-transfer`) without a
new port, and a receiver can verify the chain offline. The proposal exchange is a
new **message family** on those ports — `proposal.submit`, `proposal.review`,
`proposal.decide` (`contracts/proposal-schema.json` `transport`) — not a share
type: a share conveys a knowledge read or a copy and a proposal conveys neither,
so `capabilities.share_types` stays closed.

A message carries a **bundle**: the ordered list of proposal/review/decision
records exchanged so far. Each node appends only the records it authors — the
proposal on the proposer's ledger, a review on its reviewer's, the decision on
its owner's — because a block whose `data.signatures.user` is another author's
key would fail that node's own ledger verification. `verify_proposal_chain`
checks the union, so a receiver verifies a chain whose records live on other
nodes with the shared ladder before it signs anything; a refused bundle appends
nothing. `peer-node/services/sparknet-proposal-exchange.py` delivers the round
trip; `peer-node/services/sparknet-share-regime.py` recognises the family and
routes it (`accepts_message` / `proposal_route`). Live cross-node exchange over
the overlay is `DoD: confirm: user`.
