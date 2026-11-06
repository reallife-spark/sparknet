---
title: sparknet Plan
updated: 2026-11-06
current: 88
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

## Step 75 — User-node AI context, knowledge flow and self-healing

- [x] **Step 75** — Make the fabric's documented and tested behaviour match the
  user-node model:
  - [x] **75A — Contract map.** Add `contracts/knowledge-flow.md`; name every
    channel, its authentication, what it may carry and what it must never carry;
    update the contract index, `index.md`, `llms.txt` and README pointers.
  - [x] **75B — Governance set.** Rewrite root, peer and master
    MISSION/INTENT/AGENTS/MEMORY/PLAN to the slim model. Master status moves to
    `MEMORY.md`/`PLAN.md`; `master-node/PLAN.md` is canonical and the old path
    is a symlink.
  - [x] **75C — Context pack.** `scripts/sparknet-context-pack.py` generates
    `CONTEXT.md` at all three scopes; `make context-pack` / `context-check` are
    gates. Load it in OpenCode, Open WebUI RAG, per-user KBs/models and the
    vLLM/MASTERSPIKE precontext.
  - [x] **75D — Knowledge loop.** Add a peer RFI request client and a
    `vault.rfi` bridge tool; add the Master RFI responder over the allow-listed
    fabric corpus; prove the loop end to end on loopback and leave live units
    staged.
  - [x] **75E — Self-healing.** Add `make vault-health` / `make vault-heal`,
    a peer timer, and `docs/self-healing.md`; safe derived repairs only.
  - [x] **75F — Bloat sweep.** Archive the stale hot cache, full root MEMORY and
    PLAN, superseded Master planning docs and 2-line peer docs; dedupe the vault
    templates; add a governance gate against regrowth.
  - **DoD**: `make context-check`, `make governance-check`, `make validate`,
    `make contract-test`, `make test-all`, `make lint`, `make format-check`,
    `make shellcheck`, `make render-check`, `make sbom-check`, `make drift-check`
    and `make bundle-verify ROLE=peer|master` are green; `git diff` contains
    only intended changes; live legs are `DoD: confirm: user`.
  - **Status: complete 2026-10-31.** Local gates, both bundle verifications and `make drift-check` pass; `goagx` was republished. Live on agx64/agx32: provisioning/admin ingestion, RFI request→answer→inbox, bridge `vault.rfi`, telemetry/checkpoints, self-healing timer, admin federation `feed`/`users`, registry sequence 2 with `admin-supervise`. The remaining fresh signup→approval cycle is tracked in peer Step 11.


## Step 76 — Disposable user lifecycle (phase 1)

- [x] **Step 76** — Prove the peer account path on the live pair with a
  disposable user, then remove every artifact.
  - **Evidence**: on agx64 2026-10-31, signup created
    `026a5abd-659f-44dc-acba-b9c6a409404f` as `pending`; the Master console
    approved it; the provisioner created
    `/srv/sparknet/knowledge/peer-026a5abd-...` with 26 files and KB
    `6c6198bf-2462-4c1c-964c-f2349fe1485f`; `DELETE /api/v1/users/026...`
    returned 200; the vault, KB row/collection and per-user model were removed
    and the user no longer appears in `/api/v1/users/`.
  - **Note**: the Master admin WebUI still holds
    `e2e-20261101@sparknet.local` as its only admin; it was deliberately not
    deleted after the peer artifact cleanup.

## Step 77 — Share transport and 4203 human approval queue (phase 2)

- [x] **Step 77** — Put the existing share regime and ratification service on
  the wire without adding a second lifecycle.
  - [x] **77A — Peer listener.** `peer-node/services/sparknet-share-serve.py`
    carries `share.*` messages on 4201/4202 through
    `shared/sparknet-http.py`, persists records atomically at mode 0600 and
    refuses a corrupt state file. `peer-node/tests/test_share_serve.py` drives
    offer/accept/close over real signed loopback listeners, verifies restart
    durability and refuses unsigned/wrong-key messages.
  - [x] **77B — 4203 queue.** `master-node/services/sparknet-share-ratify.py`
    now has a signed, multi-key 4203 listener and a durable human-approval
    queue; the listener can queue but has no signer. Only `--approve/--refuse`
    asks the isolated signer. Tests cover the key ring, key/node binding,
    queue restart and the no-auto-ratify rule.
  - [x] **77C — Three-node share rehearsal.** `scripts/sparknet-share-rehearsal.sh`
    (backed by `scripts/sparknet-share-rehearsal.py`) builds three signed node
    trees and drives offer→accept→payload→4203 queue→human-signed lift over
    real loopback listeners; 10 assertions pass. `make share-rehearsal` is the
    target.
  - [x] **77D — Live pair exercise.** On 2026-10-31, agx64
    (`sparknet-node-0001`) and agx32 (`sparknet-node-0002`) exchanged a real
    `kb-share` (`share-1`, sha256 `8af639…`) and `session-handoff` (`share-2`,
    sha256 `c45080…`) over 4201/4202. The payloads landed under
    `/home/raxxar/sparknet/master-node/01_Inbox/share-share-{1,2}/` and both
    shares closed. `sparknet-share-serve.service` is enabled on both hosts;
    local operator actions use a 0600 Unix socket. The 4203 service is not
    enabled on the two-node pair.
  - **DoD**: local tests green and live pair evidence dated; satisfied. The
    `runtime` fields in `contracts/ports.json` stay `not-listening` because they
    describe this development host; their `status`/`runtime_why` record the live
    pair. The time-boxed stanza is still not applied, and 4203 stays a live
    three-node leg.

## Step 78 — Vector retrieval (phase 3)

- [x] **Step 78** — Peer-local vector index plus the Master's 4223
  `sparknet-fabric` and `sparknet-shared` collections, under privacy model A:
  only explicitly shared pages enter the Master. Add `cluster-dispatch` only
  after the share transport is live.
  - **Evidence 2026-10-31:** `scripts/sparknet-chroma.py` gained a `shared`
    scope that indexes only `01_Inbox/share-*/**/*.md`; the peer's local index
    built 897 chunks and answered a query. The Master built `sparknet-fabric`
    (143 chunks) and `sparknet-shared` (1 chunk from the live `share-1`
    payload). `master-node/services/sparknet-vector-serve.py` serves both over
    signed 4223; a peer signed query returned the shared payload and a fabric
    passage. Registry sequence 4 grants `cluster-dispatch`.
  - **Remaining:** reindex is an operator action (no timer), and `4223` is
    host-local in `sparknet-master-vector.service` rather than a tracked unit.
    The service holds no key and refuses a missing/stale index with 503.

## Step 79 — Master admin services (phase 4)

- [x] **Step 79** — Build the four contracted services:
  `4221` read-only file share at `/srv/sparknet/share`, `4220` read-only git
  mirror, `4222` status/dry-run NAT, and `4223` vector. No write path by
  default.
  - **Evidence 2026-10-31:** `sparknet-file-share.py` served `/v1/files` and
    `/v1/file/README.md` over signed 4221; `sparknet-nat-status.py` returned
    `/v1/status` and a dry-run with `changes: []` over signed 4222 as root;
    `sparknet-git-daemon.service` exported a read-only bare mirror at
    `git://10.100.0.1:4220/sparknet.git` (HEAD `1b868b8`, push refused);
    `sparknet-master-vector.service` served signed 4223. All four are enabled
    on agx32; the source is in `master-node/services/` and the git mirror is
    `/srv/sparknet/git/sparknet.git`.

## Step 80 — Phase 9 runbook and rehearsal

- [x] **Step 80** — Write and rehearse the destructive-recovery runbook for the
  approved window **2026-11-08 02:00–05:00 CET**; include snapshot, restore,
  rollback, verification and a named human trigger phrase. `DoD: confirm: user`.
  - **Prepared 2026-10-31:** `contracts/phase9-recovery-runbook.md` and
    `scripts/sparknet-recovery.py` (snapshot/verify/rehearse/restore, exact
    phrase, window guard, unsafe-target refusal). `make recovery-rehearse`
    deletes and restores a sampled file byte-for-byte. Non-destructive live
    snapshots verified: peer 221 files, Master role 159 + state 30; archives
    were deleted after hashing. The live destructive step is the only thing
    left and stays in the 2026-11-08 window.
  - **Target supplied 2026-10-31:** operator added `/mnt/backup/phase9` on
    agx32 (root-only 0700) and then explicitly moved execution to
    **2026-11-01 04:00–07:00 CET** (03:00–06:00 UTC).
  - **Executed live 2026-11-01 03:12 UTC:** froze the peer, wrote and verified a
    frozen `peer-0001-live.tar.gz` (222 files, sha256 `29cfe73d…`) and
    `user-vaults-0001.tar.gz` (147 files, `c59b047c…`) on agx32, deleted a
    sentinel, lifted `chattr +i` on the managed `wg1.conf`, restored the peer
    role root with the exact phrase, and re-applied the flag. Sentinel hash
    matched the manifest; services, WebUI (200, 1 tool server), vault-health,
    validate, keys-check and provenance all pass. The restore exposed a
    pre-existing wrong registry entry (placeholder WG key); sequence 5 fixed it
    to fingerprint `84bd134e…`, and the WebUI grant was re-minted. User vaults
    were backed up but not overwritten.


## Step 81 — Qdrant substrate, uplift and Master distillation

- [x] **Step 81** — Replace ChromaDB with Qdrant, lift consented vectors and
  inventory to the Master, and build the same-family distillation scaffold.
  - [x] **81A — Contracts.** `contracts/vector-store.md`, `uplift-schema.json`,
    `inventory-schema.json`, `distillation-schema.json`, the 8091 port, the
    `model-uplift` capability, the knowledge-flow channel and the superseded
    design note. `make contract-test` and `make render` pass.
  - [x] **81B — Substrate.** `scripts/sparknet-vector.py` is the Qdrant
    implementation; `sparknet-chroma.py` is a one-release alias. It keeps the
    scopes, chunking, stamp, reflex, shared/fabric policy and exact-corpus
    deletion. `tests/test_vector.py`, `test_vector_corpus.py` and
    `test_reflex_rag.py` pass locally; the real-Qdrant round trip skips when
    the optional package is absent.
  - [x] **81C — 4223 and Open WebUI.** Live 2026-11-01: Qdrant
    `v1.20.0` runs loopback-only on agx64 and agx32; Open WebUI was migrated to
    `VECTOR_DB=qdrant`, its 4 KBs and 107 files reindexed in 477 s, and
    per-KB and per-file retrieval both answered 200. 4223 serves
    `sparknet-fabric`/`sparknet-shared` from Qdrant and passed a signed peer
    query. ChromaDB is stopped and the old volume is retained for 14 days.
  - [x] **81D — Inventory.** `peer-node/services/sparknet-inventory-agent.py`
    projects users, models, KBs and content-free usage into
    `sparknet-inventory` and pushes through a durable outbox.
  - [x] **81E — Uplift.** `scripts/sparknet-uplift-push.py` and
    `master-node/services/sparknet-uplift-intake.py` implement signed 8091
    inventory, trace, snapshot and raw-KV artifact storage with digest checks.
    Peer timers `sparknet-inventory` (2 min) and `sparknet-uplift-sync`
    (15 min) are staged; the trace push path accepts JSONL batches.
    `scripts/sparknet-kv-export.py` packages a safetensors export and refuses
    `--from-vllm` until a version-pinned connector is proven.
  - [x] **81F — Distillation scaffold.** `master-node/services/sparknet-distill.py`
    plus `configs/distill.json`: dataset selection/redaction, doctor, planned
    run, evaluation, model card and an isolated-signer run record.
  - [x] **81G — Live rollout.** Registry sequence 7 grants `model-uplift` and
    was delivered 200. The inventory agent mirrors 41 user/model/KB/usage
    records into the Master's `uplift-inventory`; four Qdrant collection
    snapshots (peer, Open WebUI files/knowledge, inventory) were uploaded and
    one restored into a scratch collection (40 points). A real
    Qwen2.5-7B→Qwen2.5-1.5B QLoRA run (`run-20261101T101033Z-…`) trained on
    27 consented traces, evaluated at 0.2226 held-out teacher agreement, was
    signed through the isolated signer and published as a model card.
  - [x] **81H — Raw KV live capture.** vLLM 0.2.7 has no KVConnector API, so
    `peer-node/scripts/sparknet-vllm-kv-patch.sh` installs a fail-open
    in-process prefill hook (`sparknet-vllm-kv-dump.py`) into the live engine.
    A real request captured 299 KV blocks (32 layers, 8 KV heads, head_dim 128,
    fp16) as a 627 MB safetensors file; `sparknet-kv-export.py` compressed it
    to 554 MB and it was pushed to `/srv/sparknet/uplift/kv/…` on agx32
    (sha256 `f2ece221…`, gzip test and manifest digest verified).
  - **DoD**: `make contract-test`, `make test-all`, `make lint`,
    `make format-check`, `make shellcheck`, `make render-check`,
    `make sbom-check`, `make drift-check`, `make context-check`,
    `make validate`, `make keys-check`, `make shims-check`,
    `make bundle-verify ROLE=peer|master`; live legs are `DoD: confirm: user`.
  - **Status 2026-11-01:** complete. Local code and tests are green; the live
    Qdrant migration, 4223, inventory, four snapshots, one restore, consent
    grant, same-family distillation run and raw-KV capture are verified on
    agx64/agx32. Chroma volumes are retained for 14 days.


## Step 82 — Model catalog, store and runtime leases

- [x] **Step 82** — Make model placement and on-demand runtimes declarative:
  - [x] **82A — Catalog and placement.** `contracts/model-catalog.json` and
    `contracts/model-store.md`: the teacher is eligible only on `agx64` (64 GB
    peer), the student only on `agx32` (32 GB Master), embeddings on both, and
    teacher backup weights are forbidden on `agx32`. The catalog pins repo,
    revision, quant, runtime, license and fit.
  - [x] **82B — Pull and verify.** `scripts/sparknet-model-pull.py` selects by
    node, resolves the Hugging Face tree, verifies SHA-256, enforces a free-disk
    guard, writes a pinned manifest and refuses a hash or size mismatch. The
    token is read from `HF_TOKEN`/`--token-file`, never written or printed.
  - [x] **82C — Runtime leases.** `scripts/sparknet-model-runtime.py` plus
    `peer-node/configs/model-runtime/` and `master-node/configs/model-runtime/`:
    compose profiles for the teacher and student, `restart: "no"`, loopback
    health, memory guard, conflict refusal, `--replace`, idle-stop `reap` and a
    `0600` lease/audit state. The teacher and student runtimes cannot coexist on
    the same node, and the teacher is not a Master profile.
  - [x] **82D — Tests and gates.** `tests/test_model_catalog.py`,
    `tests/test_model_pull.py`, `tests/test_model_runtime.py`, the Make targets,
    `make render` and the contract README index. Local tests never pull a model
    or start a container.
  - **DoD**: `make model-catalog-check`, the three model test modules, `make
    contract-test`, `make render-check`, `make lint`, `make format-check`,
    `make test-all`, `make validate` and `make context-check` green. Live pulls,
    real teacher/student starts and the bake-off are `DoD: confirm: user`.
  - **Status 2026-11-01:** foundation implemented and locally tested; no model
    was downloaded and no container was started on this development host.

## Step 83 — On-demand teacher/student serving and bake-off

- [x] **Step 83** — Serve the teacher on `agx64`, the student on `agx32`, run
  the fixed benchmark matrix and record the pair. Training keeps an exclusive
  lease and stops student inference first.
  - [x] **83A — Benchmark harness.** `scripts/sparknet-model-bench.py` plus
    peer/master `bakeoff.json`: Ollama/OpenAI-compatible endpoints, load and
    decode metrics, resident memory, a fixed six-prompt quality suite, a
    deterministic leaderboard and a `0600` result file. It never pulls or
    starts a model.
  - [x] **83B — Teacher bake-off on agx64.** Thinking off, 8K context, aux
    embed/rerank/audio stopped. Qwen3.6-35B-A3B **Q4_K_M** (the preloaded
    `qwen3.6-35b-262k:latest`): **22.22 tok/s**, **21.21 GiB**, **100%**.
    Q8_0: **17.79 tok/s**, **34.39 GiB**, **100%**; Q4_K_M is the winner.
  - [x] **83C — Student pull and bake-off on agx32.** Pulled and verified
    `qwen3.5-9b-q8` (8.9 GiB) and `qwen3.8-27b-q4` (15.3 GiB) into
    `/mnt/ai/models`, imported both into the Master's Ollama. 9B Q8:
    **11.27 tok/s**, **8.06 GiB**, **100%**. 27B Q4: **4.75 tok/s**,
    **14.73 GiB**, **100%**. **Qwen3.5-9B is the winner.**
  - [x] **83D — Serving posture.** Qwen3.6 Q4_K_M is available on agx64 and
    benchmarks at 22.22 tok/s / 21.21 GiB; it loads on first use with a 30 min
    Ollama keep-alive. Qwen3.5-9B is available on agx32 (11.27 tok/s / 8.06
    GiB). The peer WebUI filter includes both teacher candidates; llama3.2
    stays the fallback default. vLLM, embed, rerank and audio are stopped
    because Q4_K_M plus vLLM does not fit; the node-image text engine is
    on-demand.
  - [x] **83E — Runtime support finding.** Qwen3.8-Flash-Next 3.84 bpw is not
    downloaded: Ollama 0.32.13 / the image llama.cpp has no qwen4exp support.
    The 85 GB build would be unrunnable; it stays a catalog candidate pending a
    compatible runtime.
  - **DoD**: teacher/student health and `ollama ps` 100% GPU; student manifests
    hash-verified; memory within catalog limits; fixed suite 100%; winner pair
    recorded. The live serving path is **Ollama**, not the staged
    llama.cpp compose profile; that profile remains the declarative GGUF path
    for a future runtime.
  - **Status 2026-11-01:** complete on agx64/agx32. No training run was
    started in this step.

## Step 84 — Sparknet WebUI surface

- [ ] **Step 84** — Add the thin Open WebUI sidebar patch and the Mesh, Vectors
  and Learning pages, Qdrant settings, the scoped vector proxy and the 3D
  teacher/student data cloud.
  - [x] **84A — Contract.** `contracts/webui-surface.md`: peer/master menus,
    console scope, Open WebUI session validation, service-token fallback,
    read-only boundary and the honest 3D pilot label.
  - [x] **84B — Console service.** `scripts/sparknet-console.py`: loopback
    HTTP, Open WebUI token validation (peer user/admin, Master admin), Qdrant
    read-only view with uplift/training excluded, deterministic 3D projection,
    distillation run view, no secrets and no write path.
  - [x] **84C — Pages.** `webui/console/`: dependency-free Mesh/Vectors/Learning
    pages, collection table, interactive 3D canvas with role colors and cluster
    titles, teacher/student legend and run view.
  - [x] **84D — Open WebUI shell.** `webui/patch-openwebui.py` (idempotent
    0.12.x sidebar patch) and `webui/nginx.conf.template` (same-origin `/sparknet-console/`
    proxy). The patch is tested against a synthetic sidebar; the live patched
    image and nginx unit remain target-node actions.
  - [x] **84E — Live same-origin surface.** nginx is live in front of Open
    WebUI on `agx64:8181` and `agx32:10.100.0.1:8088`: Open WebUI is loopback
    (`127.0.0.1:8180` peer, `127.0.0.1:8080` Master), `/sparknet-console/`
    routes to the read-only console, and `/sparknet-menu.js` is injected into
    the Open WebUI HTML. The peer console accepted an Open WebUI admin token
    and returned a 500-point map; the Master returned 153 points. Browser click
    confirmation is `DoD: confirm: user`.
  - [x] **84F — Persistent units and snapshot.** `webui/systemd/sparknet-console@.service`
    plus `webui/install-console.py` write a user shim and enable the console on
    agx64/agx32. On the Master, root `sparknet-distill-status.service` + `.timer`
    write a sanitized `0644` snapshot of 5 runs; Learning now reads it without
    touching `/srv/sparknet/distill`. The optional source-level sidebar image is
    deferred; the live launcher is nginx-injected.
  - [x] **84H — Sparknet sidebar group.** Both Open WebUI instances inject a
    separate **SPARKNET** group directly below Notes/Workspace: peer shows Mesh,
    Vectors and Learning; Master shows Mesh, Vectors and Learning for all
    authenticated users. The peer Learning page fetches the Master's sanitized
    snapshot over signed 4221; it never stores a mirror.
  - [x] **84I — 3D zoom.** Added explicit `+`/`−`/Reset controls, a zoom
    percentage, wheel handling on the canvas and map wrapper, and keyboard
    controls. Verified with headless Chromium: 100% → 112% on click, → 151% on
    wheel, → 100% on reset.
  - [ ] **84G — Browser confirmation.** Click Mesh, Vectors and Learning from a
    signed-in peer and Master browser session; confirm the sidebar group, the
    peer read-only Learning view, the 3D cloud rotation/zoom, and the Master
    Learning runs render. **DoD: confirm: user.**
  - **DoD**: local gates green; live peer owner sees Mesh/Vectors, Master admin
    sees Mesh/Vectors/Learning; read-only vector exploration and the 3D pilot;
    Qdrant/training exclusions hold; live clicks are `DoD: confirm: user`.
  - **Status 2026-11-04:** the native SPARKNET sidebar group is live on both
    Open WebUI instances; peer shows Mesh/Vectors/Learning and the Master shows
    the same for authenticated users. Peer Learning is a signed 4221 read-only
    fetch of the Master snapshot (`source master:4221`). Zoom controls and
    wheel/keyboard behavior are live and browser-tested. Only 84G's final
    signed-in visual confirmation remains `DoD: confirm: user`.

## Step 85 — Per-vault typed memory and local delegates

- [x] **Step 85** — Add the typed memory plane and the local delegate broker
  without creating a second vault or a second authority path:
  - [x] **85A — Contract.** `contracts/memory-schema.json`, the
    `memory-supervise` capability, the `4110` node port, the knowledge-flow
    rows, the memory-bundle profile in `share-protocol.md` and the WebUI memory
    menu. `make contract-test` and `make render` pass.
  - [x] **85B — Go store.** `gospark/internal/memory`, `internal/delegates`,
    `cmd/sparknet-memory` and the delegate plan/run/event store; per-vault
    isolation, redaction, retention, export/import, lexical retrieval, vault-page
    indexing and an optional Qdrant semantic path are tested.
  - [x] **85C — Authority gateway.** `shared/sparknet-memory-gateway.py` verifies
    signed grants and Open WebUI sessions, narrows to one vault, and forwards
    only to the loopback Go service. A grant cannot name a sibling vault.
  - [x] **85D — Node surface.** `spark.compose.yml` and
    `goagx/sparknet.agx.compose.yml` carry the `memory` service; the image
    asserts `sparknet-memory`; the dispatcher has a `memory` subcommand; the
    setup script generates the gateway/local/WebUI tokens. Parity tests pass.
  - [x] **85E — Adapters.** An OpenCode MCP server, an Open WebUI filter, a bridge
    `memory_*` admin action family, and a read-only console Memory page.
  - [x] **85F — Project lifecycle and bundles.** `scripts/sparknet-project.py`
    creates signed `PROJECT.md`/`PLAN.md`, runs bounded delegates and files
    signed reports; `scripts/sparknet-memory-bundle.py` exports, validates,
    stages and imports a `sparknet-memory-bundle/1` payload. Project agents are
    role-local; the report is never written by a delegate.
  - **DoD**: `make memory-check`, `make contract-test`, `make render-check`,
    `make test-agx-node`, `make test-webui-console`, `make test-admin-supervise`,
    `make context-check`, `make lint`, `make format-check`, `make shellcheck`,
    `make test-all`, `make bundle-verify ROLE=peer|master`; live node starts,
    browser memory page and a live Master `memory_status` are
    `DoD: confirm: user`.
  - **Status: complete 2026-11-04.** The memory sidecar is live on agx64 (`4110` store, `4093` gateway), tokens are 0600, the peer console `/api/memory` returns 200, OpenCode MCP search/remember round-trips, the Open WebUI filter is installed/active/global and its gateway path was exercised with the WebUI service token, and the Master `memory_status`/`memory-read` path returned live records through the signed admin request. The cursor stays at 84 until 84G is confirmed.

## Step 86 — Open-weight model survey and weight-update path

- [ ] **Step 86** — Inventory the catalog and live Ollama models, benchmark the
  runnable open-weight candidates, and provide a verified promote/rollback path.
  - [x] **86A — Survey tool.** `scripts/sparknet-model-survey.py` inventories
    the catalog, pinned manifests and live Ollama tags; `plan` marks
    eligible/benchmark/embedding/skip rows with `memory_fit`,
    `runtime_unsupported` and `not_imported` reasons.
  - [x] **86B — Update tool.** `scripts/sparknet-model-update.py` tracks
    active/candidate/previous manifests, verifies the pinned manifest, refuses a
    promotion below 0.8 quality or without an operator, and supports rollback.
    `make model-survey|model-update-status|model-set-candidate|model-promote|model-rollback`
    are wired.
  - [ ] **86C — Full live survey.** Run every runnable model in the agx64 and
    agx32 matrices. The inventory/plan is live: 30 agx64 tags and 19 agx32
    tags; the 9B student (10.9 tok/s, 8.06 GiB, 100%) and Qwen3 embedding
    (4096-dim, 56.6 s) were sampled. The full matrix needs an operator window.
  - [ ] **86D — Live promotion drill.** Pull a new candidate, benchmark it,
    promote it and roll back while the aliases and runtime remain healthy.
  - **DoD**: the full survey report is recorded; a candidate passes the
    benchmark gate, is promoted, and rolls back cleanly; no weights enter a
    vault, bundle or 4223.
  - **Status 2026-11-04:** tools implemented and locally tested; live
    inventory/plan and two benchmark probes done. Full survey and promotion
    drill remain `DoD: confirm: user`.

## Step 87 — Open WebUI front end on the OpenCode engine

- [x] **Step 87** — Make Open WebUI the customer-facing front end and OpenCode
  the execution engine, keep the fabric's authority boundary, and update both
  live nodes to the current surfaces.
  - [x] **87A — Live audit and safety.** Backed up both WebUI volumes, both user
    vaults and both role state trees on 2026-11-05; captured the old Master's
    disposable admin, the stale cluster2 user surface and the peer's prompt/tool/
    function/model gaps.
  - [x] **87B — Users.** The peer keeps every human user; the Master admin
    surface was recreated with exactly one `admin@sparknet.local` account and
    signup off. The old cluster2 Master WebUI on `8181` was retired after its
    one user chat was exported and imported into the peer account; its volume is
    archived and removed.
  - [x] **87C — OpenCode engine and sandbox.** `peer-node/services/
    sparknet-opencode-engine.py` is the OpenAI-compatible adapter on loopback
    `4204`; it starts one OpenCode 1.19.5 sandbox per user, mounts only
    `peer-<user_id>`, uses an internal Docker network with a host model proxy,
    and runs with a read-only root FS, dropped capabilities and no key/state/
    ledger mount. `make -C peer-node opencode-runtime` builds the pinned image;
    `sparknet-opencode-engine@peer|master` runs it.
  - [x] **87D — Workspace baseline.** Open WebUI `v0.13.0` on both nodes; 16
    bilingual prompts, four user-scoped tools, the memory filter and the capture
    action are active; per-user models are based on `sparknet-chat` with the
    personal and structure KBs; the structure KB is rebuilt from the RAG
    allow-list; the static bridge grant tool server was removed.
  - [x] **87E — Master engine.** The Master admin surface uses the same engine
    with `--single-vault /srv/sparknet/knowledge/master-admin`; the role vault
    (keys, ledger, registry) is never mounted. A live admin chat returned
    `webui-master-ok` on agx32.
  - [x] **87F — Gates.** `make lint`, `format-check`, `shellcheck`, `validate`,
    `contract-test`, `render-check`, `sbom-check`, `make test-all` (592 peer +
    fabric + master) and `make ci CI_QUICK=1` are green. Live peer chat returned
    `engine-ok`; live build-in-sandbox wrote a test note; the vault tool lists
    only the signed-in user's vault and excludes `secrets-index.json`.
  - **DoD:** every gate green; live peer and Master engine round trips dated
    2026-11-05; no user account on the Master; no static grant in WebUI; no
    cross-user sandbox path. Browser click-through of the peer sidebar and the
    Master admin surface is `DoD: confirm: user`.
  - **Status: complete and live-verified on agx64/agx32 2026-11-05.** The
    Qwen3/Nomic Ollama embeddings measured ~20 s per request with the text model
    resident, so the existing CPU MiniLM index was kept; the engine's own vault
    tools make RAG secondary. Open WebUI and OpenCode pins are updated in the
    committed configs; the running node image was not rebuilt (the sandbox
    runtime and engine are 1.19.5).

## Step 88 — Role inversion: agx64 Master, agx32 peer

- [ ] **Step 88** — Invert the live pair so `agx64` is the elected Master at
  `10.100.0.1` and `agx32` is the peer at `10.100.0.2`, using a chained
  re-formation rather than a fresh election.
  - [ ] **88A — Freeze, backup, preflight.** Park 84G, 86C/86D, 87 click-through
    and Master 9G; freeze both hosts; archive and verify role vaults, user
    vaults, WebUI volumes, Qdrant volumes, memory/engine state, ledger,
    evidence, registry, trust root and `.env`; record exact units, paths,
    volumes, ports and key locations.
  - [ ] **88B — Identities and roster.** Update the committed identity
    templates to `sparknet-node-0001` at `agx64`/`10.100.0.1` and
    `sparknet-node-0002` at `agx32`/`10.100.0.2`; keep `role: peer` in every
    committed manifest; generate new node identity keys; keep the cluster keys
    on their hosts; build the new `cluster-members.json` with new fingerprints
    and existing cluster pubkeys; copy the held old root to `agx64` for chain
    verification.
  - [ ] **88C — Chained re-formation.** Run the exchange with
    `shared/sparknet-election.py serve --trust <old-root> --members
    cluster-members.json`; `agx64` runs `election-approve EXPECT=sparknet-node-0001`;
    `agx32` runs `election-request CANDIDATE=sparknet-node-0001`; verify 2/2
    signatures, `previous_root_id`, `epoch + 1`, `master_node_id`, and
    `verify_chain`; stop the old signer on `agx32`; start the new signer on
    `agx64` only after the root is formed.
  - [ ] **88D — Overlay and firewall.** Re-address `agx64` to `10.100.0.1/32`
    and `agx32` to `10.100.0.2/32`; re-render WireGuard and the host firewall;
    `agx64` Master is unrestricted, `agx32` peer egress is restricted to
    `10.100.0.1`; prove both directions and the peer restriction.
  - [ ] **88E — Move Master state/services to agx64.** Copy ledger, evidence,
    registry, old/new roots, `master-admin`, admin WebUI volume, Master Qdrant,
    uplift/distill and share-ratify/scheduler state; do not copy the old
    operational key or signer socket; start signer, ledger, parity, admin
    console/surface, 8090/8091, 4220–4223, 4203, scheduler and firewall units.
  - [ ] **88F — Move peer state/services to agx32.** Copy `peer-*` vaults,
    provisioner state, peer WebUI volume, peer Qdrant, memory and OpenCode
    engine state; generate a new peer node identity key; start guard, bridge,
    4201/4202, telemetry/checkpoint/inventory/RFI, memory 4110/4093, WebUI
    8181, engine 4204, Qdrant, provisioner, admin agent and self-healing.
  - [ ] **88G — Registry, grants and secrets.** Sign a higher-sequence registry
    for the new identities with the existing capability sets; deliver to the
    peer guard; re-issue grants and tokens; point admin federation and goSpark
    control/agent at the new hosts; rotate WebUI, admin, engine, memory,
    Qdrant and share secrets after migration.
  - [ ] **88H — Model placement.** Update `contracts/model-catalog.json`,
    `contracts/model-store.md`, runtime configs, compose files, WebUI model
    filters, manifests and tests so the `agx64` Master hosts the teacher and
    the `agx32` peer hosts the student; keep the weights in place.
  - [ ] **88I — Verify and clean up.** Prove root/signer/registry/overlay/
    firewall/services/data/model; run every local gate and both bundle
    verifications; archive old keys/root/registry, remove old role units and
    old user-data copies after verification; update `MEMORY.md`, `log.md`,
    sessions, `CONTEXT.md`, runbooks and model docs.
  - **DoD**: new root verifies and chains to the old root; signer on `agx64`
    returns the new root id; old signer on `agx32` is disabled; registry
    verifies on both; peer WebUI/user data/KBs/Qdrant/memory match the
    preflight; Master admin/ledger/uplift/distill are on `agx64`; teacher is on
    `agx64`, student on `agx32`; `make contract-test`, `make test-all`,
    `make lint`, `make format-check`, `make shellcheck`, `make render-check`,
    `make sbom-check`, `make drift-check`, `make context-check`,
    `make validate`, `make keys-check`, `make shims-check`,
    `make bundle-verify ROLE=peer|master`, `make ci` and
    `make -C gospark ci` are green; every live leg is `DoD: confirm: user`.

## Step 89 — Gemini sovereign-cluster blueprint adoption

- [ ] **Step 89** — Adopt the Gemini “Distributed Sovereign AI Cluster”
  blueprint on the inverted pair, under the accepted D1–D4 guardrails:
  signed supervision (not arbitrary Master control), NATS/JetStream plus a
  derived graph projection, and guarded data lakes/execution/Firecracker.
  - [ ] **89A — Contracts.** Add event-bus, agent, ABAC, collaboration,
    execution-daemon, self-improvement, package, release, graph-memory,
    retrieval, realtime-distillation and data-lake contracts; extend
    capabilities, ports, overlay, knowledge-flow, memory, RFI, share, uplift,
    telemetry, provenance and identity-grant schemas; add canonical envelopes
    and golden vectors.
  - [ ] **89B — Shared foundations.** Add `sparknet-abac.py`,
    `sparknet-event.py`, `sparknet-hybrid.py`, `sparknet-graph.py`,
    `sparknet-exec-rpc.py`, `sparknet-collab.py` and `sparknet-package.py`;
    mirror the canonical forms in goSpark and pin cross-language vectors.
  - [ ] **89C — Event bus and sub-agents.** Put NATS/JetStream on the overlay,
    add the Master orchestrator and peer agent bus, implement real engineering/
    cyber/vault-curator agents, and prove topic/ABAC routing on loopback.
  - [ ] **89D — ABAC, memory, graph and hybrid retrieval.** Classify at O1
    ingestion, enforce ABAC in the memory gateway/store, add document links,
    the O1→O2→O5 pipeline, the derived graph and the semantic+agentic hybrid
    response that gives both result sets to the agent.
  - [ ] **89E — Master surfaces.** Add dashboard APIs for nodes/queue/KB/users/
    lake/distill/events/ABAC/collab; add consented lake intake, collaboration
    broker, online distillation scheduler and signed package index; writes stay
    signed admin requests.
  - [ ] **89F — Peer surfaces.** Add bridge routes for events/collab/exec/hybrid/
    graph; add the user-privileged execution daemon, collaboration client,
    self-improvement loop, package CLI, trace tap and dual teacher/student
    response.
  - [ ] **89G — Collaboration and execution.** Implement cross-department live
    collaboration with personal agents, ABAC filtering and audit; implement the
    argv-only execution daemon with pairing, signed JSON-RPC, user OS caps and
    no `shell=True`.
  - [ ] **89H — Self-improvement and packaging.** Add the Firecracker/worktree
    mutation loop, deterministic benchmarks, Git promotion/rollback, private
    container registry, GitFlow and signed package distribution.
  - [ ] **89I — Verify and roll out.** Add the test matrix and loopback
    rehearsals for every new channel; run all gates; roll out in the order
    Master contracts/registry → Master services → peer services → event bus →
    model plane → collaboration → execution → self-improvement → dashboard.
  - **DoD**: every new channel has a contract row, a canonical envelope, a
    refusal test and a loopback rehearsal; no channel carries authority and
    knowledge together; no personal page enters a shared corpus; `make
    contract-test`, `make test-all`, `make ci`, both bundle verifications,
    `make drift-check` and `make -C gospark ci` are green; every live leg is
    `DoD: confirm: user`.

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
