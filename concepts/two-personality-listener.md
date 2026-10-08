---
title: Two-personality listener
updated: 2026-10-08
type: concept
---

# Two-personality listener

One port, two audiences that must never bleed into each other, decided by the
caller's **source address** — not by anything the caller claims. Taken from
NVIDIA PAIR's `docs/architecture.mdx`, where a single proxy port serves
plaintext HTTP on loopback and peer-authenticated TLS from everywhere else,
chosen per connection and refusing plaintext from a non-loopback caller.

The sparknet reading is a **route class**, not a protocol switch.

- **Local personality** — a loopback source (`127.0.0.1`, `::1`). Belongs to
  local tooling and agents dialling the node's own services.
- **Peer personality** — every non-loopback source, i.e. the overlay. Reaches
  only what the fabric is allowed to reach.

A route declared **loopback-only** is refused with HTTP 403 `not-loopback`
**before** the request body is read or its signature verified — a peer cannot
make the server do work on a local-only face, even with a valid signature and
capability. This is implemented in the one shared transport
(`shared/sparknet-http.py`) via `serve(loopback_only_routes=...)`, and testable
on a real socket with a genuine non-loopback source
(`tests/test_http_transport.py`).

The guard's own source check (who may mutate) is the *authority* filter; the
personality gate is the *transport floor* beneath it. Consequence for the share
stanza: `ports.json` 4201–4203 have **no local face** — a service that needs a
local administration route must declare it loopback-only explicitly, never by
default.

Related: `contracts/guard-protocol.md`, `contracts/ports.json`,
`[[pair-architecture-review]]`.

Why it matters: PAIR needed it so a local app could dial the proxy without a
cert and a remote peer could authenticate; sparknet needs it so a peer can hear
the fabric and still keep its local administration off it. The mechanism differs
(signed envelope vs TLS), the refusal-before-work property is identical.