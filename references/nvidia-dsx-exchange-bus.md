---
title: dsx-exchange bus contract — AsyncAPI + NATS auth-callout on the fabric bus
updated: 2026-10-17
tags: [reference, bus, nats, asyncapi, auth, nvidia, adoption]
source: dsx-ai-factory/dsx-exchange @ 484162a68b380f403458459ef9cad5a16758f3ff (Apache-2.0)
---

# dsx-exchange bus contract → the fabric bus

Step 51(e) of `PLAN.md`: adopt dsx-exchange's AsyncAPI contract *style* for the
fabric bus, and evaluate its NATS **auth-callout** as a model for gating
publish/subscribe by signed identity. Read-only study; no code copied.

## The reference

`dsx-exchange` is an event-bus product built on NATS, with two parts worth
studying.

**AsyncAPI 3.1.0 specs, one per domain** (`schemas/asyncapi/{bms,weather,
nico,nke,dsx-flex,launch-layer,mission-control,scheduler-events}/*.yaml`). Each
is a machine-readable channel catalogue, not prose. The `bms` spec shows the
house pattern concretely:

- A **topic grammar** stated up front, e.g.
  `BMS/v1/{PUB|integration}/{Value|Metadata}/{objectType}/{pointType}/{tagPath}`,
  with wildcard semantics (`+` = one level, `#` = subtree).
- A **Value / Metadata split**: Metadata (units, identifiers, relationships)
  is retained and republished on a heartbeat; Value carries the live reading
  (`value`, `timestamp`, `quality`) and is published on change. Consumers are
  told to *always* read Metadata before interpreting a Value.
- The same `cloud-events-example.yaml` shows the envelope: a CloudEvents
  (`specversion/type/source/id/time/datacontenttype`) carried over MQTT.

**NATS auth-callout** (`auth-callout/`) is a small Go service that answers
NATS's authorization question. The flow, read from `src/internal/service/
service.go`, is:

- NATS asks the service (`jwt.AuthorizationRequest`) on behalf of a connecting
  user; `handleAuthRequest` decodes the request, increments
  `auth_requests_total` / observes `auth_request_duration_seconds`, and builds
  a `jwt.UserClaims` for the user's NKey.
- Permissions are attached from a hot-reloaded `permissions.json`
  (`config/permissions.go`) — `Permissions jwt.Permissions` with an account and
  allow/deny lists — and the signed User JWT is returned. The service also
  supports JWKS/OAuth2, mTLS and NKey authenticators.

The load-bearing idea: **the bus does not trust a connection; it asks a signed
authority who the connection is and what it may touch, per subject.**

## Mapping onto the fabric bus

goSpark's `internal/bus` is deliberately minimal — `Bus{Publish, Subscribe,
Request, Close}` over NATS/JetStream, with a `Memory` bus for tests, and a
canonical subject tree `Subject(root, kind, node)` → `sparknet.<kind>.<node>`
for kinds `register|health|task|result|registry|job|decision|delta`.

| dsx-exchange | goSpark today | Gap |
|---|---|---|
| AsyncAPI channel catalogue per domain | `Subject()` + `Kind*` constants in code | **no machine-readable channel/schema doc** |
| Topic grammar with wildcards documented | `sparknet.<kind>.<node>` implied | grammar not written down |
| Value / Metadata split | none (each message is self-describing) | not needed at this scale |
| CloudEvents envelope | plain payloads | optional |
| NATS auth-callout + permissions | bus auth delegated to NATS/JetStream config | **no signed-identity gate at the bus** |

## Decision lines

- **Adopt a written subject/schema contract** for the fabric bus: a single
  doc (or an AsyncAPI 3.1.0 file alongside `contracts/`) that names every
  kind, its subject pattern, and its payload schema. "The kernel of the
  contract is the channel catalogue, kept next to the code that publishes" —
  the reference's best idea, at a size our eight kinds justify. Landing it is a
  **follow-up**; this leg records the decision and the inventory verdict.
- **Evaluate, and defer, the auth-callout.** The fabric already draws authority
  from key possession (`contracts/guard-protocol.md`,
  `contracts/identity-schema.json`), but the *bus* itself is currently gated by
  NATS config rather than by a signed callout. A callout that issues NATS
  permissions from a peer's signed identity would close that asymmetry — and it
  is exactly the pattern `dsx-exchange` proves out. **Deferred**: it is a
  cross-role contract change (peer + master + `contracts/` atomically, per the
  charter), so it needs its own PLAN step, not a footnote in the adoption
  sweep. Recorded here as the concrete design to pick up.
- **Do not adopt Value/Metadata or CloudEvents yet.** Our subjects are
  low-cardinality control messages, not high-rate telemetry; the split and the
  envelope buy nothing until a telemetry channel exists on the bus. Revisit
  alongside any move to stream telemetry over NATS.

## Related

- `nvidia-redfish-bmc-inventory.md` — the inventory side of the same fabric.
- `../contracts/guard-protocol.md` — where fabric authority already lives.
- `../contracts/README.md` — the contract SSOT the bus contract would join.
- `../PLAN.md` — Step 51(e).
