# Guard protocol — the contract between Master and peer

Both roles implement this conversation. The peer side exists
(`peer-node/services/sparknet-guard-d.py`); the Master side that *produces*
these payloads was built in master-node build-plan Step 5
(`master-node/scripts/sparknet-approval-issue.sh`,
`sparknet-approval-sign-socket.sh`, `sparknet-approval-deliver.sh`).

The normative machine-readable policy is `contracts/capabilities.json` and
`contracts/identity-schema.json`. The approval envelope itself is stated
normatively in `contracts/guard-approval.json`; this page is the narrative
contract.

## The asymmetry is a role state, not a structure

This page previously stated, as a timeless fact, that a peer can **verify** an
approval but never **produce** one. That is no longer structurally true, and
keeping the sentence would mislead exactly the reader it was meant to protect.

A peer today contains the signing code. What stops a peer from signing is not its
implementation — it never was, and under the election model it certainly is not. A
peer lacks the **operational key**, and the operational key exists only inside a
cluster trust root that every member co-signed. A node outside the root, or a
node the root does not name as master, has nothing to sign with.

So the authority asymmetry is preserved but relocated: from *"the peer cannot
sign"* to *"only a node named by a valid cluster trust root may use the operational
key."* That is a weaker guarantee than the old sentence implied, because it
depends on state rather than on code, and it is stated as one.

Who may hold that key is decided by unanimous agreement of the members (2 of 2 in a
pair, 3 of 3 in the full cluster), specified in
`contracts/consensus-protocol.md` and carried as `cluster_trust_root` in
`contracts/identity-schema.json`.

The property that actually matters is unchanged: a node cannot authorise a change
to itself. It cannot grant itself `guard-apply`, install itself as master, or
extend its own overlay address, because each of those requires a signature under a
key it does not hold, from a root it did not unilaterally agree to.


## Request lifecycle

```
peer agent wants to change a protected file
        │
        ▼
PLAN        the agent drafts a read-only proposal; no mutation occurs
        │
        ▼
PERMISSION  the request is offered to the operator / Master for approval
        │
        ▼
EXECUTE     only a signed payload with a live capability reaches the guard
```

The guard never learns about an unapproved request. It is not a policy engine
that can be talked into approving something; it either receives a valid
signature or it refuses.

## Approval payload

A payload the Master signs to authorise one mutation. The normative field list
is `contracts/guard-approval.json`; the rule that turns it into the bytes the
signature covers lives once, in `shared/sparknet-authz.py`
(`guard_approval_message`), which both the Master and the peer import.

| Field | Purpose |
|---|---|
| `peer_fingerprint` | SHA-256 of the peer's canonical identity (`contracts/identity-schema.json`) — the peer the approval is addressed to |
| `file_path` | must appear in the peer's `critical-manifest.json` `protected_paths` |
| `content_b64` | the new file content, base64, **inside** the signed message |
| `content_sha256` | SHA-256 of the new content; the peer recomputes it and refuses a mismatch |
| `nonce` | single-use value; replay refused |
| `request_id` | correlates plan → permission → execute |
| `issued_at` / `expires_at` | validity window |

`content_b64` is **inside** the signed message (`content_in_signature: true`).
Signing only a request id would let anyone replay it against different content.
For the same reason the envelope carries **no capabilities**: the peer reads
`guard-apply` from its own signed registry entry, never from the payload. An
approval that could grant the authority it is checked against would be a
privilege-escalation channel wearing a signature.

The envelope is *exactly* these eight fields. A payload with a missing field is
refused, and so is one with an extra field: the signature covers exactly this
projection, so anything outside it is unsigned.

### One rule, two implementations of it — no longer

The rule used to exist three times: the signer listed
`peer_fingerprint, guard_protocol_version, target_path, action, expires_at`, the
guard verified `file_path, content_b64, content_sha256, issued_at, expires_at,
nonce, request_id`, and the contract above named a third set. Every side was
internally consistent and the conversation still could not happen: no approval
the Master could produce was one a peer would accept. The rule now lives in
`shared/sparknet-authz.py` and is imported by both.

### The peer binding

`peer_fingerprint` is not decoration. Without it a signature says only *that*
the Master signed something, not that the Master meant *this* node — and an
approval minted for one peer would be applied by another that protects the same
path. The peer refuses an approval addressed to anyone else.

## What the guard checks, in order

Verification is ordered so that the cheapest disqualifying check happens first,
and every failure is fail-closed:

1. **Source address** — loopback, or the Master's overlay IP
   (`contracts/overlay.json → master_anchor_ipv4`). The guard binds its *own*
   overlay address, so a legitimate Master request arrives from `10.100.0.1`.
   The node's own overlay address and neighbouring clients are rejected.
2. **Master signature** — Ed25519 over the canonical payload.
3. **Addressed to this peer** — the `peer_fingerprint` in the envelope is this
   node's own fingerprint. Checked right after the signature, before anything
   is spent on the request.
4. **Not expired / not replayed** — nonce unused, within the TTL.
5. **Content integrity** — `content_b64` decodes and hashes to
   `content_sha256`.
6. **Target is protected** — the path is in this node's manifest. An unprotected
   path is refused even with a perfect signature.
7. **`guard-apply` capability** — granted in this node's own signed registry
   entry, not asserted by the payload. The entry's own signature is verified
   first, and it covers `revoked`, so a tampered registry fails closed: clearing
   `revoked` by hand breaks the signature.
8. **`euid 0`** — the apply path requires root.
9. **`--apply-enabled`** — off by default in the shipped unit. Arming the guard
   to mutate is an explicit operator decision, not a default.

The canonical bytes are a function of the parsed fields, so the body is parsed
before the signature is checked. Parsing is not a trust decision: no value is
read before the signature over the canonical projection has verified.

## Two personalities, one listener

The guard and every future overlay service sit on the shared transport
(`shared/sparknet-http.py`), which formalises PAIR's dual-personality pattern:
one listener chooses the caller's class by **source address**, not by anything
the caller claims.

- **Local personality** — a loopback source (`127.0.0.1`, `::1`).
- **Peer personality** — any non-loopback source, i.e. the overlay.

A route may be declared **loopback-only** (`serve(loopback_only_routes=...)`).
A caller from the peer personality is then refused **HTTP 403
`not-loopback`** *before* the request body is read or the signature verified —
a peer cannot make the server do work on a local-only face, even with a valid
signature and capability. The guard's own source check (step 1 above) remains
the authority filter on who may mutate; the personality gate is the transport
floor beneath it.

Consequence for the share stanza (4201–4203): the peer share-stanza ports have
**no local face**. They are peer-personality only, and a service that needs a
local administration route must declare it explicitly as loopback-only rather
than defaulting it on.

## Apply sequence

When all of the above pass:

1. `chattr -i` the target (lift the immutable bit)
2. write atomically — temp file in the same directory, then rename
3. restore ownership and mode
4. `chattr +i` re-pin
5. append to the audit ledger, hash-chained to its predecessor

If the write fails midway the ledger records the failure; a half-applied
protected file is the worst state and must be visible in the audit trail.

## Standalone degradation

With no overlay the guard **refuses to bind** and refuses to apply. The vault
still works — an unanchored node loses the ability to mutate protected files,
not the ability to read or serve its own knowledge.

That asymmetry is deliberate: a node that has lost its Master has lost its
authority, and the correct response is to keep it useful but inert, not to let
it carry on with stale permissions.

## Master side

The Master mints, signs and delivers the payload:

- `make approval-issue TARGET=<path> CONTENT=<file> PEER_FINGERPRINT=<fp>`
  renders the envelope for one peer and signs it with the operational key. The
  offline path loads the key into the calling process; the production path is
  `make approval-sign-socket APPROVAL=<file>`, which hands the envelope to the
  isolated signer so the key never enters a calling process and every issued
  approval lands in the Master's hash-chained ledger.
- `make approval-deliver FINGERPRINT=<fp> APPROVAL=<file>` POSTs it to that
  peer's `10.100.0.x:9090`, on the route
  `POST /api/v1/critical-file/patch`, with `{"payload": <base64 canonical
  bytes>, "signature": <base64>}`. The peer's address comes from the signed
  registry; the fingerprint names the peer, the registry entry names its
  address.
- The Master tracks the nonces it has issued
  (`$SPARKNET_STATE_DIR/approval_nonces.json`) and refuses to issue one twice.
- Revocation stays with the registry: the Master signs `revoked: true` and
  redistributes it (build-plan Step 6 is the distribution channel).

`guard-apply` is therefore grantable in practice — the capability is defined,
enforced, and now exercisable end to end, and the integration test proves the
two sides agree rather than assuming it.
