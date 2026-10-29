# Provenance protocol — who wrote this, for whom, and who approved it

This is the narrative contract for accountability inside a role vault. The
normative machine-readable form is `contracts/tracking-schema.json`
(`sparknet-tracking/1`); this page says why the bytes look the way they do and
what a reader may conclude from them.

What is built and what is not: the layout, the tracking block, the user record,
the ledger records, the secret index and the local signing tooling are built.
**One node-to-node delivery leg is built too: a Master-signed RFI answer pushed to
`POST /api/v1/rfi` on the guard (9090) and installed into `01_Inbox/` with an
`inbox_acceptance` record** (`contracts/rfi-schema.json`, fabric Step 67D). The
email service, the RFI *request* leg, and the dispatch bridge as a server remain
specified, not built. Every rule below that describes who may act on an arriving
item is a policy; for the RFI answer channel a listener now enforces it, and
`contracts/ports.json` names the route that says so.

## The chain of accountability

```
00_System/user.md ── owner_id U-#### + public key + fingerprint
        │
        ├── every note (01–07): tracking.signature, an Ed25519 signature
        │       over the note's body hash and tracking hash,
        │       verifiable offline from a bare clone with only user.md
        │
        ├── blockchain/ledger.json: approval / report / share /
        │       inbox_acceptance blocks, each carrying user consent AND a
        │       node countersignature over the same payload
        │
        └── trace-back: note → tracking.conversation → the conversation
                        note → tracking.sources      → the inbox item
                        note → tracking.approvals[]  → the ledger block
```

A note is attributable to an owner, a conversation, a source and an approval
without any plaintext secret existing anywhere in the vault. The private key
never enters git, never enters a bundle, and is never needed to *verify* —
verification is a public-key operation over files a clone already has.

## Why the numbered layout

The wiki category layout (`concepts/`, `entities/`, `_raw/`, …) was organised
for a human browsing a vault. The numbered layout is organised for a pipeline:
`01_Inbox` is where things arrive, `03_Sources` and `04_Evergreen` separate what
was captured from what was refined, `05_Knowledge` is the compiled layer, and
`00_System` holds the rules that say how any of it may change.

The vendored wiki suite is pinned upstream and must not be edited
(`make wiki-verify`), and it reads the legacy names. So each legacy name stays
at the role root as a **symlink** into the numbered tree: both spellings resolve
to one file, there is no duplicate page, and `make shims-check` fails if a shim
ever becomes a real directory. The fabric root vault keeps the category layout
unchanged; this protocol applies to role subvaults.

## The note

Every note in `01_Inbox` through `07_Archives` — including `06_Projects` —
carries a `tracking` block in its YAML frontmatter (hidden in previews) with
`owner_id`, `owner_node`, `owner_ref`, `validity`, `conversation`, `shares`,
`agent`, `model`, `approvals` and `signature`. The schema is closed:
`sparknet-tracking/1` or the note is not one of ours.

The signature covers four hashes, not the raw text: the body hash, the
canonical hash of the frontmatter *outside* `tracking` (the compiler's field
zone), the canonical tracking hash with `signature` stripped, and the RFC 6962
root of the `conversation` entries — recorded in the envelope as
`signed_body_sha256`, `signed_meta_sha256`, `signed_tracking_sha256` and
`signed_conversation_root`, under the message domain `sparknet-note/2` (carried
in the envelope as `note_version`). The envelope also carries `signed_meta`, the
metadata mapping itself, so a verifier can name *which* keys moved rather than
merely observe that a hash differs. Recording what was signed is what makes
"edited since signing" a *detectable* state rather than a guess. The
conversation root binds the who/when/which-model trail (`tracking.conversation`)
to the note's own bytes: appending, editing or dropping a turn moves the root
and the note fails verification until it is re-signed.

### stale is not invalid

Automated rewrites are normal — the wiki compiler bumps `updated`,
`base_confidence`, `lifecycle`, `tier`, `summary`. If every such rewrite looked
like tampering, the verification signal would be worthless within a day. So
`make provenance-verify` distinguishes:

| Outcome | Meaning | Exit |
|---|---|---|
| `valid` | hashes match the envelope, signature verifies against user.md | 0 |
| `stale:metadata` | only allowlisted compiler fields changed; expected | 0 |
| `stale:content` | the body or a non-allowlisted field changed without re-signing | 2 |
| `invalid` | signature does not verify, or names another key, or is missing | 1 |
| `pending` | an inbox item awaiting acceptance | 0 |

Classification is **allowlist-based, never percentage-based**. A numeric delta
threshold is gameable by editing a little at a time; producing a valid signature
at all requires the private key at mode 0600. The report still prints a body
delta, because a human reviewing a 40% rewrite wants to know.

`--strict` promotes `stale:content` to failure and is what `make precommit`
runs. The standing rule is in `00_System/alpha-agent.md`: whoever writes a note
re-signs it and bumps `updated` in the same operation.

## Co-signatures

A note has one author, but accountability sometimes needs a second voice: a
reviewer, on another node, attesting that the bytes are what the author signed.
`sign_note` refuses a note whose `owner_id` differs, so a second user cannot
re-sign without stealing authorship. A **co-signature** is how they attest
instead, and it never rewrites the original author.

A co-signature lives in `tracking.signature.co_signatures[]`, a sibling of the
primary `sig`. Because the primary tracking hash is taken with the whole
`signature` key removed, appending a co-signature **cannot** invalidate the
primary signature: the note keeps its `owner_id` and still verifies `valid`. Each
entry carries `alg`, `owner_id`, `owner_node`, `public_key_b64`,
`key_fingerprint`, `sig` and `signed_at` — a user-record snapshot plus a
signature.

The co-signature's `sig` is over the **same** `sparknet-note/2` message the
primary signature covers, rebuilt from the primary envelope's four recorded
hashes. It therefore commits to the *identical* bytes; a co-signature over
anything else does not verify. `add_co_signature` signs with this vault's user
key, and re-running it from the same key replaces the entry rather than piling
up.

### The trust rule

A signature proves a key; it does not say the key belongs to anyone in
particular. A co-signature is only meaningful once the co-signer resolves to a
known identity, and there are exactly two resolvers:

1. **The Master-signed registry** (online) — the co-signer's `owner_node` names a
   **non-revoked** authorization in `manifests/node-authorizations.json` whose
   signature verifies under the registry's own master key. The Master has
   attested the node, and the node's user key travels with the note.
2. **The origin `user.md` snapshot** (offline fallback) — the entry's `owner_id`,
   `owner_node` and `key_fingerprint` match a trusted user record the verifier
   already holds. This is the user-key half of the origin node's
   `00_System/user.md`; it needs no running service, exactly as note
   verification does not.

`verify_co_signatures` checks byte integrity first and trust second. It refuses a
`key_fingerprint` that is not the fingerprint of the entry's own `public_key_b64`
(a swapped key) and a `sig` that does not verify over the recorded hashes (a
co-signature over different bytes) as `invalid`. An entry that is byte-intact
but resolves through neither resolver is reported **`untrusted`** — the bytes are
genuine, the signer is simply unknown here — so a reader can tell a forgery
apart from a stranger.

A co-signature attributes and attests; like the user key itself, it grants no
capability. Authority still comes from the capability contract and key
possession.

## The user record

`00_System/user.md` ships as a template and is **filled once per node** by
`make user-init`, which generates the fourth key scope — `user`, distinct from
`cluster`, `operational` and `identity` — through `shared/sparknet-authz.py`.
The record holds the public key, its fingerprint and identity tags only; the
allowlist test fails on any other frontmatter key, any private-key block, and
any base64 run outside `public_key_b64`. The private half goes to
`$SPARKNET_STATE_DIR/keys/user.ed25519`, mode 0600, and `.gitignore` blocks
`*.ed25519` and friends as a second line under `make keys-check`.

The user key **consents and attributes**. It grants no capability: authority
still comes from `contracts/capabilities.json` and from key possession, exactly
as before. A user signature on a note says "this is mine"; it says nothing about
what this node is permitted to do.

## Approvals live in the ledger, and only in the ledger

There is no `approvals.md`. The design dropped it deliberately: a human-readable
mirror that everyone reads and no test checks is a second source of truth waiting
to drift from the first. `blockchain/ledger.json` is authoritative, and
`make provenance-verify` proves three things about it: the hash chain is intact,
each approval block's dual signatures verify, and every `tracking.approvals[]`
id in every note resolves to a block.

An approval block carries `data.event = "approval"` with the question, the
decision, the asking agent and model, the notes it attaches to, the node's public
key inline (so an offline verifier needs no local key material), and two
signatures over the same payload: **user consent** and **node countersignature**.
Separate keys, separate meanings — a node that can write the ledger cannot mint
user consent, and a user key without the node key cannot place a block in the
chain. The block-level `signature` is a *second* signature by the appending
node's key over the whole block **header** (the block minus `hash` and
`signature`), not a restatement of the node countersignature; `hash` then binds
the signed block. `verify_chain` checks that header signature against the
block's own `node_pubkey_b64`, so a block whose timestamp, `prev_hash`, payload
or position was edited is refused even if `hash` is recomputed — which is what
stops a `grant_use` block being deleted to un-consume its nonce.

Peer-written events are `approval`, `report`, `share`, `inbox_acceptance` and
`grant_use`. Master events are the disjoint set in `tracking-schema.json`; a peer
writing one is a contract break, because only the Master can observe what those
events describe.

## Signed session grants

A grant (`contracts/identity-schema.json` `grant`) is the signed artifact every
knowledge write is authorised by — it replaces the conversation-hash heuristic
with an artifact that names the node, the user, the conversation and the vault
scope, issued by the Master or the offline operator key under
`shared/sparknet-authz.py sign --master-key` while the Master is unbuilt.

Minting and verification both live in `shared/sparknet-authz.py` — the one
crypto implementation. Verification is `contracts/identity-schema.json`
`grant.verification_order`, which is guard-protocol.md's check order unchanged:
signature → registry fingerprint not revoked → capability subset → expiry →
nonce never used on this node → the presenter is the node the grant names. Every
rejection is fail-closed: forged, expired, replayed, nonce-reused and
out-of-scope writes land nothing at their target.

Exercise of a grant is recorded in the ledger as a `grant_use` block, dual-signed
like an approval and hash-chained, naming the grant, its parent (for a delegated
subagent grant), the acting session and the note(s) written. An out-of-scope
write is quarantined to `_raw/` and recorded as `decision: quarantined`, so
authority is never widened by a signature and material is never silently lost.

## Signed checkpoints and cross-node head anchoring

A `checkpoint` ledger block is a peer's signed statement about its own head.
Its `data` carries three numbers that name the head: `size` (the number of
blocks in the chain), `head_hash` (the newest block's `hash`) and `root` — the
RFC 6962 Merkle root, computed by `shared/sparknet-merkle.py`, of every block
hash in the chain. Nothing is self-referential: `size` is the chain *before*
the checkpoint is appended, so the block becomes the oldest block of the next
snapshot and never hashes its own root. The block is signed by the node key
like every block — the header signature is the whole commitment, there is no
`data.signatures`, because there is no user consent to reproduce (unlike the
approval/report/grant_use records above).

`checkpoint` is a **peer** event, disjoint from the Master vocabulary: a
checkpoint is a statement about a peer chain, and only the peer that owns the
chain can sign it. Step 70E closes the periodic-anchor gap without a new port:
`peer-node/services/sparknet-checkpoint-anchor.py` (oneshot, on a 15-minute timer)
appends a checkpoint when the head has moved, then pushes the full signed block
as `kind=checkpoint_anchor` telemetry over the existing 8090 intake. Re-running
over an unchanged head appends nothing — the newest block already snapshots
every block before it — and re-pushes the same evidence; an empty ledger exits
silently. The receiver verifies the block with `verify_checkpoint` before
recording it, so the Master holds the signature, not just a root. The
anchor/verify pair itself remains exercised in-process (PLAN Step 36).

A node that receives another node's signed checkpoint **anchors** it. Anchored
state is kept in the receiver's state dir
(`$SPARKNET_STATE_DIR/anchored-checkpoints.json`, mode 0600 — runtime state,
never the vault), keyed by the signing node's public key, so each node's head
is tracked independently:

- the **first anchor** for a node establishes the baseline;
- a checkpoint of **smaller size** than the anchor is a **rollback** and refused;
- the **same size** must carry the **same root** — a different root is a
  **fork** and refused;
- **growth** must carry an RFC 6962 consistency proof
  (`verify_consistency`, from `shared/sparknet-merkle.py`) from the anchored
  root to the new root, with an advanced head.

The consistency mechanism is what makes truncation and forked history
*detectable* instead of merely editable: a node's history grows only by a
proof that the new root extends the one an outsider already trusts, it can
never be rolled back below what anyone has anchored, and two histories of the
same height cannot both pass. The mutation legs (break the consistency proof,
roll back the size, fork the root) are exercised in-process in the test suite;
a live cross-node leg over the overlay is `DoD: confirm: user`.

## Inbox dispatch — a policy, not a pipeline

`01_Inbox` is read-only for agents until an item is accepted. Acceptance is
recorded as an `inbox_acceptance` block; if the item is untrusted, a reviewer
agent sanitizes it before anything downstream reads it.

- source `master-node` → may be executed on notice (the Master is the signing role);
- source `peer-node` → executes only on acceptance, after review and sanitize;
- source `email` → the sender must be on the authorized list in
  `00_System/user.md`, then treated as peer-origin.

The peer reviewer is built: `agents/vault-curator` is a deterministic CLI (no
listener) that refuses untrusted ingress without an accepted, `sanitized: true`
`inbox_acceptance` naming it, strips active content outside fenced code, refuses
instruction-like text unless explicitly allowed, sets `validity.state:
sanitized` and signs the reviewed bytes with the user key. Accept with
`make -C peer-node accept-inbox ITEM=01_Inbox/... SOURCE=... REVIEWER=agents/vault-curator SANITIZED=1`,
then review with `make -C peer-node review-inbox ITEM=01_Inbox/... APPLY=1`.
Reviewer agents: `agents/vault-curator` on a peer, `.opencode/agents/evidence-reviewer`
on the Master. The RFI *answer* leg of the transport is built — a Master-signed
answer arrives on `POST /api/v1/rfi` (guard, 9090) and is installed with an
`inbox_acceptance` record; the email service and the RFI *request* leg are not.

An item that arrives over the transport is also **notified** to the human, because
acceptance is a human act and an unnoticed item is an unaccepted one. The node's
own mechanism is `shared/sparknet-notify.py` — a durable arrival spool
(`<state-dir>/notifications/arrivals.jsonl`, 0600) plus a best-effort KDE Connect
ping — not the fabric-root plugin (`scripts/plugins/kde-notify.ts`), which is
deliberately not bundled into nodes; the Master console's ping delegates to the
same module rather than keeping a second copy. The notification is the *alert*; the
`inbox_acceptance` block is the *audit trail*. It never blocks or undoes the
install, and a headless peer with no `kdeconnect-cli` honestly no-ops the ping
while still leaving the spool row. Real-time push to a remote operator from such a
peer rides Phase 4 telemetry to the Master, not a local ping: Step 70F has the
guard emit `kind=inbox_alert` after an installed RFI answer, gated on the peer's
`telemetry` capability, unsigned and overlay-attributed like every report, with the
item, source, request id, content digest and audit-block hash in its payload. A
failed alert push is logged and ignored — the acceptance, the ledger block and the
local spool already stand, and the alert carries no authority.

## Secrets

A secret is never in the vault. It lives in `$SPARKNET_STATE_DIR/secrets/` at
0700/0600 — gitignored, excluded from bundles — and `00_System/secrets-index.json`
records only that it exists: an id, its kind, which agent holds it, a `ref`
(path or environment-variable *name*), a sha256 fingerprint, scopes and rotation
dates. The schema has no `value` field to abuse, and the tests fail on a
registered value appearing in any tracked file.

## Verifying

```bash
make provenance-verify     # per-note outcomes + ledger chain + approvals
make shims-check           # every legacy name is a symlink to the right target
make keys-check            # no key material tracked; state-dir keys are 0600
make precommit             # keys-check + secret scan + provenance-verify --strict
make contract-test         # both roles still match contracts/
```
