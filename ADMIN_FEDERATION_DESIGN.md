---
title: Sparknet admin federation — cross-node administration design
updated: 2026-10-12
status: design (adopted: vocabulary + signed transport; console and live deploy open)
---

# Sparknet admin federation

**Adopted in vocabulary and signed transport; console and live deploy open.**
This page records the operator decisions and the build plan for one capability:
a Master-side administrator who can see and supervise the Open WebUI users,
privileges and activity of **every node in the fabric**, while nobody can log
in as an administrator on a peer node. The capability name it needs
(`admin-supervise`) is **reserved and wired cross-role** (contracts +
`shared/sparknet-authz.py`, fabric Step 29 phase 2): the Master's signer
produces signed admin requests and the peer's bridge `/admin/*` route executes
them, inert until the peer's own registry grants the capability. Phases 3–5
(the Master console, notifications, and the live deploy that turns the
overlay-reachable surface on) are still open and listed as unbuilt below.

Related, already-proposed surface: the per-user vaults design in
[`PER_USER_VAULTS_DESIGN.md`](PER_USER_VAULTS_DESIGN.md) already names the
bridge admin channel and the missing capability. This page is the
administration half of that work.

## The problem

The two cluster2 nodes (`.131` Master, `.133` peer) each run their **own**
Open WebUI on `0.0.0.0:8181`, each against its **own** `open-webui-data` volume.
There is no federation between them, so:

- a signup or sign-in on `.133` is invisible on `.131`, and vice versa;
- a signup request produces no notice to anyone — the surface is not
  self-service today (`ENABLE_SIGNUP: "false"`), so the account a user *wants*
  can only be created by an operator already logged into that node;
- there is no single place to review or change a user's role, model access,
  knowledge base or chats across nodes;
- **both** nodes expose a human administrator (`admin@sparknet.local`) on the
  LAN and overlay, so "administrator login" is possible everywhere.

## Operator decisions (2026-10-12)

| Question | Decision |
|---|---|
| Architecture | **Signed federation** — peers stay authoritative for their own users; the Master supervises over the fabric's signed transport, never a shared WebUI password. |
| Signup | **Enable signup with pending approval** — self-registration is allowed, but a new account lands `pending` and reaches nothing until an admin Accepts it. |
| Notifications | **Master console live feed + KDE Connect push** — the Master's console shows activity as it happens; signups and logins also ping paired KDE devices. |
| Activity scope | **Successful logins only**, plus **full admin control** — no failed-login capture; the Master can do everything a node admin can do, remotely. |

## Current state (why this is not a config flip)

| Root cause | Where |
|---|---|
| Per-node SQLite; no shared store | `open-webui-data` volume, [`peer-node/configs/ai-stack/docker-compose.yml`](peer-node/configs/ai-stack/docker-compose.yml) |
| Signup disabled, so nothing to review | same file, `ENABLE_SIGNUP: "false"` |
| No event stream configured | no `events.webhooks` registration on either node |
| Provisioner ignores unapproved roles | [`peer-node/services/sparknet-vault-provisioner.py`](peer-node/services/sparknet-vault-provisioner.py) — only `user`/`admin` roles are provisioned |
| Both nodes expose a human admin | `WEBUI_ADMIN_EMAIL: admin@sparknet.local` on both |
| Admin channel designed, unbuilt | [`PER_USER_VAULTS_DESIGN.md`](PER_USER_VAULTS_DESIGN.md), fabric `PLAN.md` Step 28 |

Open WebUI 0.12 gives us the two primitives this design rests on, both verified
in the upstream source:

- **Event webhooks** (`events.webhooks` config key, managed through
  `POST /api/events/webhooks`). The auth catalog names `auth.signup`,
  `auth.login`, `auth.logout`, `auth.password_changed`, and `user.role_updated`
  is in the users catalog. `auth.login` fires on **success**, so "successful
  logins only" is the default behaviour, not a filter we build.
- **`DEFAULT_USER_ROLE`** lets signup land accounts in `pending` instead of
  `user`, which is the approval gate the provisioner already respects by
  refusing to provision anything that is not `user`/`admin`.

## Architecture: signed federation

```
   .133 peer                         .131 Master
   ┌──────────────────────┐          ┌───────────────────────────────┐
   │ Open WebUI (8181)    │          │ Open WebUI admin surface      │
   │   └ events.webhooks ─┼──┐       │   (10.100.0.1:8080)           │
   │ sparknet-admin-agent │  │       │ sparknet-admin-console        │
   │   (loopback spool)   │  │       │   ├─ live feed                │
   │ sparknet-dispatch-   │◄─┼───────┤   ├─ user/KB/chat control      │
   │   bridge (4096)      │  │       │   └─ KDE Connect push         │
   │   └ /admin/* route   │  │       └───────────────────────────────┘
   └──────────────────────┘  │                  ▲
             overlay 10.100.0.2 ────────────────┘  signed admin-request
```

Three rules make this safe:

1. **A peer is authoritative for its own users.** The Master never writes a
   peer's database directly; it asks, and the peer's own agent performs the
   change against the peer's own Open WebUI admin API.
2. **Authority comes from a signature, not a password.** The Master signs each
   `admin-request` with its operational key (isolated signer). The peer verifies
   the signature against the fabric registry **before** any WebUI admin call, in
   guard-protocol order. A node with the admin vocabulary but not the key can
   verify but never act.
3. **The node's admin token never leaves the node.** The peer's bridge proxies
   to `http://127.0.0.1:8181/api/v1/...` with the peer's **own** service-account
   token, read from that node's `.state`.

### The new capability

`admin-supervise` — adopted shape (Phase 2 landed):

```json
"admin-supervise": {
  "grants": "Submit signed admin-requests that make a peer perform Open WebUI
             administrative actions (list/approve users, change roles, read
             chats/Knowledge, toggle access) against its own setup.",
  "holder": "master",
  "sensitive": true
}
```

`holder: master` and `sensitive: true`, like the other authority-bearing
surfaces. It is **cross-role atomic work**: `contracts/capabilities.json` +
`shared/sparknet-authz.py` `KNOWN_CAPABILITIES` + the guard/bridge verification
paths must land in one commit, then `make contract-test`. Until the real
registry carries a signed grant of it, the route exists and authorises nothing —
the same inert posture as `cluster-dispatch`.

## Node side — `sparknet-admin-agent.py` (Phase 1)

A small stdlib-only service on each node, in the peer role:

- **Auth-event ingest.** A loopback HTTP listener receives Open WebUI event
  webhooks and appends them to an append-only spool at
  `$SPARKNET_STATE_DIR/admin-events/events.jsonl` (mode 0600). Registered events:
  `auth.signup`, `auth.login`, `auth.logout`, `auth.password_changed`,
  `user.role_updated`. Only successes exist in the catalog, so no failure events
  are captured.
- **Webhook registration.** `--register-webhooks` calls the node's own Open
  WebUI admin API (`POST /api/events/webhooks`) to point the events at the
  agent's loopback URL. This is a deploy-time action because Open WebUI has no
  supported env var for the per-event webhook list.
- **Admin snapshot.** On each poll it reads `/api/v1/users/` with the node's
  service-account token and writes a normalised snapshot, so the Master can
  reconcile approvals without a live pull.

The agent holds no signing key. It is a reader of the node's own surface and a
writer of a local spool; it performs no administrative mutation itself — the
mutation path is the bridge `/admin/*` route (Phase 2, landed): the bridge
executes signed admin requests through this agent's `admin_api_call`/token
client, so the execution path and the ingest path share one WebUI client and
the node's service-account token stays on the node.

## Master side — the admin console (Phase 3)

The Master's existing admin surface (`10.100.0.1:8080`, declared in
[`contracts/ports.json`](contracts/ports.json) and
[`master-node/configs/admin-surface/docker-compose.admin.yml`](master-node/configs/admin-surface/docker-compose.admin.yml))
gains a console that:

- subscribes to each node's event feed (through the signed `/admin` route),
  showing a live, de-duplicated view of signups, logins and role changes;
- lists users across nodes, and can approve/deny, change roles, and inspect each
  user's Knowledge, models and chats;
- pages the operator over KDE Connect on signup/login, reusing the pattern in
  [`scripts/plugins/kde-notify.ts`](scripts/plugins/kde-notify.ts)
  (`kdeconnect-cli -d <id> --ping-msg`).

The console is an **admin-plane** surface, not an authority plane: a grant or
approval still originates at the guard ports and is signed in the isolated
signer. The console only composes signed `admin-request`s and displays results.

## Admin-only-on-master enforcement

The peer's administrator stops being a human:

- On a peer, the Open WebUI admin is a **service account**. Its password is
  generated at deploy, written 0600 under the node's site-local state dir, and
  read only by the provisioner and the admin-agent. No human is given it, so no
  human can log in as admin on the peer.
- On the **Master**, the human administrator remains. That is the one place an
  administrator signs in.
- `ENABLE_SIGNUP: "true"` with `DEFAULT_USER_ROLE: "pending"` turns the peer's
  chat surface into an approval-mediated one: a stranger may create an account,
  but it reaches nothing until the Master's console (via the peer's own agent)
  accepts it.

This supersedes the earlier "a chat surface must never be self-service" stance
for the peer; the compensating control is that `pending` confers no access, and
the approval decision is the Master's.

## Phases

| Phase | Work | Gate | Status |
|---|---|---|---|
| 0 | This design page; fabric `PLAN.md` step; peer and master plan pointers. | `make contract-test`, fabric suite green with only doc + plan edits. | **landed 2026-10-12** |
| 1 | Compose: signup + `pending` + audit trail; `sparknet-admin-agent.py`; unit + installer; tests. | peer suite green; `--help` contract; relocatable. | **landed 2026-10-12** |
| 2 | `admin-supervise` in `contracts/` + `shared/`; bridge `/admin/*` route; signer `sign-admin-request`. | `make contract-test`, master parity green. | **landed as code + signed plumbing 2026-10-12**; live legs (Phase 5) still carry the reachability change |
| 3 | Master admin console; deploy the declared admin surface; service-account enforcement. | console serves; no human admin on peer (DoD: confirm: user). | open |
| 4 | KDE Connect + live feed notifications. | plugin path proven against a paired device. | open |
| 5 | Live deploy on `.131`/`.133` (turns the overlay-reachable surface on; bridge today binds loopback by design). | `DoD: confirm: user`. | open |
| 6 | Full gates: `make test-all`, `contract-test`, `lint`, `validate`, `keys-check`, `shims-check`, `bundle-verify`, `precommit`. | green. | re-run whenever a phase lands |

## Boundaries — what this is not

- **Not a shared database.** No node reads another node's `open-webui-data`.
- **Not a shared password.** The cross-node link is signed, per
  [`PER_USER_VAULTS_DESIGN.md`](PER_USER_VAULTS_DESIGN.md) ("not shared WebUI
  passwords").
- **Not a new authority plane.** The console composes requests; signing stays in
  the isolated Master signer, and a peer's guard still gates mutation.
- **No secrets in the tree.** The service-account password and node admin tokens
  live in `.state`; only their *paths* are referenced.

## Honest boundary

Everything above is design until the phases land. Phases 0–2 are landed as
code and signed plumbing; the live legs (Phase 3–5) — a real signup landing
`pending`, the Master console approving it over the overlay, a KDE push
firing, and no human admin login succeeding on a peer — are `DoD: confirm: user`
on the target nodes. The bridge deliberately binds loopback until Phase 5: the
overlay-reachable `/admin/*` surface is a deployment binding change, not a code
one. As with the rest of this fabric, committing declarative config proves the
topology is coherent, never that a deployment held.
