---
title: PAIR cluster architecture review
updated: 2026-10-08
source: https://github.com/NVIDIA/Personal-AI-Router
license: Apache-2.0
type: reference
---

# PAIR cluster architecture review

A dated review of NVIDIA's Personal-AI-Router (PAIR) repository, captured as
the provenance record behind the pages built from it. Reviewed 2026-10-08 at
`refs/remotes/origin/develop` (shallow clone).

## What PAIR is

A LAN-first *inference* router (Apache-2.0): several machines form a cluster
that routes single AI requests to whichever node can serve them. It is Go
services plus an Electron desktop app, discovery by mDNS, pairing by EAP-NOOB,
mTLS pinned to per-node UUIDs, and a local proxy + scheduler that route one
request to one node. There is no WireGuard anywhere; it is a same-LAN tool.

## Files reviewed

| PAIR path | What it establishes |
|---|---|
| `docs/architecture.mdx` | the dual-personality proxy: one port, plaintext loopback-only + peer TLS, 403 for plaintext from a non-loopback caller |
| `services/eap-noob/README.md` | RFC 9140 EAP-NOOB pairing: out-of-band code, KDF, byte-in/byte-out library |
| `services/nvpair-cluster-manager/README.md`, `spec.md` | roster fixpoint, monotonic admission epochs, endorsement chains, removal proofs |
| `services/nvpair-node-scanner/README.md` | probe rhythm, activity-trumps-eviction, "a scan that loses everything is our own fault" |
| `services/nvpair-manual-nodes/README.md` | operator-pinned nodes, re-resolution per probe, probe non-serving ports |
| `SECURITY.md`, `AGENTS.md` | threat posture and repo conventions |

## What translated into sparknet

- **Two personalities, one listener** → the loopback-only route class in the
  shared transport (`shared/sparknet-http.py`, `[[two-personality-listener]]`).
- **Probe + eviction rules** → the peer health contract
  (`contracts/health-protocol.md`, `[[activity-trumps-eviction]]`).
- **Admission epochs + removal proofs** → the re-formation design
  (`[[admission-epoch]]`, `master-node/plans/PAIR_REFORMATION_DESIGN.md`).
- **EAP-NOOB OOB bootstrap** → the optional, time-boxed, stanza-scoped seed
  (`shared/sparknet-oob.py`).

## What deliberately did not translate

- mTLS itself — sparknet's signed-message-over-WireGuard
  (`shared/sparknet-authz.py`) is the right trust path for an authority
  fabric; a TLS handshake adds a second vocabulary for no gain.
- Broker/scheduler/proxy routing and the Electron app — sparknet is an
  authority fabric, not an inference router, and the bundle runtime allow-list
  is `cryptography`-only.
- Plaintext `node-info` telemetry — sparknet's signed `telemetry` capability
  is strictly stronger.

## License note

PAIR is Apache-2.0; this record quotes structure, not code. The mapping pages
under `[[synthesis/]]` and `[[concepts/]]` cite these paths, never a blob.

Related: `[[two-personality-listener]]`, `[[activity-trumps-eviction]]`,
`[[admission-epoch]]`,
`[[what-pair-membership-implies-for-sparknet-reformation]]`,
`contracts/health-protocol.md`, `contracts/consensus-protocol.md`.