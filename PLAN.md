---
title: sparknet Plan
updated: 2026-11-13
current: 111
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

## Step 94 — Sandbox domain vocabulary and policy authority

- [x] **Step 94** — Settle the execution-sandbox vocabulary and the
  policy-authority boundary. Documentation only: no contracts, code, manifests,
  submodule pins or live claims change.
  - [x] **94A — Glossary.** Reformat `GLOSSARY.md` into the domain-modeling
    structure, retain every existing term, strip file paths and table names,
    add the sandbox cluster and the authority vocabulary it needs, and name the
    collision pairs (`approval`, `supervisor`/`supervision`, `proposal`,
    `mount`, `execution`, `holder`, `owner`).
    **DoD**: every sandbox concept in ADR-0012/0013 and
    `contracts/sandbox-schema.json` resolves to exactly one glossary entry; no
    file path or table name remains; no term still used in the repo was removed.
    **Status 2026-11-10 — COMPLETE.** 72 unique terms in four clusters; every
    prior term retained; the sandbox contract's actions, identity, policy,
    mounts, exposure and refusal vocabulary resolve to an entry; no file path
    or table name remains.
  - [x] **94B — ADRs.** Amend proposed ADR-0012 for the layered names, the
    vault/config mount split, the peer-local backend/driver choice and the
    execution-surface classification. Add accepted ADR-0013 for the
    signed-`policy-update` versus local-`policy-proposal` boundary and the
    refuse-then-recreate lifecycle.
    **DoD**: ADR-0012 and ADR-0013 agree with the glossary and the sandbox
    contract; ADR-0013 records the independence of the two policy paths and the
    service-sandbox open edge; neither ADR claims deployment.
    **Status 2026-11-10 — COMPLETE.** ADR-0012 uses the layered vocabulary and
    the vault/config mount split; ADR-0013 records the authority split,
    independence, `policy-refused` recreation rule and the 20F service-sandbox
    open edge. ADR-0012 remains proposed; ADR-0013 is accepted as a model
    decision and claims no deployment.
  - [x] **94C — Verification and records.** Update `sessions/2026-11-10.md` and
    the architecture-decision line in `MEMORY.md`; append the Step 94
    transitions to `log.md`; run the docs gates.
    **DoD**: `git diff --check` and `make ci CI_QUICK=1` are green;
    `DoD: confirm: user` for the vocabulary and ADR read-through.
    **Status 2026-11-10 — COMPLETE.** Operator confirmed the vocabulary and ADR
    read-through. Session and memory records updated; `git diff --check` and
    `make ci CI_QUICK=1` pass (context, governance, phase8, keys, shims, lint,
    format, shellcheck, role-skills, validate, contract-test, render-check,
    SBOM). The full test suite was skipped because no code or contract changed.
  - **DoD**: 94A–94C each have their named gate; the vocabulary is used
    consistently in ADR-0012, ADR-0013 and the glossary; no production gate or
    live claim is made because no contract or code changed.
  - **Status 2026-11-10 — COMPLETE.** The glossary, ADR-0012 and ADR-0013 are
    the settled model; `current: done`. No contract, code, manifest, submodule,
    goagx or live change.

## Step 95 — Deep-module audit remediation

- [x] **Step 95** — Close the seven findings from the 2026-11-10 deep-module
  audit and record the one design decision that should not be rushed.
  - [x] **95A — Go capability catalog.** Add `issue-report` and
    `sandbox-supervise` to the Go vocabulary and sensitive set; pin the Go
    known/sensitive/Master-implied sets to `contracts/capabilities.json`; add
    cross-language grants for both capabilities.
  - [x] **95B — Registry acceptance.** Add `authz.accept_entry` as the one
    acceptance seam for a remote entry, make `evaluate` use it, and replace the
    five service-local copies with typed refusal mapping.
  - [x] **95C — Loader resolution.** Make `sparknet_loader` own the standard
    shared-directory policy; remove the role-service resolvers; guard against a
    new one.
  - [x] **95D — Vector view.** Add the stdlib-only shared read view and make the
    console use it instead of a second Qdrant HTTP client.
  - [x] **95E — Contract tests.** Split `tests/test_contracts.py` by contract
    boundary under `tests/contracts/`; keep the old path as a thin inventory
    marker; update both Makefile entry points.
  - [x] **95F — Package artifacts.** Move the directory artifact walk and
    exclusions into the shared package module; the CLI only parses arguments.
  - [x] **95G — Authz decision.** ADR-0014 keeps `sparknet-authz.py` as one deep
    module for this release and records the staged-split trigger.
  - **DoD**: `make test-all`, `CI_QUICK=1 make ci`, `make contract-test`,
    `make render-check`, `make sbom-check`, `make format-check`,
    `make shellcheck` and `git diff --check` are green; the goagx release is
    published and its pointer pinned.
  - **Status 2026-11-11 — COMPLETE.** All seven local issues are `done`.
    Commits: goSpark `cd2d72a`, peer `24bee7d`, master `edc45eb`, fabric
    `503a2f7`; goagx republished as `dcb84b4` and pinned. All four remotes are
    pushed; the release-pin commit is `ff2cd12`. GitHub issue mirroring remains
    blocked by the current PAT's missing Issues write. No live claim.

## Step 96 — Skill-based feedback loops and evaluations

- [x] **Step 96** — Turn the installed Matt Pocock skills into recorded,
  gating evaluations of AI work products and of the skills themselves; file the
  work local-first in all five repositories (96A–96F). Detail:
  `sessions/2026-11-11.md` and `log.md`.
  - **DoD**: `make test-all`, `CI_QUICK=1 make ci`, `make contract-test`,
    `make render-check`, `make drift-check` and `git diff --check` green; no
    live claim from this host.
  - **Status 2026-11-11 — COMPLETE.** 96A–96F verified; goSpark `2e8b2be`,
    fabric `8f9bb08`, goagx `c77170b`; `make drift-check` green. The GitHub
    mirror remains blocked by the PAT; local `.scratch/issues/` canonical. No
    live claim.

## Step 97 — Restore the fabric dependency guard

- [x] **Step 97** — Restore `tests/test_services.py` at the fabric root, the
  path both `pyproject.toml` and `requirements.txt` cite, with the allow-list
  and mirror guards; prove each can fail.
  - **DoD**: the guard fails when a stray dependency is added to either file
    and passes after reverting; `make lint`, `make format-check` and the fabric
    suite are green; both prose citations resolve to a real file.
  - **Status 2026-11-11 — COMPLETE.** `tests/test_services.py` restored at the
    cited path. Mutation 1 (`requests>=2` in `pyproject.toml`) failed both
    guards; mutation 2 (`httpx>=0.27` in `requirements.txt`) failed only the
    mirror guard; each reverted green. Full fabric suite, lint and format
    green. No live claim.

## Step 98 — Make the pytest tier vocabulary selectable

- [x] **Step 98** — Apply the registered tiers to every fabric test module and
  add the selection path, so `-m unit` is a real fast loop.
  - [x] **98A — Marks.** Module-level `pytestmark` in all 128 fabric test
    modules: 47 `unit`, 44 `integration`, 21 `contract`, 11 `layout`, plus the
    5 that already carried an integration/slow mark.
  - [x] **98B — Selection and guard.** `make test-unit` and
    `make test-integration`; `tests/test_tier_markers.py` fails on an unmarked
    module and on a `unit` module that imports or calls a process/socket
    boundary.
  - [x] **98C — Docs.** `CONTRIBUTING.md` explains the tiers and the two
    targets.
  - **DoD**: `make test-unit` is green and fast; `make test-integration` is
    green; the full suite and `CI_QUICK=1 make ci` are green; lint and format
    are clean.
  - **Status 2026-11-11 — COMPLETE.** `make test-unit` passed in 17.2 s (213
    tests) and `make test-integration` in 2 m 07 s; the full fabric suite and
    the quick pre-merge gate are green. No test behavior changed; the change is
    additive marks plus the meta-guard.

## Step 99 — Pin the memory-filter dependency boundary

- [x] **Step 99** — Decide and enforce the boundary around the WebUI-only
  adapter instead of letting a legitimate exception look like runtime drift.
  - [x] **99A — Decision.** ADR-0015 records the filter as an adapter executed
    by Open WebUI, the one-physical-file rule, and the lazy optional-extra
    rule for the Understand extractor.
  - [x] **99B — Guard.** `tests/test_dependency_boundary.py`: module-level
    imports are stdlib plus `cryptography`, with `httpx`/`pydantic` allowed
    only in the filter; lazy imports are only optional extras; the WebUI name
    is a symlink to the shared file; no runtime module names the adapter.
  - [x] **99C — Docs.** `webui/README.md` records the symlink and the reason.
  - **DoD**: the guard fails on a stray shared import and passes after
    reverting; the symlink resolves; the full suite, lint and format are green.
  - **Status 2026-11-11 — COMPLETE.** Mutation reverted green; symlink
    resolves; full suite, lint and format green. No live claim.

## Step 100 — Read-only eval audit surface

- [x] **Step 100** — Surface skill-eval verdicts in the read-only console.
  - [x] **100A — API.** `/api/evals` reads this node's delegate runs through
    the loopback gateway, validates every record with the shared module, counts
    invalid/tampered records without showing them, and projects
    node/skill/verdict/subject/evaluator/findings (bounded).
  - [x] **100B — Surface.** The `evals` menu and panel are wired through the one
    `SURFACES` table, admin-only like Issues; both role configs list it.
  - [x] **100C — Boundary.** Audit-only: no KB path, no knowledge write, no
    authority. Cross-node aggregation is a transport decision and is filed
    separately.
  - **DoD**: console tests cover a valid record, a tampered record and the
    projection; the full suite, lint, format and app.js syntax are green.
  - **Status 2026-11-11 — COMPLETE.** Valid/tampered projection test green;
    full suite, lint, format and drift-check green. No live claim.

## Step 101 — Console degrades on a malformed gateway payload

- [x] **Step 101** — Diagnose and fix the console endpoints that drop the
  connection when the local memory gateway answers with a non-object JSON
  value.
  - **Symptom.** `/api/evals` and `/api/projects` error instead of showing an
    empty view when the gateway returns `[]`; the dispatcher does not catch
    handler exceptions.
  - **Loop.** `tests/test_webui_console.py::test_evals_route_degrades_when_the_gateway_returns_a_non_object`
    with a fake gateway returning `[]`. RED:
    `AttributeError: 'list' object has no attribute 'get'` at
    `_local_gateway_runs`; GREEN after the shape guard.
  - **Hypothesis.** A non-dict payload reaches `payload.get("runs")`; the data
    path, not the transport exceptions, is the defect.
  - **Fix.** `_local_gateway_runs` returns an empty view unless the payload is a
    dict and `runs` is a list; both consumers are covered.
  - **DoD**: the regression test, the console file, the full suite, lint and
    format are green; `make drift-check` green after the goagx republish.
  - **Status 2026-11-11 — COMPLETE.** Regression green; goagx `59a83e7`;
    drift-check green. No live claim.
## Step 102 — Refuse a malformed delegate run record
- [x] **Step 102** — Diagnose and fix `project report` aborting with a raw
  traceback when the run view carries a non-object `result` or `task`.
  - **Symptom.** `project report` exits with
    `AttributeError: 'list' object has no attribute 'get'` instead of a clean
    refusal; no report page is written.
  - **Loop.** `tests/test_project_script.py::test_report_refuses_a_malformed_run_record`
    with a fake gateway returning `result: []` and then `task: "..."`.
  - **Hypotheses.** (1) a non-dict `result` reaches `.get()` in the report body
    — confirmed by the traceback at line 428; (2) a non-dict `task` reaches
    `.get()` in the Task section; (3) missing values are already handled by the
    old `or {}`.
  - **Fix.** `cmd_report` refuses a run whose `result` or `task` is not an
    object, before the review gate and before any write.
  - **DoD**: both malformed variants refuse cleanly with no report file; the
    project suite, full suite, lint and format are green; goagx republished.
  - **Status 2026-11-11 — COMPLETE.** Both variants refuse; full suite, lint,
    format green; goagx `62797c6`. No live claim.
## Step 103 — Nocturnal skill-eval subtasks and network summary
- [x] **Step 103** — Give the nocturnal window a deterministic eval mode
  without breaking model-prompt subtasks.
  - [x] **103A — Cluster contract.** `shared/sparknet-cluster.py` accepts a
    per-subtask `mode` (`model` default, `skill-eval`), refuses unknown or
    mixed modes, and the nocturnal artifact contract documents the mode, the
    `fixture:<name>` ref, the signed record output and the Master
    `network_evals` summary.
  - [x] **103B — Harness.** `scripts/sparknet-skill-eval.py --candidate`
    evaluates one fixture diff under `scripts/skill-evals/fixtures/`, refuses
    paths outside it, and emits a valid record; defect and clean fixtures.
  - [x] **103C — Peer executor.** The dispatch bridge runs the harness for a
    `skill-eval` subtask with a fixed argv and a `fixture:<name>` ref only;
    model prompts keep the Ollama path. Results stay signed with
    `model: skill-eval-rules/1`.
  - [x] **103D — Master summary.** The scheduler validates every eval output
    and writes `network_evals` (records plus pass/warn/fail/invalid counts)
    into the signed aggregate; a tampered record counts invalid, never pass.
  - [x] **103E — Rehearsal.** `make nocturnal-rehearsal` runs the offline
    scheduler suite: plan/arm/abort/drain, a trivial model job, an eval job and
    a tampered record.
  - **DoD**: fabric, peer and master suites, lint, format, contract-test,
    render-check and `make nocturnal-rehearsal` are green. The live 02:00–05:00
    window remains issue #8 (`DoD: confirm: user`) and is not claimed here.
  - **Status 2026-11-11 — COMPLETE (code and rehearsal).** Suites and
    `make nocturnal-rehearsal` green; peer `89afef4`, master `b93f077`, fabric
    `ab9be7a`, goagx `2b4de0f`. Live window is issue #8.

## Step 104 — Migrate the two large node scripts to Python

- [x] **Step 104** — Replace the logic in `spark-entrypoint.sh` and
  `sparknet-node-setup.sh` with Python implementations behind thin exec
  wrappers, keeping the names, flags and output stable.
  - [x] **104A — Behavioural tests.** `tests/test_entrypoint.py` exercises the
    dispatcher argv/env construction, the boot helpers and the fail-closed
    key/secret paths in the unit tier; the node-setup join suite covers the
    env-file and join contracts through the wrapper.
  - [x] **104B — Entrypoint.** `spark-entrypoint.py` (3.8-compatible) is the
    implementation; the shell file is a five-line exec wrapper. Both
    Dockerfiles copy and byte-compile it; the release-export, goagx-publish and
    layout lists carry the new file.
  - [x] **104C — Node setup.** `sparknet-node-setup.py` owns args, preflight,
    compose, bundle staging, join, env-file rendering, the GPU fixture and the
    actions; the shell file is the same thin wrapper.
  - [x] **104D — Target-host verification.** Build and run the image and the
    setup flows on agx64/agx32, including SIGTERM drain, a join and a second
    idempotent run. `DoD: confirm: user`; no live claim from this host.
  - **DoD**: the fabric suite, peer and master suites, lint, format, shellcheck,
    contract-test, render-check and `make drift-check` are green; the two
    live checks are recorded with host and date.
  - **Status 2026-11-12 — COMPLETE (live target-host verification).** Local:
    `make ci`, `make test-all`, `make container-test` (3 passed, `:py104`),
    `make drift-check`, shellcheck and both bundle verifies green. On `agx32`
    (peer) and `agx64` (master): `help`, `vllm-stub`, `compute`,
    `memory-gateway`, `llama-embed`/`llama-rerank` start; `whisper-asr` starts
    both children and exits 0 on SIGTERM. Setup up/down/up is idempotent;
    `--role master`, `--platform agx` and the join fields pass. Env rendering
    differs only in two comment lines (old unquoted-heredoc backticks); the
    real vLLM model was not started (upstream down), and the from-source image
    rebuild remains a release task (thin `:py104` used). goagx `c07e40d`;
    detail in the session.

## Step 105 — Skill catalog access across OpenCode and Open WebUI

- [x] **Step 105** — Give the fabric, peer and Master one deterministic skill
  catalog with search/load access, and stop the master catalog from flooding
  every prompt. Step 104D remains open and is not blocked by this step.
  - [x] **105A — Catalog index.** Emit `.opencode/skills/.catalog.json` for the
    base suite, peer and master; entries are sorted by `(group, id)`; the
    existing `.inventory.json` shape stays unchanged.
  - [x] **105B — Access surface.** Add `shared/sparknet-skills-mcp.py` and
    `scripts/sparknet-skills.py`; groups, list, search, load and path are
    read-only and role-scoped.
  - [x] **105C — OpenCode.** Add the MCP server, a featured allow-list using
    `permission.skill`, and the missing base suite path to the peer and master
    configs.
  - [x] **105D — Open WebUI engine.** Mount the catalog into the sandbox,
    inject the MCP server and the featured permission set, and keep the master
    catalog out of a peer sandbox.
  - [x] **105E — Verification and docs.** Tests for deterministic ordering,
    scoping and path safety; ADR 0020; the role READMEs and context pack.
  - **DoD**: `make role-skills-check`, `make test-all`, `make contract-test`,
    `make sbom-check` and `make render-check` are green; a master session
    advertises at most the featured set; the MCP returns a hidden skill by
    search and load; the engine config test proves the catalog mount.
  - **Status 2026-11-12 — COMPLETE.** Catalogs sorted; MCP round-trip green;
    both bundles verify. Live: both engines/consoles restarted, both catalogs
    check clean, both `/api/skills` routes return data. Commits: peer
    `16b4c66`, master `abbc8db`, fabric `21edb5e`; goagx `9e80adf`. The model
    upstream is down, so end-to-end chat is not claimed.

## Step 106 — Live-verify the peer eval audit transport

- [x] **Step 106** — Close issue #9 by proving the signed peer→Master eval
  report live.
  - **DoD**: a signed valid report from `agx32` is accepted and appears in the
    Master `/api/evals`; a duplicate is a no-op; a self-consistent report with
    a tampered record is stored and counted `invalid`, never shown; no vault/KB
    read; dated host-specific evidence. `contracts/knowledge-flow.md` records
    the live pair; contract-test and drift-check are green.
  - **Status 2026-11-12 — COMPLETE (live pair).** `agx32` pushed the signed
    `defect-shell-true` report; accepted, duplicate no-op, tampered counted
    `invalid`. `/api/evals`: `fail: 1`, `invalid: 1`, `total: 1`, `read_only`.

## Step 107 — Capture the AGX LLM engine research and improve the vault

- [x] **Step 107** — Capture the dusty-nv review, the runtime/model decision,
  the hardware truth and the storage contract; run the full wiki cycle.
  - **DoD**: the reference/entities/ADR/concept/synthesis/GLOSSARY/index/hot
    pages are cited, cross-linked and current; the hardware truth is AGX Xavier
    64/32 GB; the full wiki cycle and `make ci`/`test-all`/`drift-check` are
    green; no live claim for the unimplemented engine.
  - **Status 2026-11-13 — COMPLETE.** The pages are written and linked; the
    hardware truth is 64/32; the wiki cycle and the local gates are green. Step
    108 is next.
## Step 108 — Replace the AGX text engine with llama.cpp/llama-server
- [x] **Step 108** — Implement `sparknet-llm:agx`, remove the vLLM build from
  the node image, keep `vllm:8000`/`vllm-stub`/aux, stage the teacher/student
  models, migrate storage, and validate on agx64/agx32.
  - **DoD**: the `sparknet-llm:agx` image serves the teacher on agx64 and the
    student on agx32 through the OpenAI endpoints; the precontext is present;
    the node image no longer builds vLLM; the `vllm-stub`/aux/agent/compute
    paths still work; the active model files are on the root and the vaults on
    the data drives; the live checks are dated and host-specific; `make ci`,
    `make test-all`, `make drift-check`, `make container-test`, `make bundle`/
    `bundle-verify` and the goagx publish/pin are green; no live claim before
    the checks run.
  - **Status 2026-11-13 — COMPLETE.** Static `sparknet-llm:agx` serves
    Qwen3.6-35B-A3B on `agx64` and Qwen3.6-27B on `agx32`; precontext 16000 B;
    `vllm-stub`/embed/rerank/agent/compute validated; models on root, vaults on
    `/mnt/ai`; `make ci`/`test-all`/`drift-check`/`container-test` and the
    bundle/goagx gates green.
## Step 109 — Dual teacher/student bake-off
- [x] **Step 109** — Keep both same-version sets available and benchmark them
  on the real AGX engine: Qwen3.6-35B-A3B Q4_K_M + Qwen3.6-27B Q4_K_M and
  Qwen3-32B Q4_K_M + Qwen3-0.6B Q8_0.
  - **Scope**: no training; the distillation pass is the teacher→student
    agreement eval (`held_out_teacher_agreement`, quality agreement, refusal
    rate, latency).
  - **Method**: run the no-precontext pass first, then the fabric-precontext
    pass; record teacher and student decode tok/s separately; quality floor
    **1.0**; show the speeds and recommend the winner using student
    precontext-on speed first, teacher precontext-on speed second, memory
    third.
  - **DoD**: both sets are catalogued and staged; `scripts/sparknet-model-set.py`
    switches the active engine; the OpenAI bake-off configs and the agreement
    eval are implemented and tested; both no-precontext and precontext results
    are recorded for both sets; the report shows teacher/student speeds and a
    recommendation; the winner stays on root and the other set moves to the
    cold store; `make ci`, `make test-all`, `make contract-test`,
    `make drift-check`, `make goagx-publish`/pin and the bundle gates are
    green; the live checks are dated and host-specific.
  - **Status 2026-11-13 — measured.** All four runs passed quality 1.0.
    `qwen3.6`: teacher 18.54/18.08 tok/s, student 4.41/4.54, agreement 0.653.
    `qwen3`: teacher 3.94/3.65, student 76.78/57.33, agreement 0.608.
    Recommendation: `qwen3` on student speed; operator chose `qwen3.6`.
  - **Status 2026-11-13 — COMPLETE.** `qwen3.6` stays on root; Qwen3 set
    cold under `/mnt/ai/models/`; re-stage with
    `scripts/sparknet-model-stage.py`; report/agreement saved; all gates and
    goagx publish/pin green.
## Step 110 — Qwen3-2507 main/teacher + peer model stack
- [x] **Step 110** — Make Qwen3-30B-A3B-2507 the agx64 main/teacher and Qwen3-4B-2507 the agx32 student at 262k; add Qwen3-Coder-30B, Qwen3-Embedding-0.6B and Qwen3-VL-4B to the agx32 stack; retire Qwen3.6 and the old Qwen3 pair.
  - **Status 2026-11-14 — COMPLETE.** Qwen3-30B-A3B-2507 is the agx64
    main/teacher and Qwen3-4B-2507 the agx32 student at 262k q8 KV; the 4B
    candidate is on agx64 via the signed 8091 artifact; coder 30B 65k,
    embedding 0.6B and VL 4B are in Ollama; gates green.
## Step 111 — Daily auto-distillation
- [ ] **Step 111** — Distill on agx32 daily or on request from the 30B main/teacher; export the 4B GGUF; sign/upload to agx64; sync the agx64 student copy daily/on request when idle; benchmark and promote/rollback.
  - **DoD**: consented dataset, 4B LoRA at 16k, merge/GGUF, signed upload, idle-aware copy, candidate benchmark, operator promotion, timer/manual trigger, docs/tests/gates green.
  - **Status 2026-11-14 — BLOCKED (external GPU host).** Dataset/collect/doctor,
    the keyless bundle, external Dockerfile, sign/8091 and idle sync are
    implemented. agx32 is live: Qdrant reindexed to 1024, Qwen3-4B plus CPU
    embedding healthy, daily bundle cron 03:15, and Qwen3.6 moved cold. Only
    the external GPU training host is missing.
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
