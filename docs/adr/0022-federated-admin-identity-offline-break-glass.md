# 0022 — Federated admin identity with an offline break-glass path

## Status

Accepted (2026-11-16). Implementation is a new `PLAN.md` step. This ADR
supersedes, for the admin identity question only, the "admin-only-on-master"
enforcement in `ADMIN_FEDERATION_DESIGN.md` and the "Master is admin-only…
never by a second account" rule in `contracts/webui-surface.md`.

## Context

The fabric's adopted admin model was **signed federation**: each peer owns its
own Open WebUI users, a peer's administrator is a machine service account, and
the Master supervises peers through Master-signed `admin-supervise` requests on
the bridge (`ADMIN_FEDERATION_DESIGN.md`). The human administrator existed only
on the Master.

The operator now needs a different property:

- the admin account must work on **every node**, not only the Master;
- the admin must reach every node **from the Master**;
- an **isolated node** that cannot reach the Master or the other nodes must
  still accept the admin locally, with full local admin, so the node can be
  repaired and rejoined;
- nodes stay **local-first**; an unreachable Master is acceptable;
- the admin has **full Open WebUI admin** on that node (users, roles,
  approvals, Knowledge/KB, chats, models, prompts/tools/functions, settings,
  files/uploads), not only the eleven signed admin verbs.

A Master-hosted identity provider alone cannot satisfy the isolated-node
requirement: Open WebUI's OIDC login is an online code exchange, and a node cut
off from the Master cannot complete it. A shared WebUI password on every node
would satisfy the requirement but would reintroduce the one thing the fabric's
authority model exists to avoid: a network-wide shared secret. The design needs
two authentication paths — federated online and local offline — sharing one
human identity.

Open WebUI v0.13 provides the levers: OIDC/OAuth, trusted-header authentication
with role and group headers, a local login form that can stay enabled alongside
those, and role management. The node already has an nginx ingress in front of a
loopback-only Open WebUI; the Master already has an overlay-only admin surface.

## Decision

Adopt a **Master-hosted OIDC identity provider** and put a **node auth gateway**
in front of every Open WebUI. The normative details live in
`contracts/sso-identity.md`; this ADR records the shape.

1. **Identity.** Human identities are held by a Master-hosted OIDC provider and
   are separate from node identities (`contracts/identity-schema.json`). Groups
   `sparknet-admins` and `sparknet-users` are the baseline role truth. The
   deploy-time Open WebUI admin account becomes a locked automation account used
   only by the admin agent, bridge and provisioner; no human logs in as it.
2. **Online path.** A node auth gateway performs OIDC against the Master IdP,
   maps the admin group to `admin`, strips any caller-supplied identity headers
   and injects `X-User-Email` / `X-User-Role` to a loopback-only Open WebUI.
   The Master admin proxy authenticates the operator once and forwards a
   short-lived, mTLS-protected assertion to the target node's gateway so one
   origin reaches every node.
3. **Offline path.** The admin holds a short-lived client certificate. On an
   isolated node the same gateway verifies it against the fabric admin CA and
   injects `admin`, with no IdP, no Master and no network. Regular users keep the
   local login form as their offline fallback; those accounts are per-node and
   are not synchronized.
4. **Role truth.** IdP groups are the baseline. A signed `admin-supervise`
   `set_user_role` may write a per-node override (0600 under the node state
   dir). The effective role is the override when present, otherwise the IdP
   group. A disagreement is recorded, surfaced and held for a human, never
   silently overwritten.
5. **Offline repair.** Changes made on an isolated node are tagged
   `offline-repair`, signed with the node's identity key, spooled and reported
   on reconnect. They win for that node's local state; they never propagate
   authority or user grants, and any grant/revoke/widen is held for a human.
6. **Retained surface.** The signed `admin-supervise` console remains for
   automated, bulk and audited actions. Direct login and the signed console are
   two paths to the same node administration, not two authorities.

## Consequences

- **Easier:** one admin identity on every node; one origin from the Master; the
  admin can repair an isolated node with full local admin; no shared WebUI
  password; the IdP becomes the single place to grant or revoke online access.
- **Harder:** a new identity service and a per-node auth gateway must be built,
  deployed and tested; the node ingress becomes security-critical; client
  certificates must be issued, rotated and revoked; the Master carries more
  availability weight for online logins.
- **Forbidden:** a shared admin password across nodes; a shared user database;
  reaching Open WebUI except through the auth gateway; trusting an
  `X-User-*` header from a caller; propagating offline-repair authority to other
  nodes; treating admin/auth data as knowledge.
- **Accepted loss:** per-node Open WebUI state (chats, preferences) and offline
  local user accounts are not synchronized. "The admin works everywhere" means
  identity, role and access, not a shared per-node database.
- **Reversed security property:** a human admin may now log in on a peer, and a
  direct login is a second path to node administration. Compensating controls
  are the gateway-only ingress, header stripping, short-lived client certs,
  audit and the retained signed console. This must be stated, not hidden.
- **Local-first preserved:** with no Master, the admin still gets in offline and
  users can still use a local credential. The node loses federated identity, not
  usefulness.
- **Live boundary:** code, contracts and tests are provable on the development
  host. Overlay reachability, mTLS, the IdP, systemd and the browser surfaces are
  target-host checks and stay `DoD: confirm: user`.

## Alternatives

- **Shared admin password on every node** — rejected: a network-wide shared
  secret; one compromised node exposes every node.
- **OIDC only** — rejected: cannot authenticate an isolated node.
- **Signed `admin-supervise` only** — insufficient: it does not provide direct
  login or the full Open WebUI admin set the operator asked for.
- **A shared Open WebUI database** — rejected: a shared user database; it
  violates the per-node authority boundary and the knowledge/authority split.
- **An external IdP** — rejected for now: it delegates the fabric's identity
  root outside the Master, contradicting "the Master supplies authority". A
  later ADR may revisit it.

## References

`contracts/sso-identity.md` · `contracts/webui-surface.md` ·
`contracts/identity-schema.json` · `contracts/ports.json` ·
`contracts/knowledge-flow.md` · `ADMIN_FEDERATION_DESIGN.md` ·
`INTENT.md` invariant 10 · `docs/adr/0014-keep-authz-behind-one-facade.md`
