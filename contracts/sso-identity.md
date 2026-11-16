---
title: federated admin identity and offline break-glass
role: both
updated: 2026-11-16
---

# Federated admin identity and offline break-glass

This contract is normative for how a human administrator is identified on every
node, how a node authenticates that administrator when it cannot reach the
Master, and how role truth and offline repairs are reconciled. It is the
companion to `ADMIN_FEDERATION_DESIGN.md` and is decided by
`docs/adr/0022-federated-admin-identity-offline-break-glass.md`.

**Status: contract and live on the current fleet (2026-11-16).** Dex 9443,
lldap, the admin CA, the Master SSO ingress 8092, the peer admin ingress 8182
and the Master `/nodes/` proxy are live on `agx32`/`agx64`/`sparknet-node-0003`.
OIDC browser login via a per-node oauth2-proxy on loopback 4180 is live: the
`sparknet-admin` identity reaches 200 on 8092/8182, a user-only identity is
refused with `admin-required`, and the client-certificate path still returns
200. The offline-repair reconnect test and signed bundle verification remain
`DoD: confirm: user`.

## The two identities

| Identity | Holder | Used for | Never used for |
|---|---|---|---|
| **Node identity** | the node's state dir, 0600 | registry entry, signed requests, node-signed repair records | logging a human in |
| **Human identity** | the Master-hosted OIDC provider | human login on any node, online; the admin principal | signing a fabric capability, a registry entry or an approval |

A human identity is **not** a node role and does not enter
`contracts/identity-schema.json`'s `identity_fields`. It is an authentication
principal; authority still comes from the node's registry grant and the Master's
operational key. A WebUI login, including an admin login, grants no fabric
capability (`webui-surface.md`, "Identity and authority").

The **admin principal** is the human identity in the IdP group
`sparknet-admins`. The **user principal** is a human identity in
`sparknet-users`. A human in neither group is refused online; there is no
implicit `pending` promotion from the IdP.

## Online path

```
browser -> Master admin proxy (8092, overlay) or the node admin gateway (8182)
        -> OIDC against the Master IdP (9443, overlay)
        -> group -> role (sparknet-admins=admin, sparknet-users=user)
        -> trusted headers (X-User-Email, X-User-Role, X-User-Groups)
        -> Open WebUI (loopback only)
```

Rules:

1. **Two ingresses, one admin path.** The existing user ingress on 8181 keeps
   the normal Open WebUI login/signup surface and is unchanged. The federated
   admin path is the separate admin-only ingress on 8182, which calls the auth
   gateway and injects verified headers. Open WebUI itself binds loopback and
   never a wildcard. A user login never depends on the admin ingress, and the
   admin ingress never serves an anonymous user session.
2. **Strip, then inject.** The gateway removes every caller-supplied
   `X-User-*` header before it injects its own. A request from a client that
   reaches Open WebUI directly, or that carries its own identity headers, is a
   defect, not a feature.
3. **One origin from the Master.** The Master admin proxy authenticates the
   operator once, resolves the target from the signed registry, and forwards a
   short-lived assertion over mTLS to that node's gateway. It is not an open
   proxy: the target allow-list is the registry, never a caller-supplied URL.
4. **No shared password.** No human uses the deploy-time `WEBUI_ADMIN_*`
   account. It is a locked automation account for the admin agent, bridge and
   provisioner, and its password stays 0600 on the node.

## Offline path

An isolated node cannot reach the Master IdP, so it cannot complete the OIDC
code exchange. The same gateway provides a local path:

1. The admin presents a **client certificate** over TLS. It is issued under the
   fabric admin CA, is short-lived (90 days by default), and is held on a
   hardware token or an equivalent protected store.
2. The gateway verifies the chain, expiry and revocation state against the
   admin CA it holds locally. A missing, expired or revoked certificate is
   refused. It then injects `X-User-Email` and `X-User-Role: admin`.
3. No IdP, no Master and no overlay are required. The admin gets the full
   Open WebUI admin surface on that node.
4. **Regular users offline** use the local login form with a per-node local
   credential. Those accounts are per-node, are not federated and are **not
   synchronized** across nodes. This is the honest boundary of local-first.
5. The admin CA public certificate and the revocation list are 0644 under the
   node state dir; the CA private key never leaves the Master state dir at 0600.

## Role truth and precedence

| Source | Scope | Wins when |
|---|---|---|
| IdP group (`sparknet-admins` / `sparknet-users`) | every node | no per-node override exists |
| Signed `admin-supervise` `set_user_role` override | one node | it exists and is valid |
| Offline-repair record | one node, local state | the node is isolated; it is flagged on reconnect |

- The override is stored at `$SPARKNET_STATE_DIR/admin-role-overrides.json`
  (0600), written only by the node's signed `set_user_role` handler. It records
  the target user, role, request id, issuer and timestamp. It is not a second
  user database: it names only exceptions.
- The effective role is `override[user]` when present, otherwise the IdP group
  role. The gateway applies it; the node's admin agent does not rewrite roles on
  a poll.
- When an override disagrees with the current IdP group, the node records a
  `role-override-conflict` event and surfaces it to the Master console. The
  conflict is **held for a human**; neither side is silently overwritten.
- `pending` remains the local-signup default. An IdP identity is never
  automatically promoted to `user` or `admin`; it must be in the corresponding
  group.

## Offline repair

A change the admin makes on an isolated node is tagged `offline-repair`:

- The node signs a repair record with its **node identity key** and spools it
  under `$SPARKNET_STATE_DIR/admin-events/` at 0600.
- On reconnect, the Master verifies the node signature and the record's node id,
  and flags the change for review. The record may describe local user, role,
  Knowledge/KB, chat or setting state on that node.
- The record **must never** carry a new capability, a registry change, a trust
  root, a key, a protected-file approval or a grant to another node. Those are
  held for a human even when the node is the one reporting them.
- The offline change wins for that node's local state; the Master reconciles
  around it instead of overwriting it. A change that would widen authority is
  refused and reported.

## Secrets and trust

- IdP signing keys, the admin CA private key, OIDC client secrets and TLS keys
  live under `$SPARKNET_STATE_DIR` at 0700/0600. Only paths are referenced in the
  tree; `make keys-check` is the gate.
- Every node gets its **own** OIDC confidential client and secret. One secret
  copied to every node would make one compromised node a fabric-wide identity
  credential.
- The admin client certificate is short-lived and revocable. The node refreshes
  the revocation list when it can reach the Master; offline it fails closed on
  expiry. A revocation that cannot reach a node is a bounded risk, not a silent
  one.
- The Master IdP is overlay-only. Neither the IdP nor the admin proxy binds a
  wildcard address.

## Declared surfaces

| Surface | Port | Bind | Reachability |
|---|---|---|---|
| Master IdP | 9443 | Master overlay address | overlay only |
| Master admin SSO ingress / proxy | 8092 | Master overlay address | overlay only |
| Existing Master admin surface (retired 2026-11-16) | 8088 | Master overlay address | stopped; restart only for local rollback |
| Node admin ingress | 8182 | node overlay address and, for isolated repair, the node LAN address | fabric + LAN; never a wildcard |
| Node OIDC proxy | 4180 | loopback | local only |
| Node user ingress | 8181 | node LAN/overlay address | user login surface, unchanged |
| Open WebUI | 8180 (peer) / 8080 (Master) | loopback | local only |

The auth gateway is the one declared exception to "peer-side listeners that
inject local identity stay off the overlay": it injects identity only after OIDC
or mTLS verification, and it strips caller-supplied headers first. It carries no
vault content and is not a knowledge channel.

## Refusals

| Code | Meaning |
|---|---|
| `idp-unreachable` | online login attempted, IdP not reachable; use the offline path |
| `bad-client-cert` | no client certificate or the chain does not verify |
| `cert-expired` / `cert-revoked` | the offline admin certificate is not valid |
| `unapproved` | the IdP identity is in neither allowed group |
| `role-override-conflict` | per-node override and IdP group disagree; held for a human |
| `assertion-stale` | the Master→node assertion is expired, replayed or for another node |
| `offline-repair-refused` | a repair record tries to carry authority, a key or a grant |

## What this is not

- **Not vault access.** The admin role manages users, roles, Knowledge/KB,
  chats, models, prompts, settings and files. It does not read a user's private
  vault pages outside the session grant's `vault_scope`, and it does not gain
  containers, shell or host root.
- **Not a shared user database.** Identity is federated; per-node Open WebUI
  state is not copied. Offline user accounts are per-node.
- **Not a new fabric authority plane.** The IdP authenticates. The registry
  grants capabilities. The signer signs. The admin console remains an
  admin-plane surface, not a signing surface.
- **Not knowledge.** Auth events, role claims, admin responses and repair
  records are authority/audit data. A user's AI may not answer from them
  (`knowledge-flow.md` rule 7).

## Verification

- Contract tests: the ports, the role precedence table, the refusal vocabulary
  and the "no shared password / no shared database / no vault access" rules are
  asserted from this page.
- Code tests: gateway header stripping, OIDC group mapping, mTLS offline login,
  override precedence, conflict recording, offline-repair signature and
  refusal.
- Gates: `make contract-test`, `make validate`, `make test-all`, `make
  keys-check`, `make bundle-verify`.
- Live: IdP discovery, online login on each node, offline login with the Master
  unreachable, and the Master proxy reaching each node are `DoD: confirm: user`.
