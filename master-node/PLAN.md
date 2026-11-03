---
title: sparknet master-node Plan
updated: 2026-11-01
current: 24
---

# sparknet master-node — Active Plan

> Single source of truth for Master work. The `current:` cursor names the step
> being worked. Write this file back **immediately** on every advance and append
> the transition line to `00_System/log.md`. Completed steps 1–9, 13–21 are in
> `plans/archive/MASTER_BUILD_PLAN_FULL_2026-10-30.md`; `plans/MASTER_BUILD_PLAN.md`
> is a symlink to this file for old links.

## Status Legend

- `[ ]` not started / in progress
- `[x]` complete — DoD verified
- **DoD** — the check that proves the step is done; `DoD: confirm: user` when a
  human must confirm
- `current: N` — step being worked; `current: done` — terminal

## Closed steps

| Step | Scope | Evidence |
|---|---|---|
| 1–9 | key/registry, schema, CLI, overlay, approvals, distribution, intake, KillSwitch, scheduler | archived plan and `log.md` |
| 13–21 | consensus, shared election, role inversion, parity, signer, admin surface, honest verification, signer liveness, console | archived plan and `log.md` |

## Step 10 — Share ratification service

- [ ] **Step 10** — Accept an accepted share only when the peer's grant verifies
  against the signed registry, then issue a Master-signed, time-boxed
  ratification. The signer signs `sign-share-ratification`; no key is held here.
  - **DoD**: signed accept/refuse envelopes, deadline and flag-retained fields,
    duplicate/expired/unknown-grant refusals, tests through the real signer, a
    staged `4203` listener. Live listener and a peer round trip are
    `DoD: confirm: user`.
  - **Status**: code complete 2026-10-29. On 2026-10-31 a signed multi-key
    listener and a durable human-approval queue were added; the listener queues
    but never signs, and only `--approve/--refuse` reaches the isolated signer.
    Tests cover key ring, key/node binding, restart and no-auto-ratify. No unit
    is enabled; a live peer round trip remains `DoD: confirm: user`. The
    three-node preparation is in `docs/share-ratification-live.md`; the unit is
    rendered, never enabled on the pair. No third host exists yet. On agx32 the
    unit is installed **disabled/inactive** (state 0700, key dir peer-only,
    port 4203 unbound) as the two-node posture.

## Step 11 — Evidence capture and review repository

- [ ] **Step 11** — Validate one share-evidence event, write it under
  `evidence-repo/events/`, record its digest in the signed ledger and commit it.
  - **DoD**: hashed event, signer-recorded ledger block, git commit, `verify_repo`
    against the ledger, missing/unrecorded file discrepancy; tests green.
  - **Status**: code complete 2026-10-29; live repository/telemetry consumption
    is `DoD: confirm: user`.

## Step 12 — Review agents and trust decisions

- [ ] **Step 12** — Produce a finding for each evidence event without modifying
  the evidence, and emit a reversible signed trust belief. Never write a registry
  or a grant.
  - **DoD**: signed `trust_level_changed` with `reversible`/`flag_preserved`,
    invalid levels refused, evidence read-only, tests green.
  - **Status**: code complete 2026-10-29; live review round trip is
    `DoD: confirm: user`.

## Step 22 — Scoped knowledge responder and AI context

- [x] **Step 22** — Make the Master supply scoped fabric knowledge to a user's
  peer without becoming a general oracle:
  - [x] **22A — Context.** Generate `CONTEXT.md` and load it in the Master's
    OpenCode terminal and admin surface; never expose the peer context as the
    Master's.
  - [x] **22B — Responder.** Consume queued RFI requests, search only the
    allow-listed fabric corpus, enforce the request's `scope`, return an empty
    answer when nothing matches, sign through the isolated signer and deliver
    through the existing RFI answer transport.
  - [x] **22C — Knowledge intake.** Record the answer/response in the ledger and
    telemetry as evidence; never treat it as authority or as a peer's vault read.
  - **DoD**: an end-to-end loopback test (peer request → `8090` intake → queue →
    responder → signed answer → peer guard → `01_Inbox/`), scope/empty/revoked
    refusals, `make context-check`, `make render`, `make contract-test`,
    `make test-all`; live units and cross-node delivery are
    `DoD: confirm: user`.
  - **Status: complete and live-verified on agx32 2026-10-31.** 8090 intake and the responder run; a real peer RFI was answered and installed; the admin console `feed`/`users` paths work; registry sequence 2 was re-signed and delivered. Master tests and bundle verify pass.

## Step 23 — Qdrant Master store, uplift intake and distillation

- [x] **Step 23** — Run the Master's Qdrant-backed 4223 store, receive consented
  uplift on 8091, and operate the same-family distillation scaffold.
  - [x] **23A — 4223.** `services/sparknet-vector-serve.py` loads
    `scripts/sparknet-vector.py`; only `sparknet-fabric` and
    `sparknet-shared` are served. Local tests pass.
  - [x] **23B — Uplift intake.** `services/sparknet-uplift-intake.py` verifies
    overlay source, node signature, `model-uplift`, freshness and nonce, then
    stores inventory, traces, snapshots and KV manifests. It holds no key.
  - [x] **23C — Distillation.** `services/sparknet-distill.py` builds a
    consented, redacted dataset, refuses a failed doctor, evaluates a candidate
    and can sign a `distillation_run` through the isolated signer.
  - [x] **23D — Live.** Qdrant `v1.20.0` on agx32; registry sequence 7 grants
    `model-uplift` and delivered 200; 8091 intake mirroring 41 inventory
    records; four agx64 snapshots uploaded and one restored (40 points); a real
    Qwen2.5-7B→Qwen2.5-1.5B LoRA run was signed (`run-20261101T101033Z-…`) and
    its model card published. Raw vLLM KV capture remains open (root 81H).
  - **DoD**: master suite green; live legs `DoD: confirm: user`.

## Step 24 — Master memory control and read-through

- [ ] **Step 24** — Let the Master govern fleet memory without a mirror:
  - [x] **24A — Capability and actions.** `memory-supervise` is a sensitive
    Master-issued capability; `memory_status`, `memory_policy_set`,
    `memory_read` and `memory_purge` are signed admin actions with fields inside
    the canonical projection.
  - [x] **24B — Peer execution.** The bridge verifies the signature, the target
    and `memory-supervise`, then forwards to the local Python gateway; the
    content is transient and the peer audits it.
  - [x] **24C — Console posture.** The Master console carries a read-only Memory
    menu and the admin console composes the memory verbs; no content mirror is
    stored.
  - [x] **24D — Project memory.** The shared `06_Projects` lifecycle and memory
    bundle commands work in the Master role vault; reports are signed by the
    operator, not the Master AI.
  - **DoD**: `make test-master`, `make test-admin-supervise`,
    `make contract-test`, `make context-check`, `make bundle-verify ROLE=master`;
    live `memory_status` and an on-demand content read are
    `DoD: confirm: user`.
  - **Status: local implementation complete 2026-11-02.** Code, tests, contracts and both bundle verifications pass; live node/browser legs are `DoD: confirm: user`.

## Next

`current:` moves one step at a time, and only after the DoD is verified.
Peer work stays in `../peer-node/PLAN.md`; fabric work in `../PLAN.md`.
