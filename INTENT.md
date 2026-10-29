---
title: sparknet — INTENT
role: fabric
template: true
intent: design-contract
updated: 2026-10-29
---

# sparknet — INTENT

This page states how the fabric is meant to work and what must remain true as it
changes. It is not a plan, a runbook or a status page. `PLAN.md` is the work
order; `MISSION.md` is why the fabric exists; `AGENTS.md` is the operating
charter.

## Why two roles

The fabric deliberately separates **verification** from **authority**.

- A **peer** serves its own vault and inference, holds its own identity key, and
  verifies what the Master signed. It never holds the operational key.
- A **Master** is a peer that won an election. It additionally holds the
  operational key, authors the registry and signs approvals.

That asymmetry is the product. A peer with the full capability vocabulary but no
operational key can read, infer and serve; it cannot grant, revoke or escalate.

## Invariants

1. **The contract is the single source of truth.** Overlay addressing,
   capabilities, identity, ports and the guard conversation are defined in
   `contracts/`; a role does not restate them.
2. **Cross-role changes are atomic.** A change to anything a peer depends on is
   one commit touching `contracts/`, both roles and the shared implementation,
   followed by `make contract-test`.
3. **One authorization implementation.** `shared/sparknet-authz.py` signs and
   verifies; neither role carries a copy. A second copy can drift and silently
   stop validating.
4. **A role subvault is not a deployment.** A node needs the contract, the
   shared implementation and its role. `make bundle` assembles what a deployment
   actually needs; `bundle-verify` proves it runs elsewhere.
5. **Vaults are per-role and per-node.** Cross-cutting knowledge belongs in the
   fabric vault; role knowledge belongs in that role's vault. Filing into the
   wrong vault is invisible because the write succeeds.
6. **No secrets in a vault.** Key material lives in a node's state directory at
   mode 0700/0600 and is referenced by path only.
7. **Templates are blank slates.** `MISSION.md` and `INTENT.md` describe durable
   intent. Live hosts, keys, root ids, dates and deployment status belong in
   `manifests/`, `plans/`, `MEMORY.md` and `log.md`.

## First deployment

A fresh role deployment is expected to run from its first boot:

1. `make env-init` writes the vault `.env` and category skeleton.
2. `make user-init` creates the user key and fills `00_System/user.md` once.
3. `make validate` proves the role's required files, environment and manifests.
4. `make wiki-preflight` proves the vendored wiki skills resolve this vault.
5. An AI session reads `AGENTS.md`, `MISSION.md`, `INTENT.md`, `MEMORY.md` and
   today's session file before acting.

Nothing about the deployment is hand-edited into these identity pages. A new node
inherits the role's intent, not another node's history.

## AI operating model

- `AGENTS.md` defines the operating rules and wins on conflict.
- `MISSION.md` defines purpose and success.
- `INTENT.md` defines invariants and expected behaviour.
- `MEMORY.md` is tiny standing state; `log.md` is the append-only audit trail.
- Plans hold the work order; identity pages do not track live progress.
- Agents must not claim live verification of network, kernel, signer or systemd
  behaviour from a development host.

## Change intent

New work gets a new plan step, not a rewrite of this page. Change `INTENT.md`
only when the design contract itself changes, and change both roles in the same
commit when the change touches anything a peer depends on.

## What this page is not

It is not a runbook, not a deployment record, not a status page and not a
substitute for the contract. If a statement here contradicts `AGENTS.md` or
`contracts/`, those win and this page is wrong.
