---
title: sparknet — MISSION
role: fabric
template: true
updated: 2026-10-31
---

# sparknet — MISSION

sparknet is a two-role fabric for local AI nodes. A **peer** is the user's node:
it runs local chat, agentic planning and building, a private vault and a
self-healing knowledge loop. An elected **Master** holds the one key able to
authorise privileged action and supplies scoped fabric knowledge. The fabric
exists so authority is explicit, verifiable and revocable, and so useful local
AI does not require trusting a network position or a capability label.

`INTENT.md` is the design contract; `AGENTS.md` is the operating charter and
wins if the two ever disagree.

## Scope

- **In scope**: the cross-role contract (`contracts/`), the one signed
  authorization implementation (`shared/`), both role implementations, their
  vaults, deployment bundles, verification gates, the Qdrant vector store, and
  the consented uplift + same-family distillation pipeline.
- **Out of scope**: runtime services owned by one role, domain knowledge that
  belongs in another vault, and secrets. Keys live in a node's state directory,
  never in a vault and never in git.
- **Out of scope**: treating a role subvault as a deployment. A peer cannot
  verify a signature without the contract and the shared implementation, so a
  bare role copy must fail validation rather than pretend to work.

## Success

This vault should answer, with citations:

1. What can the Master do that no peer can, and by what mechanism?
2. Why can a peer verify an authorization but never create one?
3. How does a user get chat, agentic planning/building and a private KB?
4. How does knowledge reach a peer, and what may it never carry?
5. What must change atomically, and which behaviours are proven by tests,
   which only on a real deployment, and which are still specification?

The fabric succeeds when every privileged action has one visible path through
the Master, a revoked peer becomes inert without its cooperation, and a peer
remains useful for reading, inference, chat, planning and its own vault even
with no authority at all.
## Non-goals

- A single monolithic node, or authority by vocabulary alone.
- Sharing personal pages, live host state, keys or personal material.
- Replacing a role's own manual, plan or runbook with this page.

## Constraints

- One contract is the single source of truth; cross-role edits are atomic.
- One signed-authorization implementation, used by both roles, never copied.
- Vaults hold knowledge; state directories hold secrets. Knowledge and
  authority never share a channel; see `contracts/knowledge-flow.md`.
- Live network, kernel, signer or admin claims are dated and host-specific.
