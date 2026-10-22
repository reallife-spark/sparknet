---
title: Registry protocol
type: specification
role: master
status: partially-built
updated: 2026-10-22
---

# Registry protocol

> [!warning] The shape is contracted and checked; the channel that carries it is not built
> A registry's *shape* is stated once, in
> [`../../contracts/registry-schema.json`](../../contracts/registry-schema.json),
> and every document is checked against it. The *distribution channel* — how a
> signed registry reaches a peer — is still **unspecified and unbuilt**
> (build plan Step 6). Peers read a registry an operator placed; nothing pushes
> one. `contracts/identity-schema.json` carries `distribution: UNSPECIFIED` on
> purpose, and that stays until Step 6 decides it.

This document describes the registry format the Master emits and peers consume.
It was written before the CLI existed so the contract could not drift; the CLI
that arrived in Step 3 now emits and verifies it, and Step 2 turned the shape
into a checkable schema.

## The canonical shape

One file states it: [`../../contracts/registry-schema.json`](../../contracts/registry-schema.json).
The Master reaches it through a symlink
([`../manifests/registry.schema.json`](../manifests/registry.schema.json)) —
not a copy, because two copies of a shape would drift and the copies would win
the argument by being read more often. The example document a peer ships is
[`../../peer-node/manifests/node-authorizations.json`](../../peer-node/manifests/node-authorizations.json).

The document:

| Field | Required | Meaning |
|---|---|---|
| `schema_version` | yes | the shape's version. `1.0` — not `1.0.0` |
| `master_public_key_b64` | yes | the operational public key every entry is signed under |
| `description` | no | free text; never read by code |
| `authorizations` | yes | the entries, one per authorized node |

Each entry in `authorizations`:

| Field | Required | Meaning |
|---|---|---|
| `fingerprint` | yes | SHA-256 of the canonical identity bytes; the lookup key |
| `identity` | yes | the node's identity: `node_id`, `role`, `wireguard_public_key_b64`, `overlay_ipv4`, `requested_capabilities` |
| `capabilities` | yes | what the node may do, a subset of the closed vocabulary |
| `overlay_ipv4` | yes | the `/32` the node gets on the overlay |
| `issued_at` | yes | ISO-8601 |
| `expires_at` | yes | ISO-8601; an expired entry grants nothing |
| `revoked` | no | only the Master may set it, and it is inside the signed envelope |
| `signature_b64` | yes | Ed25519 over `{fingerprint, identity, capabilities, overlay_ipv4, issued_at, expires_at, revoked}` |

Two names in that table were the whole problem when this step was reopened:
there is **no `role` field on the document** (the role lives inside each
identity), and the signature field is **`signature_b64`**, not `signature` —
the one implementation, [`../../shared/sparknet-authz.py`](../../shared/sparknet-authz.py),
emits and verifies that name and has never read another.

## Checking a registry

```bash
# the shape and the signatures, against the contract
shared/sparknet-registry-schema.py --registry <path>

# the shape only
shared/sparknet-registry-schema.py --registry <path> --no-verify-signatures
```

Exit codes: `0` conforms, `1` does not, `2` usage or I/O error. The checker
refuses a schema keyword it does not implement rather than ignoring it — a rule
nobody enforces is a rule that quietly stops being true. It is standard library
only on purpose: the fabric's runtime dependency allow-list is `cryptography`
alone, so a validator needing `jsonschema` would pass here and fail on a node.

The Master's own verifier is the same implementation from the other side:

```bash
make -C master-node registry-verify REGISTRY=<path>
```

`master-node/tests/test_registry_schema.py` pins all of it: the shipped
registry conforms, a registry the implementation mints conforms, and the three
ways the draft schema was wrong are refused.

## What is not built

| Piece | State | Step |
|---|---|---|
| the shape | contracted, checked, tested | 2 (this document) |
| signing, verifying, publishing | built — `scripts/sparknet-registry-{sign,verify,publish,revoke}.sh` | 3 |
| the distribution channel | **unspecified**; `registry-listen` is a stub and `contracts/identity-schema.json` says `distribution: UNSPECIFIED` | 6 |
| tamper fails closed *on the peer* | proven on this side only — no test yet drives `shared/sparknet-authz.py` the way `peer-node/services/sparknet-guard-d.py` calls it | 6 |
| revocation propagation | unmeasurable until there is a channel | 6 |

The shipped registry is **empty on purpose**: a committed entry grants its
capabilities to whoever holds the matching identity, so a fresh deployment
carries none. Empty is fail-closed, and the difference between "no peers yet"
and "I cannot load my registry" must stay visible.
