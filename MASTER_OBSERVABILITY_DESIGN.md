# Master observability — design (fabric PLAN Step 69A, Phase 4)

status: adopted design; 69B–69H implement it. It adds one contract
(`contracts/telemetry-schema.json`) and re-scopes one port (8090), so it is a
contract change, not a mere proposal.

## The goal, and the line it must not cross

Phase 4 is **Master observability without touching the data path**. Peers talk to
each other directly by design, and the Master is authority-plane only at
`10.100.0.1/32`. So monitoring means **signed evidence pushed to the Master, never
interception**: the Master learns what a peer tells it, attributed to that peer, and
never sits in the middle of the peer↔peer data plane. Two invariants follow, and
they are the same shape as the reflex layer's:

- **Telemetry carries no authority.** It may inform, record, surface and flag; it may
  never grant, revoke, escalate, widen a permission, or approve a guard application.
  The Master *observes* it. A report that could change what a node may do would be an
  authority channel wearing a monitoring costume.
- **No interception, no new write path.** The Master does not proxy or mirror peer
  traffic. Fabric-wide vault maintenance rides the existing `guard-apply` +
  `critical-manifest.json` `protected_paths` mechanism, not a telemetry-driven write.

## The gap Phase 4 closes

Each piece exists in vocabulary or in reference code and none is wired:

| Piece | State today |
|---|---|
| `telemetry` capability | In the closed vocabulary — "Push metrics and node status to the Master" (`capabilities.json`, holder `peer`, `sensitive: false`). Built as 70A (peer pusher) + 70B (8090 intake); the cross-node pair is still `DoD: confirm: user`. |
| `shared/sparknet-liveness.py` | Built as 70D: the reference monitor runs in `sparknet-liveness-monitor.py`, probes the contracted non-serving port 4211 and pushes `kind=liveness`. Live cross-node behaviour is `DoD: confirm: user`. |
| checkpoints | Built as 70E: `sparknet-checkpoint-anchor.py` periodically appends an idempotent signed checkpoint over the ledger head and pushes the full block as `kind=checkpoint_anchor`. Live cross-node anchoring is `DoD: confirm: user`. |
| `flagged` trust level | Built as 70G: the peer's `status` payload carries its trust level and retained share evidence, and the admin console surfaces flagged nodes from the Master's telemetry spool. A flag is held for a human; telemetry never clears it and only a signed registry event moves it. |
| inbox-arrival alert (67B) | Built as 70F: an installed RFI answer still spools locally and pings KDE, and now also emits `kind=inbox_alert` to the Master. A headless peer's arrival therefore reaches a remote operator; live cross-node delivery is `DoD: confirm: user`. |
| Master peer intake | Built as 70B: `sparknet-peer-intake.py` serves the overlay-only 8090 surface (`/api/v1/telemetry` + `/api/v1/rfi-request`), so 8090 is no longer spec-only. 4203 remains spec-only; the Master still *dials* peers on 9090 for the pull path. |

There is already a **pull** path, and it is not this: the Master admin console's
`feed()` sends `list_events` admin requests (over `admin-supervise`, Step 29) to each
peer's bridge `/admin/*` route and reads that peer's 0600 auth-event spool. Pull is
Master-initiated, on-demand, `admin-supervise`-gated, and limited to auth events.
Phase 4 adds the **push** complement: peer-initiated, continuous, `telemetry`-gated,
carrying status/metrics/liveness/checkpoint-anchors/inbox-alerts. They are
complementary, not redundant — and the capability gate differs, which is the point:
`admin-supervise` is Master-held, `telemetry` is peer-held.

## The architecture

**One Master peer-intake listener, many routes.** The Master needs a peer-facing
socket; 8090 is `spec-only` and *superseded in direction*, and Master Step 7 was left
open precisely to decide whether it "survives for ACL pushes, is re-scoped, or is
retired." **Re-scope 8090 as the Master's peer→Master intake listener**, overlay-only,
source-gated to registered non-revoked peer overlay addresses. It carries peer→Master
message *families* as routes, not one port per family — exactly as the peer's guard
9090 carries three routes (`critical-file/patch`, `registry`, `rfi`). Phase 4 adds
`POST /api/v1/telemetry`; **Step 68C's RFI request listener becomes another route on
the same 8090**, so the two steps build one surface rather than two. This resolves
Master Step 7 productively instead of leaving 8090 a dead spec.

**Attribution by the authenticated overlay** (Step 68A's Option B, generalised). A
peer→Master report is *not* signed with a node key — nothing binds a peer fingerprint
to a node signing public key, so such a signature would be unverifiable theatre. The
Master derives the sender's fingerprint from the WireGuard-authenticated source
address via its own registry (`overlay_ipv4 → fingerprint`) and refuses a report whose
`peer_fingerprint` field disagrees. **On the overlay the tunnel is the identity.**
`nonce` + `expires_at` give the replay/freshness guard a signature's freshness fields
would. (The upgrade path — attesting `node_pubkey_b64` in the signed envelope, a
two-repo change riding the re-sign already pending from Step 66 — is in
`RFI_REQUEST_DESIGN.md` and applies here identically if non-repudiation is ever
required.)

**The telemetry evidence envelope** (`contracts/telemetry-schema.json`,
`shared/sparknet-authz.py::build_telemetry_report` / `verify_telemetry_report`): a
`kind`-tagged body — `status`, `metrics`, `liveness`, `checkpoint_anchor`,
`inbox_alert` — carrying `peer_fingerprint`, an opaque `payload` object, `issued_at`,
`expires_at`, `nonce`. `verify_telemetry_report` is a **validator + fingerprint
match**, not a signature check: exact field set, `kind` in the closed vocabulary,
`payload` an object, `peer_fingerprint == expected_fingerprint`, expiry, future-issue
skew, nonce replay. It never raises. `kind` routes the report to what records it; the
per-kind payload's meaning belongs to the consumer sub-step, not the envelope.

**The Master records telemetry as evidence, and acts on nothing.** A received report
is appended to a telemetry spool the admin console's feed can surface alongside auth
events. `flagged` nodes' evidence is what 70G makes actionable — the peer reads its
own persisted share records through `sparknet-share-regime.py::trust_summary`, puts
the level and retained `flagged` markers in its `status` payload, and the console
surfaces them for a human. Nothing auto-remediates: only the Master moves a trust
level, and only as a signed registry event. The inbox-arrival alert (69H) is the `inbox_alert` kind:
67B's local spool row also rides telemetry to the Master, whose admin surface a remote
operator actually watches — closing Phase 3's third deferred leg.

## Sub-steps

- **69A** (this doc) — decide the architecture; open `contracts/telemetry-schema.json`;
  re-scope 8090 in the design (wired in 69C).
- **69B** — the telemetry evidence envelope (`build_telemetry_report` /
  `verify_telemetry_report`, overlay-attributed), pinned to the contract. No listener
  yet, exactly as 67C built the answer envelope before 67D's route.
- **69C** — the Master peer-intake listener: **re-scope 8090** (overlay-only,
  source-gated to registered non-revoked peers, fingerprint from the WireGuard
  source), serving `POST /api/v1/telemetry`; reconcile `ports.json` + Master Step 7.
  **This is the surface 68C's RFI request route then joins.**
- **69D** — the peer telemetry pusher: a service/unit that periodically builds a
  `status`/`metrics` report and pushes it, gated on the peer's `telemetry` capability
  (a peer without it does not push).
- **69E** (built as 70D) — deploy `sparknet-liveness.py`: a service running `ContinuousMonitor`
  against registry-derived peers, a non-serving probe port (contracted in
  `ports.json`), and the peer's liveness `claim()` riding telemetry as kind
  `liveness`. Live cross-node behaviour stays `DoD: confirm: user` (no overlay here).
- **69F** (built as 70E) — anchor checkpoint Merkle roots: a periodic service
  calling `provenance.build_checkpoint_data` + appending the checkpoint block, and
  pushing the full signed block as kind `checkpoint_anchor` so the Master holds a
  tamper-evident head. Live cross-node anchoring stays `DoD: confirm: user`.
- **69G** (built as 70G) — make `flagged` actionable: the peer's `status` payload
  carries its trust summary, and the admin console surfaces flagged nodes and their
  retained evidence from the Master's telemetry spool; a flag is held for a human,
  never auto-remediated (only the Master moves a trust level, by signed registry event).
- **69H** (built as 70F) — inbox-arrival alert to a remote operator: 67B's arrival
  also emits an `inbox_alert` telemetry report, so a headless peer's arrival reaches
  the Master's admin surface. Closes Phase 3's third deferred leg.

## What Phase 4 deliberately does not do

- **No interception** of the peer↔peer data plane, and no Master proxy/mirror of it.
- **No authority** on the telemetry path: it cannot grant, revoke, escalate, widen, or
  approve. Any future leg that would let observability touch an authority path is a
  contract change and belongs in `contracts/` first, with its own step.
- **No new write path** for fabric-wide vault maintenance: that rides `guard-apply` +
  `protected_paths`, as the phase's own scope states.
