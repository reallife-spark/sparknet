---
title: sparknet Plan
updated: 2026-11-01
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
