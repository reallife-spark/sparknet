---
title: Redfish BMC inventory — design and offline mock fixture
updated: 2026-10-17
tags: [reference, redfish, bmc, inventory, nvidia, adoption]
source: dsx-ai-factory/nv-redfish @ 7c6a95762cc63cffbca459808b92f546c47aac25 + libredfish @ a51ffb1ffeae15d8f9471224cb799d54007098a2
---

# Redfish BMC inventory with an offline mock

Step 51(d) of `PLAN.md`: adopt Redfish (nv-redfish / libredfish) as the
BMC-style inventory of fabric hosts, behind a mock fixture so it is
offline-testable. Read-only study; no code copied. The live-hardware half is a
`DoD: confirm: user` item.

## The reference

- **`nv-redfish`** (Rust, Apache-2.0) ships a full Redfish crate **plus a
  `bmc-mock` crate**. The mock is the reusable idea: it is a cassette-style
  *expectation engine*, not a canned server. `bmc-mock/src/expect.rs` models an
  `ExpectedRequest` as an enum — `Get`, `PollResult`, `PollPending`,
  `PollEmpty`, `PollStatus`, `PollWait`, `Expand`, `Update`, `Create`,
  `CreateSession`, `Delete`, `Action`, `MultipartUpdate`, `Stream` — each
  keyed by `ODataId`. A test queues the requests it expects; the mock answers
  with the queued JSON body and fails loudly on an unexpected or out-of-order
  request.
- **`libredfish`** (Rust, MIT) is the minimal client: session login, `GET` an
  `ODataId`, follow `Expandable`/`ODataId` links. Enough to walk a service
  root to inventory, no vendor quirks.

The two together separate the *client contract* from the *server fiction*, so
inventory logic is testable with no BMC on the wire.

## Design for the fabric

A `internal/redfish` package in goSpark (Go, so it joins the existing node
surface), in two halves and a fixture:

1. **Client** — `New(baseURL, creds)`, `Get(path) (json.RawMessage, error)`,
   walking `ServiceRoot → ChassisCollection → Chassis → SystemsCollection →
   ComputerSystem → ProcessorSummary/Memory`. Only `GET` and Redfish session
   auth are in scope; no `POST`/actions in the first cut.
2. **Inventory projection** — `Collect(ctx) (Inventory, error)` reduces the
   walk to a host record: `Host{BMC, Manufacturer, Model, Serial,
   PowerState, Chassis[], Systems[{Serial, Model, PowerState, CPUModel,
   CPUCount, MemoryGiB}], Sensors[]}`. The projection is the only place that
   knows Redfish field names, so the model stays testable on its own.
3. **Offline fixture** — a JSON **cassette** keyed by request path, in the
   `bmc-mock` spirit: `{"GET /redfish/v1/": {...}, "GET
   /redfish/v1/Chassis": {...}, …}`. Tests serve the cassette from
   `net/http/httptest` and assert both the decoded `Inventory` and that the
   client requested exactly the expected paths (unexpected path ⇒ fail).

### Fixture shape

```json
{
  "GET /redfish/v1/": {
    "status": 200,
    "body": { "@odata.id": "/redfish/v1/", "Chassis": { "@odata.id": "/redfish/v1/Chassis" } }
  },
  "GET /redfish/v1/Chassis": { "status": 200, "body": { "Members": [ { "@odata.id": "/redfish/v1/Chassis/1" } ] } }
}
```

`status != 200` is how a bad-path / auth-failure case is exercised, matching
`bmc-mock`'s `PollStatus`/`ErrorResponse` variants. A `"repeat": true` flag can
model a polled task later; the first cut does not poll.

### Test tier

- **Offline (always runs):** `httptest` + a repo fixture asserting the decoded
  inventory and the exact request path sequence. This is the half that lands in
  CI.
- **Live (never runs in CI):** point `New` at a real BMC address; assert a
  non-empty `Inventory`. Marked `DoD: confirm: user`.

## Decision lines

- **Adopt the client/projection split and the cassette fixture** — this is the
  mechanism, and it is what makes leg (d) offline-testable per the DoD.
- **First cut is read-only (`GET` only).** Actions, updates and task polling
  are out of scope: goSpark never writes to a BMC, so modelling them would be
  unused surface. Revisit only if a real need (firmware/`Action`) appears.
- **Go, not Rust.** The reference is Rust; the fabric is Go. We adopt the
  *shape* (expectation cassette, minimal client), not the implementation.
- **Live BMC verification is `DoD: confirm: user`** — no BMC is reachable from
  CI, so only the offline tier is asserted here.

## Related

- `nvidia-telemetry-observation-model.md` — nv-telemetry's `sources/redfish`
  feeds the same Reading model; this leg is the inventory side.
- `nvidia-dsx-standard-practice.md` — the inventory this page's verdict feeds.
- `../PLAN.md` — Step 51(d).
