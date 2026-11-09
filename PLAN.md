---
title: sparknet Plan
updated: 2026-11-09
current: 91
---

# sparknet — Active Plan

> Single source of truth for fabric work. The `current:` cursor names the step
> being worked. Write this file back **immediately** on every advance and append
> the matching transition line to `log.md`. Completed steps 1–74 are in
> `_archives/PLAN_FULL_2026-10-30.md`; their evidence is in `log.md` and
> `sessions/`. Peer work stays in `peer-node/PLAN.md`; Master work in
> `master-node/PLAN.md`.

## Status Legend

- `[ ]` not started / in progress
- `[x]` complete — DoD verified
- **DoD** — the check that proves the step is done; `DoD: confirm: user` when a
  human must confirm
- `current: N` — step being worked; `current: done` — terminal

## Closed steps

| Range | Scope | Evidence |
|---|---|---|
| 1–14 | split, vendoring, bundle, contracts, agents, truth audit, election | archived plan + `log.md` |
| 15–41 | hardening, three-node rehearsal, cluster inference, proposals, release surface | archived plan + `log.md` |
| 42–63 | adoption, role swap, AGX image, overlay, consistency, cluster jobs, vector substrate | archived plan + `log.md` |
| 64–74 | reflex, naming, departments, intake/RFI, observability, roadmap, materials, skills, SBOM | archived plan + `log.md` |
| 75–89 | user-node context, governance, share/model plane, role inversion, Step 89 | `_archives/PLAN_FULL_2026-11-08.md` |


## Step 90 — Phase 8 file-level remediation

- [x] **Step 90** — Review every one of the 416 files in the Phase 8
  inventory, patch confirmed defects and preserve behavior.
  - [x] **90A — Inventory and governance.** Archive Steps 75–89, add a
    machine-readable 416-row inventory and `make phase8-check`; no file may be
    left `pending` at closure.
  - [x] **90B — Shared core.** Authz, consensus, election, provenance, install,
    memory gateway, HTTP/YAML/loader and associated tests.
  - [x] **90C — Master.** Signer, ledger, intake, distill, admin/vector/uplift,
    scheduler, RFI/share and scripts/tests.
  - [x] **90D — Peer.** Guard, bridge, OpenCode engine, registry client,
    provisioner, share, telemetry/RFI and WireGuard scripts/tests.
  - [x] **90E — goSpark.** Authz, gateway, kvtransfer, transport, server, memory,
    registryfile, commands, proto and tests; separate repository commits.
  - [x] **90F — Scripts, goagx, webui.** Shell help/syntax, bundle/model/vector
    tools, image surface and web UI helpers.
  - [x] **90G — Tests.** Verify every test can fail for its claimed bug; add a
    regression for every fixed defect; gate live-only checks.
  - [x] **90H — Closure.** No `pending` or `needs-decision`; update the register;
    run all gates; publish goagx; set `current: done`.
  - **DoD**: all 416 rows have a verdict and evidence; every `fixed` row names a
    regression test or an explicit no-test reason; `make phase8-closure-check`,
    `make test-all`, `make ci`, both bundle verifications, `make -C gospark ci`,
    `make drift-check` and the role suites are green.
  - **Status 2026-11-08 — CLOSED.** All 416 rows are terminal: 54 fixed,
    186 reviewed-clean and 176 test-verified. `make phase8-closure-check`,
    `make test-all`, `make ci`, signed bundle verification, signed goagx
    verification and `make drift-check` are green.

## Step 91 — Understand-Anything + Matt Pocock integration

- [ ] **Step 91** — Port Understand-Anything to Python/Go, add its skills and
  console surface, and integrate the Matt Pocock engineering skills with a
  local issue tracker whose work items reach the Master over a signed route.
  - [x] **91A — Contracts and provenance.** Add `contracts/understand-schema.json`
    and `contracts/issue-schema.json`; add the peer-held `issue-report`
    capability; add the knowledge-flow rows; name the `/api/v1/issues` route on
    8090; record `.scratch/issues` as local work items; update the contract
    manifest and README.
  - [x] **91B — Python core.** Native-first extractors (`ast`, `go/parser`,
    shell, markdown, JSON/YAML/TOML) plus the tree-sitter fallback; graph
    normalize/merge/validate; knowledge, domain, figma and incremental
    analyzers; the JSON stdin/stdout parser seam. Tests and golden graphs.
  - [x] **91C — Go service.** `internal/understand` walk/ignore/fingerprint/
    batch/store/query/diff/export and `cmd/sparknet-understand`; no cgo, no
    duplicate parser; ADR 0005. Tests.
  - [x] **91D — Skills and plugin.** Vendor the nine `/understand*` skills,
    rewrite helpers to call the Go/Python CLI, and port the auto-update and
    stale-check hooks to `.opencode/plugin/understand-anything.ts`.
  - [x] **91E — Console.** Add the Understand tab to `webui/console` as
    server-rendered HTML/CSS with a small vanilla-JS graph module; add
    `GET /api/understand` and `/understand`; enable it in both role configs.
  - [x] **91F — Matt Pocock skills.** Add the pinned vendor family and
    `.families.json`; teach `sync-wiki-skills.py` not to prune it; add the
    engineering set to `PEER_SKILLS`; run `setup-matt-pocock-skills` in the
    root, peer and master workspaces with the local markdown tracker.
  - [x] **91G — Issue flow.** Peer pusher, Master `POST /api/v1/issues`
    listener, redaction, store, triage state and the Master Issues tab. Signed
    round-trip and refusal tests.
  - [ ] **91H — Bundle and gates.** Regenerate goagx (never hand-edit), update
    SBOM/notices and `.gitignore`, run the full gate suite.
  - **DoD**: `make validate`, `make contract-test`, `make render-check`,
    `make test-all`, `make ci`, `make lint`, `make shellcheck`,
    `make role-skills-check`, `make wiki-verify`, `make sbom-check`,
    `make drift-check` and `make bundle-verify` are green; the three workspaces
    load the skills and the issue tracker; the console renders the graph; the
    signed issue round-trip passes locally. Live cross-node and live browser
    legs are `DoD: confirm: user`.

  - **Status 2026-11-09 — 91A–91G verified; 91H local-only.** Contracts,
    Python core, Go service, `/understand*` skills, HTML/CSS console tab,
    Matt Pocock family and the signed issue round-trip are implemented and
    covered by `make ci`. Peer and master bundles were rebuilt and verified;
    the goagx tree was staged, verified and copied into the submodule. The
    published goagx remote still needs `make goagx-publish`, so
    `make drift-check` is red until that operator action; live cross-node and
    live browser legs remain `DoD: confirm: user`.

## Standing verification rules

- A gate that cannot fail is not a gate. Every claim needs a named test or a
  dated live observation.
- `make test-all` is the local truth; CI runs the same pre-merge gate.
- A live claim names the host and date. A development host never proves
  WireGuard, `chattr`, systemd, the signer or a browser surface.
- `PLAN.md` history is evidence; do not rewrite it to make a status look better.
- New roadmap work after `current: done` becomes a new step, not a reuse.

## Next

`current:` moves one step at a time, and only after the DoD is verified.
