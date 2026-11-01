---
title: sparknet — INTENT
role: fabric
template: true
intent: design-contract
updated: 2026-10-31
---

# sparknet — INTENT

How the fabric is meant to work and what must remain true as it changes. It is
not a plan, a runbook or a status page. `PLAN.md` is the work order;
`MISSION.md` is why the fabric exists; `AGENTS.md` is the operating charter.

## Why two roles

The fabric separates **usefulness** from **authority**.

- A **peer** is the user's node: local chat, agentic planning and building, its
  own vault, per-user KBs and self-healing. It holds an identity key and verifies
  what the Master signed; it never holds the operational key.
- A **Master** is a peer that won an election. It additionally holds the
  operational key, authors the registry, signs approvals and supplies scoped
  fabric knowledge.

That asymmetry is the product. A peer with the full capability vocabulary but no
operational key can read, infer, chat and build; it cannot grant, revoke or
escalate. The Master supplies authority and knowledge, not control.

## Invariants

1. **The contract is the single source of truth.** Overlay addressing,
   capabilities, identity, ports, the guard conversation and the knowledge
   channel map are defined in `contracts/`; a role does not restate them.
2. **Cross-role changes are atomic.** A change to anything a peer depends on is
   one commit touching `contracts/`, both roles and the shared implementation,
   followed by `make contract-test`.
3. **One authorization implementation.** `shared/sparknet-authz.py` signs and
   verifies; neither role carries a copy.
4. **A role subvault is not a deployment.** A node needs the contract, the
   shared implementation and its role; `make bundle` assembles them and
   `bundle-verify` proves the result runs elsewhere.
5. **Vaults are per-role and per-node.** Cross-cutting knowledge belongs in the
   fabric vault; role knowledge belongs in that role's vault; a user's knowledge
   belongs in their own `peer-<id>` vault/KB. Filing wrongly is invisible
   because the write succeeds.
6. **No secrets in a vault.** Key material lives in a node's state directory at
   mode 0700/0600, referenced by path only.
7. **Templates are blank slates.** MISSION/INTENT describe durable intent. Live
   hosts, keys, root ids, dates and deployment status belong in `manifests/`,
   `PLAN.md`, `MEMORY.md` and `log.md`.
8. **Knowledge and authority stay separate.** A peer answers from its vault, its
   user's KB, an accepted RFI answer, a reconciled share or the build-time
   context pack. Registry entries, approvals, telemetry and admin responses are
   never knowledge. The map is `contracts/knowledge-flow.md`.
9. **Every AI instance loads one context.** `CONTEXT.md` is generated from the
   identity pages and the knowledge-flow map; OpenCode, Open WebUI, per-user
   models and the vLLM/MASTERSPIKE precontext load it. It is never hand-edited.
10. **Local-first is the default.** With no Master, chat, planning, building,
    vault reads and self-healing keep working. The node loses authority and
    external knowledge, not usefulness.

## First deployment

1. `make env-init` writes the vault `.env` and category skeleton.
2. `make user-init` creates the user key and fills `00_System/user.md` once.
3. `make validate` proves the role's files, environment and manifests.
4. `make wiki-preflight` proves the vendored skills resolve this vault.
5. An AI session reads `CONTEXT.md`, `AGENTS.md`, `MISSION.md`, `INTENT.md`,
   `MEMORY.md` and today's session file before acting.

Nothing about the deployment is hand-edited into these identity pages. A new
node inherits the role's intent, not another node's history.

## AI operating model

- `AGENTS.md` defines the rules and wins on conflict.
- `MISSION.md` defines purpose and success.
- `INTENT.md` defines invariants and expected behaviour.
- `MEMORY.md` is tiny standing state; `log.md` is the append-only audit trail.
- Plans hold the work order; identity pages do not track live progress.
- Agents must not claim live verification of network, kernel, signer or systemd
  behaviour from a development host.

## Change intent

New work gets a plan step, not a rewrite. Change `INTENT.md` only when the
design contract changes; a cross-role change is one commit. It is not a
runbook, deployment record or status page. If it contradicts `AGENTS.md` or
`contracts/`, those win and this page is wrong.
