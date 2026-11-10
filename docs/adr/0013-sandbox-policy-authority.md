# 0013 — Sandbox policy authority and recreation

## Status

Accepted. This records the model decision, not a deployment: the
`sandbox-supervise` capability and the `/sandbox/*` route remain inert (peer
PLAN 20E).

## Context

ADR-0012 defines the OpenShell execution sandbox. Two questions were left
ambiguous:

1. `contracts/sandbox-schema.json` lets a Master-signed `policy-update` apply a
   policy, while ADR-0012 said "approvals stay local" and "the Master cannot
   approve on the user's behalf."
2. A policy change to filesystem, Landlock or process settings cannot be
   applied live, but the contract did not say who orchestrates recreation.

Both questions decide whether the Master or the local approver is the final
authority over a sandbox's policy. That is a security boundary, not a wording
detail.

## Decision

- **A Master-signed `policy-update` is authority, not a proposal.** The peer
  executes it when the request is valid, the `sandbox-supervise` grant is
  present, and the peer's local execution whitelist accepts it. It does not
  require a second local approval. The local whitelist may still refuse an
  otherwise valid request.
- **A workload-generated `policy proposal` is not authority.** It stays inert
  until the sandbox user approves it. For a session sandbox the approver is the
  sandbox user; for a service sandbox the approver is not yet contracted. The
  Master cannot approve or reject a proposal on the user's behalf.
- **The two paths are independent.** A Master signature on a `policy-update` is
  not an approval of a workload proposal, even when the two describe the same
  change. A local approval is not a capability grant. Neither path can promote
  the other.
- **A policy change that cannot be applied live is refused.** Network-only
  changes may apply live. Filesystem, Landlock and process changes are refused
  with `policy-refused` while the sandbox is running.
- **Recreation is a separate sequence.** The caller issues `stop`, `delete` and
  `create` as separate signed requests. This contract has no `recreate` action.
  `delete` removes the sandbox record and compute resource; it never deletes the
  vault mount.

## Consequences

- The Master can supervise policy within the peer's local whitelist without a
  local prompt. The sandbox user retains approval of workload-initiated changes
  in a session sandbox.
- A caller that needs a non-live change must orchestrate three actions and
  accept the gap between delete and create. The peer never destroys and
  recreates a sandbox implicitly.
- A future `recreate` action would be a new contract decision, not an
  interpretation of `policy-update`.
- A service sandbox's mount and approver remain an open edge for peer PLAN 20F;
  this ADR does not extend the session-sandbox approver to it.
