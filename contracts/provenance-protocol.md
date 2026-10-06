# Provenance protocol — who wrote this, for whom, and who approved it

This is the narrative contract for accountability inside a role vault. The
normative machine-readable form is `contracts/tracking-schema.json`
(`sparknet-tracking/1`); this page says why the bytes look the way they do and
what a reader may conclude from them.

What is built and what is not: the layout, the tracking block, the user record,
the ledger records, the secret index and the local signing tooling are built as
of this step. **The transport that would deliver inbox items — the email service
and node-to-node delivery — is specified, not built.** Every rule below that
describes who may act on an arriving item is a policy awaiting a listener, and
`contracts/ports.json` is what says so.

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

The signature covers three hashes, not the raw text: the body hash, the
canonical hash of the frontmatter *outside* `tracking` (the compiler's field
zone), and the canonical tracking hash with `signature` stripped — recorded in
the envelope as `signed_body_sha256`, `signed_meta_sha256` and
`signed_tracking_sha256`. The envelope also carries `signed_meta`, the metadata
mapping itself, so a verifier can name *which* keys moved rather than merely
observe that a hash differs. Recording what was signed is what makes "edited
since signing" a *detectable* state rather than a guess.

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
chain. The block-level `signature` restates the node's countersignature where
the schema requires a signature; `hash` binds the whole block.

Peer-written events are `approval`, `report`, `share` and `inbox_acceptance`.
Master events are the disjoint set in `tracking-schema.json`; a peer writing one
is a contract break, because only the Master can observe what those events
describe.

## Inbox dispatch — a policy, not a pipeline

`01_Inbox` is read-only for agents until an item is accepted. Acceptance is
recorded as an `inbox_acceptance` block; if the item is untrusted, a reviewer
agent sanitizes it before anything downstream reads it.

- source `master-node` → may be executed on notice (the Master is the signing role);
- source `peer-node` → executes only on acceptance, after review and sanitize;
- source `email` → the sender must be on the authorized list in
  `00_System/user.md`, then treated as peer-origin.

Reviewer agents: `agents/vault-curator` on a peer, `.opencode/agents/evidence-reviewer`
on the Master. The transport that would deliver these items does not exist yet.

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
