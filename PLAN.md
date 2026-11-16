---
title: sparknet Plan
updated: 2026-11-16
current: 113
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
| 90–110 | Phase 8 remediation through Qwen3-2507 main/peer stack | `_archives/PLAN_FULL_2026-11-16.md` |
## Step 111 — Daily auto-distillation
- [ ] **Step 111** — Distill on agx32 daily or on request from the 30B main/teacher; export the 4B GGUF; sign/upload to agx64; sync the agx64 student copy daily/on request when idle; benchmark and promote/rollback.
  - **DoD**: consented dataset, 4B LoRA at 16k, merge/GGUF, signed upload, idle-aware copy, candidate benchmark, operator promotion, timer/manual trigger, docs/tests/gates green.
  - **Status 2026-11-14/15 — BLOCKED (external GPU).** Keyless 16k bundle
    `sparknet-distill-e69b5e6f6247110d-20261115T024212Z.tar.gz` built; external
    Dockerfile, sign/8091 and idle sync implemented; agx32 live (Qdrant 1024, cron 03:15).
    `raxxaramd` is online as a general x86 VM/build node (`.107` WiFi, Tailscale boot verified,
    trainer key), but its GTX 1650M 4 GB/no CUDA cannot run 16k; agx64 llama.cpp is full-finetune, not QLoRA.
## Step 112 — Third-member admission / join ceremony

- [x] **Step 112** — Add the schema 1.3 2 -> 3 admission path so a third peer can
  join the live pair without re-electing the Master, then deploy it on `vmx`.
  - [x] **112A — Consensus rule.** `verify_root` accepts one strict superset:
    parent exactly two, child exactly three, Master and `master_pubkey`
    unchanged, existing member records byte-identical, new keys distinct, no
    removal proof, schema 1.3+, `admission_*` refusals.
  - [x] **112B — Exchange and adoption.** `serve --admission` verifies the child
    at the seal; `member --trust/--as-member`, `accept --as-member`, and a
    non-master member writes only `trust_root`; ordinary election losers still
    write nothing.
  - [x] **112C — Scripts, tests, contracts.** Peer script/Makefile flags,
    admission unit/cross-process tests, consensus/identity contracts and the
    role-transition/deployment runbooks.
  - [x] **112D — Live join.** VM, node `0003` keys, 2 -> 3 admission, 3 -> 3
    key-rotation re-formation, registry sequence 12, overlay/guard/share and a
    CPU llama.cpp + Open WebUI stack are live; `make ci` green.
  - **DoD**: `make ci`, `make contract-test`, `make test-all`, `make validate`
    and `make context-check` green; the admission code path is covered by
    tests that fail on a Master change, existing-member rewrite, duplicate key,
    removal proof or schema 1.2 child. Live join is separately confirmed.
  - **Status 2026-11-15 — COMPLETE.** Schema 1.3 admission, general member
    adoption, 3 -> 3 WG rotation, root `9157113f…` epoch 4, registry sequence
    12, guard/share/overlay and a CPU llama.cpp + Open WebUI stack on 0003 are
    live; `make ci` green and the old WG keys are no longer active.
## Step 113 — Federated admin identity and offline break-glass

- [ ] **Step 113** — Make one admin identity work on every node, online from the
  Master and offline on an isolated node, with full Open WebUI administration
  and no shared password or shared user database. Decision and normative rules:
  `docs/adr/0022-federated-admin-identity-offline-break-glass.md` and
  `contracts/sso-identity.md`.
  - [x] **113A — Contract and decision.** ADR 0022; `contracts/sso-identity.md`;
    amend `webui-surface.md`, `ADMIN_FEDERATION_DESIGN.md`, `INTENT.md` invariant
    10 + 15, `identity-schema.json` human identity, `ports.json` (8181, 9443),
    `knowledge-flow.md` rows and `contracts/README.md`.
    - **DoD**: `make context-check`, `make validate`, `make contract-test`,
      `make render-check` green with contract/doc changes only. — **met
      2026-11-16.**
  - [x] **113B — Master IdP and per-node clients.** A Master-hosted OIDC
    provider on 9443 with `sparknet-admins` / `sparknet-users`; one confidential
    client secret per node, issued through the signed deployment path and stored
    0600. Resource measurement on `agx32` before pinning the product.
    - **DoD**: OIDC discovery over the overlay; `make keys-check`; no secret in
      the tree; memory measured and recorded. — **met 2026-11-16.** Dex
      `v2.41.1` + lldap `v0.6.3` live on agx32; discovery verified; Dex
      10.8 MiB, lldap 9.6 MiB; clients for 0001/0002/0003; redirect URIs
      8092/8182.
  - [x] **113C — Node auth gateway (online).** OIDC at the node gateway; strip
    caller `X-User-*`; inject verified `X-User-Email` / `X-User-Role`; Open
    WebUI loopback-only; trusted-header auth in the compose config.
    - **DoD**: SSO admin login on a node; direct Open WebUI refused; forged
      header stripped; local login still works; tests. — **met 2026-11-16.**
      Per-node oauth2-proxy on loopback 4180; OIDC login completes at 8092 and
      the peer 8182 ingresses; the admin identity gets 200. The user-only test
      identity gets `admin-required` 403. mTLS still returns 200.
  - [x] **113D — Offline break-glass.** Admin CA and short-lived client
    certificate; the gateway verifies chain, expiry and revocation, then injects
    `admin`; no IdP or Master needed.
    - **DoD**: with the Master unreachable, a client-cert login gets full local
      admin; no cert, bad cert, expired and revoked are refused; tests. —
      **met 2026-11-16.** With Dex and the Master SSO ingress stopped, direct
      mTLS to 0002 and 0003 returned 200; no certificate returns 401; the
      refusal tests cover bad/expired/revoked.
  - [x] **113E — Role truth and overrides.** IdP group baseline; per-node
    `.state/admin-role-overrides.json` written only by signed `set_user_role`;
    effective-role precedence; `role-override-conflict` recorded and held.
    - **DoD**: IdP change propagates; signed override applies; conflict is
      recorded and surfaced, never silently overwritten; tests. — **met
      2026-11-16.** Dex logs the admin groups `[sparknet-admins
      sparknet-users]`; a user-only identity is refused by the admin ingress,
      while the admin identity gets 200. The override writer is live on the
      0002 bridge; the precedence/conflict tests pass.
  - [x] **113F — Master admin proxy.** One origin at 8092 (the existing 8088
    surface stays as rollback), registry-derived target allow-list, short-lived
    mTLS assertion to the node gateway, audit.
    - **DoD**: the admin reaches every node from the Master; arbitrary target
      URLs refused; assertion replay/expiry refused; tests. — **met 2026-11-16.**
      `/nodes/sparknet-node-0002/` and `/nodes/sparknet-node-0003/` return 200
      with the admin certificate; without it they return 401.
  - [x] **113G — Offline-repair reconciliation.** Node-signed `offline-repair`
    records; reconnect verification; local state preserved and flagged; no
    authority propagation.
    - **DoD**: simulated isolated repair signs, reconnects, is flagged; a record
      carrying a grant/key/registry change is refused; tests. — **met
      2026-11-16.** A 0002 record signed with the registry-attested node key was
      accepted by the Master reviewer (`accepted 1, applied false`); a record
      carrying `capabilities` was refused.
  - [ ] **113H — Gates and live rollout.** Deploy to `agx32` Master,
    `agx64` and `sparknet-node-0003`; verify online login from the Master, offline
    login with the Master unreachable, and repair/reconnect.
    - **DoD**: `make ci`, `make test-all`, `make contract-test`, `make lint`,
      `make validate`, `make keys-check`, `make shims-check`,
      `make bundle-verify` green; live legs `DoD: confirm: user`. — **live
      rollout and OIDC login met; signed bundle verification and a reboot
      check open.** `test-all` 683/1 skipped,
      lint/format/validate/contract/render/context/keys/shims/shellcheck green.
      `bundle-verify` still needs the release public key.
  - [ ] **113I — Gate-safe LLM proxy import.** The gate venv carries only
    `cryptography`, `pytest`, `ruff` and `PyYAML`; the proxy must stay
    importable without the web stack while the container entry point still
    builds the FastAPI app.
    - **DoD**: `tests/test_llm_engine.py` passes in a venv built from
      `requirements.txt` + `requirements-dev.txt`; `create_app()` and the
      `app` entry point still build the FastAPI app; `make ci` green; the
      published goagx root proxy matches the fabric root.
  - **Status 2026-11-16 — LIVE on agx32/agx64/sparknet-node-0003; signed
    bundle verification and a reboot-persistence check remain.** Dex `v2.41.1`
    and lldap `v0.6.3` are live on agx32; `sparknet-admins` / `sparknet-users`
    and `sparknet-admin` exist; per-node clients and redirect URIs are
    8092/8182. The admin client certificate (`sparknet-admin@sparknet.local`)
    logs into the Master SSO ingress 8092 and into the peer admin ingress 8182
    on 0002/0003; the Master `/nodes/` proxy returns 200 for both peers; without
    the certificate the same endpoints return 401. The existing user ingresses
    on 8181 are unchanged and return 200. The peer admin ingress binds the
    overlay and the node LAN address, never a wildcard. The auth gateway,
    Master proxy, Dex/lldap and the three ingress containers are persistent
    (user systemd units / compose restart policy). The 0003 CPU stack uses the
    CPU SSO overlay. A test offline-repair record from 0002 was accepted by the
    Master reviewer with `applied: false`; an authority-bearing record was
    refused. OIDC browser login via oauth2-proxy is live on all three nodes:
    the admin identity reaches 200 on 8092 and the peer 8182 ingresses; a
    user-only identity gets `admin-required` 403. The old 8088 surface was
    stopped after 8092 proved out, retiring the exposed rollback password.
    Still open: signed `bundle-verify` (release public key absent) and a
    reboot-persistence check. The signed `admin-supervise` console is retained
    for automated/bulk/audited actions.

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
