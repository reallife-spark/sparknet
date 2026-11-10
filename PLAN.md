---
title: sparknet Plan
updated: 2026-11-10
current: done
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

- [x] **Step 91** — Port Understand-Anything to Python/Go, add its skills and
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
  - [x] **91H — Bundle and gates.** Regenerate goagx (never hand-edit), update
    SBOM/notices and `.gitignore`, run the full gate suite.
  - **DoD**: `make validate`, `make contract-test`, `make render-check`,
    `make test-all`, `make ci`, `make lint`, `make shellcheck`,
    `make role-skills-check`, `make wiki-verify`, `make sbom-check`,
    `make drift-check` and `make bundle-verify` are green; the three workspaces
    load the skills and the issue tracker; the console renders the graph; the
    signed issue round-trip passes locally. Live cross-node and live browser
    legs are `DoD: confirm: user`.

  - **Status 2026-11-10 — COMPLETE, including live legs.** The Step 91 code is
    committed and pinned: goSpark `970d714`, peer `a5f80e7`, master `ea4822a`,
    root code `7b7ae6b`, goagx `c3efd98`. Live role code was updated on `agx64`/`agx32`, the
    Master registry granted the peer `issue-report`, and `/etc/sparknet/issue-keys.json`
    bound the peer key. Live issue `live-step91-issue` was signed by
    `sparknet-node-0002` and delivered from `10.100.0.2` to the Master's
    `10.100.0.1:8090`; the Master recorded it in
    `/mnt/log/sparknet-issues.jsonl`, the console reported it, and the
    Master-local triage transition closed it `done`/`wontfix`. Chromium browser
    checks rendered the Master Issues tab and both Understand tabs; the peer
    issue is operational data, not knowledge and not authority. A live console
    bug (`.panel[hidden]` not hiding panels) and swapped node labels were fixed
    and deployed. Peer and master bundles were rebuilt and verified. No live
    claim is made for any surface outside these dated checks.

## Step 92 — Four-candidate architecture exploration

- [x] **Step 92** — Explore the four `improve-codebase-architecture` candidates
  in report order, one candidate at a time. This is design-only: no production
  code, contracts, manifests or submodule pins change. Operator approved:
  design-only decision packs, report order, explicit per-candidate gate,
  `design-it-twice` only for contested adopted seams, Step 92 tracking, root
  ADRs for cross-role decisions and goSpark ADRs for Go-plane decisions.
  - [x] **92A — Graph producer.** Verify the Python/Go scan-and-diff split,
    ADR-0017 friction, schema fidelity and build/gate/bundle gaps. Grill the
    seam, policy ownership, diff semantics, failure modes, compatibility and
    parity tests. Adopted: Python owns `scan`/`diff`; Go keeps query/export/MCP;
    Go CLI commands are adapters; `gofrag` keeps `go/parser` over Python scan
    records. Seam settled as the path-stable `shared/sparknet-understand.py`
    JSON CLI; no design-it-twice needed. ADR-0017 superseded by goSpark ADR
    0018. **DoD: confirm: user — confirmed 2026-11-10.**
  - [x] **92B — Issue module.** Verify the peer, Master and console issue paths,
    contract, store, triage state and signed-route authority. Adopted: one
    shared issue module in `shared/sparknet-issue.py` plus
    `shared/sparknet_issue/`; authz remains the envelope/signature owner; peer,
    Master and console are adapters. Triage transitions are in scope through an
    append-only `triage.jsonl` and derived `triage.json`; one redaction policy;
    wire contract unchanged. Root ADR `0009-issue-module.md` records it.
    **DoD: confirm: user — confirmed 2026-11-10.**
  - [x] **92C — Skill catalog.** Verify the four sync scripts, manifest shapes,
    licenses, host-path guards, gates and tests. Adopted: one build-time engine
    under `scripts/skill_catalog/` with wiki, Matt, Understand and role adapters;
    existing script paths and flags stay stable. Internal manifest model
    converges; external manifest shapes remain unchanged. Engine owns copy,
    digest, manifest/check, host-path guard and missing-source handling; adapters
    own family transforms and role-catalog policy. Root ADR
    `0010-skill-catalog.md` records it. **DoD: confirm: user — confirmed
    2026-11-10.**
  - [x] **92D — Core split.** Re-scoped against 92A: this is internal locality,
    not producer duplication. Adopted the four-module map: `schema.py`,
    `production.py`, `algebra.py`, and a path-stable `core.py` facade, with
    `build.py` as orchestration. Design-it-twice compared minimal, flexible and
    common-caller maps; the four-module common-caller map won. Root ADR
    `0011-understand-core-split.md` records it.
    **DoD: confirm: user — confirmed 2026-11-10.**
  - [x] **92E — Synthesis.** Compared all four decisions, resolved overlap and
    conflicts, and produced one combined implementation roadmap with interfaces,
    migration, tests, gates, cross-repository commit boundaries and goagx
    impact. Implementation order: graph producer, issue module, skill catalog,
    core split. **DoD: confirm: user — approved 2026-11-10.**
  - **DoD**: 92A–92D each have a confirmed decision memo and no open design
    frontier; 92E has an operator-approved roadmap; `PLAN.md`, `log.md`,
    `sessions/2026-11-10.md`, `GLOSSARY.md` and any accepted ADRs are current;
    `git diff --check` passes and `make validate` is green. No production gates
    are claimed because no production code changed.
  - **Status 2026-11-10 — COMPLETE.** All four candidates adopted, the roadmap
    approved, and the design-only records written. Step 91 stays open on its
    live-only confirmations; this step does not claim them.

## Step 93 — Implement the architecture roadmap

- [x] **Step 93** — Implement the approved 92E roadmap in order. The graph
  producer and core split both touch `shared/sparknet_understand/`; never run
  them in parallel.
  - [x] **93A — Graph producer.** Python owns `scan`/`diff`; Go `scan`/`diff`
    and `parse` are adapters over `shared/sparknet-understand.py`; `gofrag`
    keeps `go/parser` over Python `FileRecords`; Go preserves raw graph fidelity
    for query/export/MCP; duplicate Go scan/diff policy deleted. Built
    `sparknet-understand`, added root `understand-check`, one cross-language
    parity fixture and ADR 0018. **DoD: verified 2026-11-10** — Go adapter,
    parse, scan and raw-fidelity tests pass; `make -C gospark ci`,
    `make understand-check`, `make test-all` (exit 0) and
    `make contract-test` are green. goagx was republished as `fc9ccee` with
    goSpark `970d714`; no role or live claim is made.
  - [x] **93B — Issue module.** Implemented `shared/sparknet-issue.py` and
    `shared/sparknet_issue/` for parse, `body_sha256`, redaction, validation,
    ledger/latest view, triage and projection. Peer pusher, Master intake and
    console are adapters; authz remains the envelope/signature owner. Added the
    append-only `triage.jsonl`, derived `triage.json`, Master triage CLI and
    read-only effective-status projection. **DoD: verified 2026-11-10** —
    module, route, console and triage tests pass; peer/master suites,
    `make test-all`, `make ci`, `make contract-test`, `make render-check`,
    `make sbom-check`, `make validate`, lint/format/shellcheck green. Committed
    as peer `a64e993` and master `8580214`; no live claim.
  - [x] **93C — Skill catalog.** Implemented
    `scripts/skill_catalog/{__init__,engine}.py` and moved wiki, Matt,
    Understand and role sync onto the shared copy, digest, manifest, host-path
    and missing-source mechanics. The four existing script paths and external
    manifest shapes remain stable. **DoD: verified 2026-11-10** —
    `tests/test_skill_catalog.py`, `make wiki-verify`, `make role-skills-check`,
    `make sbom-check`, `make test-all`, `make ci` and lint/format/shellcheck are
    green.
  - [x] **93D — Core split.** Implemented `schema.py`, `production.py`,
    `algebra.py` and the path-stable `core.py` facade; `build.py` and the
    extractors/knowledge/figma/domain/CLI callers now import the narrow modules.
    **DoD: verified 2026-11-10** — focused module tests plus the existing
    integration fixture pass; `make understand-check`, `make test-all`,
    `make ci` and lint/format/shellcheck are green; caller paths are unchanged.
  - **DoD**: each implementation step has its named gates; cross-repository
    commits land role changes before superproject pins; goagx is republished
    where the distributed tree changes; no live claim comes from this host.
  - **Status 2026-11-10 — COMPLETE.** Graph adapters, issue module, triage
    writer, skill-catalog engine, console projection and core split are green.
    goSpark `970d714`; Step 93 code root `c5602cc`; the live-fix follow-up
    is peer `a5f80e7`, master `ea4822a`, root `7b7ae6b`, goagx `c3efd98`. Step 91 and the role live-leg
    confirmations remain open and are not claimed here.

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
