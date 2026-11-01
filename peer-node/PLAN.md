---
title: sparknet peer-node Plan
updated: 2026-10-31
current: done
---

# sparknet peer-node — Active Plan

> Single source of truth for multi-step work. The `current:` cursor names the
> step being worked. Write this file back **immediately** on every advance and
> append the transition line to `00_System/log.md`. Completed steps 1–10 are in
> `plans/archive/PEER_PLAN_FULL_2026-10-26.md`; do not copy their history back.

## Status Legend

- `[ ]` not started / in progress
- `[x]` complete — DoD verified
- **DoD** — the check that proves the step is done; `DoD: confirm: user` when a
  human must confirm
- `current: N` — step being worked; `current: done` — terminal

## Closed steps

| Step | Scope | Evidence |
|---|---|---|
| 1–10 | subvault, container, grants, bridge, Open WebUI, conversation passing, MASTERSPIKE, sharing, AI stack, exposed/firewalled stack | archived plan and `log.md` |

## Step 11 — Per-user knowledge vaults (`peer-<user_id>`) and user KBs

- [x] **Step 11** — Every approved Open WebUI user gets a copy of the
  `peer-node` knowledge-vault slice at `/srv/sparknet/knowledge/peer-<user_id>/`,
  created on `pending` → `user`, connected to a KB they own and grow.
  - **DoD**: (1) the provisioner watches `GET /api/v1/users/` with the node admin
    token and records state under `/srv/sparknet/knowledge/.state/`; (2) the
    slice excludes `.state/`, `blockchain/`, `services/`, `scripts/`,
    `container/`, `configs/`, `tests/`, `manifests/`, `.git/` and the template
    `.env`; (3) the KB is created with a `read` grant to the user, embeds the
    vault markup and is the default model's `meta.knowledge`; (4) a digest pass
    re-embeds changed pages; (5) `master-<id>` stays inactive on a peer;
    (6) tests, `contract-test`, `lint` and `bundle-verify` are green.
  - **Status: complete 2026-10-31.** A disposable live account
    (`026a5abd-659f-44dc-acba-b9c6a409404f`) moved `pending` → `user` after
    Master approval; the provisioner created 26 files and KB
    `6c6198bf-2462-4c1c-964c-f2349fe1485f`; deletion removed the user, vault,
    KB/model and state record. Tests cover the slice, KB grant/model wiring and
    digest path; `make test-all` is green.

## Step 12 — Node admin agent: auth events and pending-signup supervision

- [x] **Step 12** — A local, stdlib-only agent turns the node's Open WebUI into
  an approval-mediated surface the Master can supervise.
  - **DoD**: signup enabled with `DEFAULT_USER_ROLE: "pending"`; the agent
    appends normalised auth events to a 0600 spool and registers its webhook;
    the node admin is a machine service account; `tests/test_admin_agent.py`
    proves the spool, allow-list, webhook body and pending gate; `manifests/
    ai-stack.json` records the posture; gates green.
  - **Status**: code complete 2026-10-12; live on the retired pair, not yet on
    the current pair.

## Step 13 — User AI context, knowledge loop and self-healing

- [x] **Step 13** — Make the peer a coherent user AI node on `agx64`:
  - [x] **13A — Context.** Generate `CONTEXT.md` from the identity pages and
    `../contracts/knowledge-flow.md`; load it in OpenCode, the Open WebUI
    structure KB, per-user KBs/models, the vLLM/MASTERSPIKE precontext and the
    admin terminal. `make context-check` is a gate.
  - [x] **13B — Chat/plan/build surface.** The local model is the per-user chat
    default; `plan` and `build` are selectable agent models; `MODEL_FILTER_LIST`
    names the same surface as `manifests/agent-models.json`.
  - [x] **13C — Knowledge request.** Add a peer RFI request client and a
    `vault.rfi` bridge tool. A request names an explicit scope; it never
    grants or widens anything.
  - [x] **13D — Knowledge intake.** A Master answer installs in `01_Inbox/`,
    records `inbox_acceptance`, is sanitized when untrusted, and is indexed
    into the user's KB only after acceptance.
  - [x] **13E — Self-healing.** `make vault-health` diagnoses; `make vault-heal`
    repairs only derived/safe state; `docs/self-healing.md` states what is
    report-only and what is gated; the timer is staged.
  - **DoD**: `make context-check`, `make vault-health`, the RFI loop test, the
    context-propagation test and the peer suite are green; `make bundle-verify
    ROLE=peer` passes; `agx64` live legs are `DoD: confirm: user`.
  - **Status: complete and live-verified on agx64 2026-10-31.** Context is in WebUI RAG, per-user KBs, vLLM precontext and OpenCode; `vault.rfi` completed a real request→answer→inbox round trip; telemetry/checkpoint/self-healing timers run; peer suite and bundle verify pass.

## Next

`current:` moves one step at a time, and only after the DoD is verified.
Master-side work stays in `../master-node/PLAN.md`; fabric work in `../PLAN.md`.
