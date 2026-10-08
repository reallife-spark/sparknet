# Guard protocol — the contract between Master and peer

Both roles implement this conversation. The peer side exists
(`peer-node/services/sparknet-guard-d.py`); the Master side that *produces*
these payloads does not exist yet and is specced in
`master-node/plans/MASTER_BUILD_PLAN.md`.

The normative machine-readable policy is `contracts/capabilities.json` and
`contracts/identity-schema.json`. This page is the narrative contract.

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

A payload the Master signs to authorise one mutation:

| Field | Purpose |
|---|---|
| `fingerprint` | SHA-256 of the peer's canonical identity (`contracts/identity-schema.json`) |
| `capabilities` | must include `guard-apply`, or the guard refuses |
| `target_path` | must appear in the peer's `critical-manifest.json` `protected_paths` |
| `content` | the new file content |
| `nonce` | single-use value; replay refused |
| `request_id` | correlates plan → permission → execute |
| `issued_at` / `expires_at` | validity window |

`content` is **inside** the signed message (`content_in_signature: true`).
Signing only a request id would let anyone replay it against different content.

## What the guard checks, in order

Verification is ordered so that the cheapest disqualifying check happens first,
and every failure is fail-closed:

1. **Source address** — loopback, or the Master's overlay IP
   (`contracts/overlay.json → master_anchor_ipv4`). The guard binds its *own*
   overlay address, so a legitimate Master request arrives from `10.100.0.1`.
   The node's own overlay address and neighbouring clients are rejected.
2. **Master signature** — Ed25519 over the canonical payload.
3. **Not revoked** — checked *before* signature validity, so a tampered
   registry fails closed: clearing `revoked` by hand breaks the signature.
4. **Not expired / not replayed** — nonce unused, within the TTL.
5. **`guard-apply` capability** — present in the signed envelope.
6. **Target is protected** — the path is in this node's manifest. An unprotected
   path is refused even with a perfect signature.
7. **`euid 0`** — the apply path requires root.
8. **`--apply-enabled`** — off by default in the shipped unit. Arming the guard
   to mutate is an explicit operator decision, not a default.

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

## Master side (not yet built)

The Master must be able to:

- render this payload for a specific peer, signed with its private key
- POST it to that peer's `10.100.0.x:9090`
- track issued nonces so it never signs the same one twice
- revoke: sign `revoked: true` and redistribute the registry

Until that exists, `guard-apply` cannot be granted to any peer in practice. The
capability is defined and enforced, but nothing can issue it.