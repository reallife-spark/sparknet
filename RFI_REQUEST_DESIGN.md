# RFI request channel — design (fabric PLAN Step 68A)

status: adopted design; 68B–68D implement it. Changes `contracts/rfi-schema.json`'s
`request` block (attribution), so it is a contract change, not a mere proposal.

## The problem

Step 67 built the RFI **answer** direction: the Master signs an answer and pushes
it to `POST /api/v1/rfi` on the peer's guard, which installs it into `01_Inbox/`.
The **request** direction — a peer asks, the Master answers — was deferred, and
`rfi-schema.json` `implementation_state.request_channel` records exactly why:

> A request is signed with the peer's own node key, but nothing in the fabric
> binds a peer *fingerprint* to a node *signing* public key, so the Master cannot
> attribute a request signature and `verify_rfi_request` does not exist.

Concretely, from `contracts/identity-schema.json` and the tree:

- `identity_fields` are `node_id, role, wireguard_public_key_b64, overlay_ipv4,
  requested_capabilities`. The WireGuard key is **Curve25519** and cannot verify an
  **Ed25519** signature.
- A peer *does* hold an Ed25519 node key (`$SPARKNET_STATE_DIR/keys/
  ed25519-node.key.b64` — the countersignature half of a dual-signed ledger
  block), but its **public half appears in neither the identity, the signed
  registry entry, nor the cluster trust root**. The Master has never seen it.
- The Master has **no implemented peer-facing listener**. It *dials* peers on 9090;
  8090 (instant-push) and 4203 (share-ratification) are `spec-only`.

So a node-key-signed request is **unverifiable** today: there is no attested key to
check it against, and no socket to receive it on.

## The two ways out

**Option C — attest the node key in the signed envelope.** Add `node_pubkey_b64` to
`signed_envelope_fields` (as `department` was added in Step 66A), so the Master's
registry signature attests `fingerprint → node_pubkey`, and `verify_rfi_request`
checks the request against the registry's copy. This matches the contract's stated
rationale verbatim.

Rejected for now, on blast radius, not merit:

- The signed envelope is implemented **twice** — Python here and **Go in goSpark** —
  and `tests/test_registry_crossverify.py` is the only proof the two agree. Adding a
  field is a **two-repo** change (66A had to be, for `department`).
- `identity-schema.json`'s own `signed_envelope_note`: adding a field "changes the
  bytes the Master signs, which stops every existing entry signature verifying —
  adopt it by re-signing and re-publishing at a higher sequence." That re-attestation
  is **already pending** from 66A (`MEMORY.md`: a live node must re-sign; not closable
  from this repo). Folding a second field in compounds a migration that has not yet
  been executed on the live pair.
- It also needs a registration-flow change: the Master must *obtain* each peer's node
  pubkey to attest it (out of band, like the WireGuard key exchange).

Option C stays the **upgrade path** if node-key *non-repudiation* is ever required.
It changes the attribution anchor, not the wire shape much, so adopting it later is
additive.

**Option B — attribute by the authenticated overlay (chosen).** The request rides the
WireGuard overlay, which *already* authenticates every peer: the Master's `wg0`
carries one `[Peer]` stanza per authorized node, keyed by `wireguard_public_key_b64`
and `AllowedIPs` = that node's overlay `/32`. A packet the Master receives on the
overlay from `10.100.0.x` is therefore from the peer holding that stanza's private
key — and the Master's registry maps `overlay_ipv4 → fingerprint`. So the Master can
attribute a request to a registered, non-revoked fingerprint **from the tunnel it
arrived on**, with no node-key signature and no schema change.

Chosen because it is **single-repo, reversible, and needs no migration**: nothing
signed changes shape, so no live registry is invalidated and goSpark is untouched.

## Option B, precisely

**Attribution is the tunnel, not a signature.** The Master:

1. receives the request on an **overlay-only** listener, source-gated to the overlay
   addresses of registered, non-revoked peers (the same gate the answer route uses,
   mirrored);
2. derives the sender's fingerprint from the **overlay source address** via its own
   registry (`overlay_ipv4 → fingerprint`), refusing a source it does not recognise
   or a revoked one;
3. refuses any request whose `peer_fingerprint` **field** disagrees with the
   overlay-derived fingerprint — a peer may not ask as another peer;
4. validates the body (exact fields, `expires_at` in window, `nonce` unseen);
5. only then gathers an answer and signs it (Step 67D's `sign_rfi_answer`).

**The request is not signed.** There is no key the Master can verify it against, and
a signature it cannot check is theatre. The request body carries `request_id,
peer_fingerprint, question, scope, issued_at, expires_at, nonce` — the `nonce` and
`expires_at` give replay protection, which is what a signed envelope's freshness
fields are for; attribution comes from the tunnel. `verify_rfi_request` is therefore
a **validator + fingerprint match**, not a signature check: it takes the
overlay-derived `expected_fingerprint` and returns `(ok, reason)` after checking the
field set, the fingerprint match, expiry and the nonce.

This is honest about a real property: **on the overlay, the tunnel is the identity.**
The fabric signs Master→peer messages (approvals, registry, answers) because those
cross a boundary where the receiver must check authority it cannot otherwise trust;
a peer→Master request arrives on a tunnel the Master itself terminates and
authenticated, so the source *is* the attestation.

**Where the listener lives (68C).** The Master has no implemented peer-facing
listener, so 68C must place one. The natural home is **8090**, which
`contracts/ports.json` marks `spec-only` and *superseded in direction* — Master Step
7 was left open precisely to decide whether 8090 "survives for ACL pushes, is
re-scoped, or is retired." Re-scoping it as the Master's peer→Master **request**
listener (RFI requests now; ACL pushes and share-ratification could ride it later)
resolves that open question productively rather than adding a fresh transport edge.
68C records the decision in `ports.json` and reconciles Master Step 7. This design
does **not** unilaterally re-scope 8090; it recommends it and leaves the port wiring
to 68C.

**Composer rewiring (68D).** `sparknet-rfi-answer.sh` currently takes
`--request-id`/`--peer` as operator inputs (67D, because no verified request
existed). 68D adds a `--request <artifact>` path: the composer verifies the request
(the overlay-derived fingerprint comes from the listener that received it), reads
`question`/`scope`/`request_id`/`peer_fingerprint` from it, and answers — closing the
loop. The `--request-id`/`--peer` inputs stay for the offline/operator path, exactly
as the answer channel keeps an operator-carried install beside the live listener.

## Scope discipline (what this channel may not become)

- `scope` is an allow-list of vault categories the answer may draw on. The Master
  **refuses** a request whose scope reaches material the peer is not granted (per its
  registry entry / department). Scope narrows; it never widens. The Master is not a
  general query oracle for a peer — it answers within what the peer is already
  allowed to know.
- The request channel carries **no authority**. It cannot grant, revoke, escalate or
  widen a permission; it asks for information and the Master answers within the
  peer's existing ceiling. This is the same invariant the reflex layer holds.
- Gathering the answer is **upstream and out of scope** here, as in 67D: the fabric's
  semantic store (4223 `vector-embed`) is `spec-only`, so a composer gathers from
  whatever local source it is pointed at. This design builds the *channel*, not a RAG
  backend.

## Sub-steps

- **68A** (this doc) — decide attribution, rewrite `rfi-schema.json`'s `request`
  block to Option B, update `implementation_state.request_channel`.
- **68B** — `build_rfi_request` / `verify_rfi_request` in `shared/sparknet-authz.py`
  (validator + overlay-fingerprint match + nonce/expiry), pinned to the contract like
  every other envelope. No signature, so no `sign_rfi_request`.
- **68C** — the Master-side request listener on the port 68C decides (recommended:
  re-scoped 8090), source-gated to registered non-revoked peers, deriving the
  fingerprint from the overlay source; `ports.json` + Master Step 7 reconciled.
- **68D** — `sparknet-rfi-answer.sh --request <artifact>`: verify, then gather/sign/
  deliver, closing the peer→Master→peer loop.
