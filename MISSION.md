---
title: sparknet — MISSION
role: fabric
template: true
updated: 2026-10-29
---

# sparknet — MISSION

sparknet is a two-role fabric for local AI nodes: an implemented **peer** that
serves its own vault and inference, and an elected **Master** that holds the one
key able to authorise privileged action. The fabric exists so that authority is
explicit, verifiable and revocable rather than implied by network position or a
capability label.

Read `INTENT.md` for the design contract behind this mission. `AGENTS.md` is the
operating charter and wins if the two ever disagree.

## Scope

- **In scope**: the cross-role contract (`contracts/`), the one signed
  authorization implementation (`shared/`), both role implementations, their
  per-role vaults, deployment bundles, verification gates, and the knowledge
  needed to change any of them without breaking the other role.
- **Out of scope**: runtime services owned by a single role, domain knowledge
  that belongs in another vault, and secrets. Keys live in a node's state
  directory, never in a vault and never in git.
- **Out of scope**: treating a role subvault as a deployment. A peer cannot
  verify a signature without the contract and the shared implementation, so a
  bare role copy must fail validation rather than pretend to work.

## Success

This vault should answer, fluently and with citations:

1. What can the Master do that no peer can, and by what mechanism?
2. Why can a peer verify an authorization but never create one?
3. How does a fresh node get from a bundle to a verified, anchored deployment?
4. What must change atomically when a cross-role contract changes?
5. Which behaviours are proven by tests, which are proven only on a real
   deployment, and which are still specification?

## Success for the fabric itself

The fabric is successful when every privileged action has one visible path
through the Master, a revoked peer becomes inert without its cooperation, and a
node remains useful for reading, inference and its own vault even when it has no
authority at all.

## Non-goals

- Being a single monolithic node.
- Granting authority by capability vocabulary alone.
- Shipping live host state, keys or personal material in a template.
- Replacing a role's own manual, plan or runbook with this page.

## Constraints

- One contract is the single source of truth; cross-role edits are atomic.
- One signed-authorization implementation, used by both roles, never copied.
- Vaults hold knowledge; state directories hold secrets.
- Claims about live network, kernel, signer or admin behaviour are dated and
  host-specific, never generalised from a development host.
