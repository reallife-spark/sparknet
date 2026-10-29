# Admin federation runbook — Phase 5 live deploy (historical cluster2)

> Status: **historical procedure; executed on the retired cluster2 pair.**
> Every role-bound host name and command below describes that retired pair
> (`.131` Master / `.133` peer). The current Step 57 pair is **`agx64` peer /
> `agx32` Master**, with state dirs `~/sparknet/peer-node/.state` and
> `~/.local/state/sparknet/master-node`. Do **not** copy a role-bound command
> from this page onto the current pair without re-mapping the role. Admin
> federation has not been redeployed on the current pair; that leg is
> `DoD: confirm: user`. The companion design is
> [`../ADMIN_FEDERATION_DESIGN.md`](../ADMIN_FEDERATION_DESIGN.md);
> the signed shapes live in `capabilities.json`, `identity-schema.json` and
> `shared/sparknet-authz.py`. If a command here disagrees with a contract, the
> contract wins — this runbook is a script the operator reads, not a norm.

This is the operational translation of ADMIN_FEDERATION_DESIGN Phase 5: turn the
already-landed code (Phases 1–4) into a **running** cross-node admin surface on
the two physical hosts, prove the live legs, and keep every live leg
`confirm: user`.

## Hosts and addressing

This table is the **retired cluster2** mapping on which Phase 5 was executed.
The current pair is listed separately; the roles are swapped.

| Pair | Role | Host | LAN / overlay | Node id | State dir |
|---|---|---|---|---|---|
| cluster2 (retired) | Master | `agx64` / `red-team` | `192.168.178.131` / `10.100.0.1` | `node131` | `~/.local/state/sparknet/cluster2` |
| cluster2 (retired) | Peer | `agx32` / `blue-team` | `192.168.178.133` / `10.100.0.2` | `node133` | `~/.local/state/sparknet/cluster2` |
| current (Step 57) | Peer | `agx64` / `sparknet-node-0001` | `192.168.178.21` / `10.100.0.2` | `node-0001` | `~/sparknet/peer-node/.state` |
| current (Step 57) | Master | `agx32` / `sparknet-node-0002` | `192.168.178.22` / `10.100.0.1` | `node-0002` | `~/.local/state/sparknet/master-node` |

The cluster2 trees live under `/home/raxxar/sparknet-cluster2`; the current
pair uses the role worktrees. The old `.131`/`.133` LAN legs are retired.
`~/.ssh/config` carries the current aliases.

Declared surfaces this touches (see `ports.json`): the peer bridge **4096**
(`dispatch-bridge`, currently `--bind 127.0.0.1`) and the Master admin surface
**8088** (`admin-surface`, `10.100.0.1`; relocated from 8080, fabric Step 55).
The console dials the peer bridge on `<peer-overlay-ip>:4096/admin/<action>`.

## Preconditions on both hosts

- The `wg1` overlay is up and reachable **both ways** — from the Master,
  `ping -c1 10.100.0.2`; from the peer, `ping -c1 10.100.0.1`. A node that cannot
  reach the other over the overlay cannot administer or be administered.
- The cluster2 tree and state dir exist as tabled above. The state dir must hold
  `keys/` (0600), `trust-root.json` (on the Master), `wg1.conf`, and — on the
  peer — `webui-admin-password` (0600). Confirm the private halves never leave
  their node.
- The Master's isolated signer runs: `systemctl is-active
  sparknet-master-signer-c2.service` → `active`, socket at
  `/home/raxxar/.local/state/sparknet/cluster2/signer/signer.sock`. The console
  holds no key; it can only ask this process.
- Read the design page's "The problem" and "Admin-only-on-master enforcement"
  sections before starting. `admin-supervise` is inert until Phase B grants it.

## Finding F1 — Phase 5 is not only a binding change (read first)

`ADMIN_FEDERATION_DESIGN.md` calls the overlay-reachable `/admin/*` surface "a
deployment binding change, not a code one". Recon against the live cluster2 trees
on 2026-10-12 shows that is **inaccurate**, and this runbook corrects it. Two
facts stand in the way:

1. The bridge's plain handler (`_plain()` in
   `peer-node/services/sparknet-dispatch-bridge.py`) enforced its own
   `_loopback_guard()`, refusing **every** non-loopback source on the *entire*
   plain surface — `/admin/*` included. As-is, a Master dialling
   `10.100.0.2:4096/admin/...` over the overlay would be refused `403
   off-loopback` before the signed ladder is ever reached, so Phase 5 cannot work
   without a code change.
2. Binding to a single address (`--bind 10.100.0.2`) drops the loopback listener,
   so the bridge's own local consumers of port 4096 stop resolving. And a naive
   fix that just opens the whole surface to the overlay exposes the OpenAI proxy
   that "injects the user environment profile" plus `/session/`, `/vault/` —
   violating the `ports.json` 4096 note ("Local-only by design: it injects the
   user environment profile, so it must not be exposed") and the invariant
   "Peer-side listeners that inject local identity or accept mutations stay off
   the overlay."

**Required minimal change, landed as code + test before Phase D:**

- Declare the local personality as a named route class and apply it in the plain
  handler (the server attribute alone is *not* enough, because the plain handler
  guarded itself):
  ```python
  LOCAL_ONLY_PREFIXES = ("/v1/models", "/v1/chat/completions", "/v1/openapi.json", "/session/", "/vault/")
  ...
  # in Handler._plain(), replace self._loopback_guard():
  source = bridge.http.source_kind(self.client_address)
  reason = bridge.http.check_source_policy(path, source, LOCAL_ONLY_PREFIXES)
  if reason is not None:
      raise _HttpRequestError(403, reason, f"{path} is loopback-only; caller is from the {source} personality")
  ```
  `/admin/` and the signed `/v1/status` are then reachable from the fabric, and a
  request from an overlay source to any OpenAI/session/vault route is refused
  `403 not-loopback` **before the request is read**. `_configure_server()` also
  stamps `server.loopback_only_routes = LOCAL_ONLY_PREFIXES` so the shared signed
  handler agrees (defense-in-depth; the signed routes themselves are unaffected).
- Listen on **both** loopback and the overlay. Make `--bind` repeatable and run
  one `ThreadingHTTPServer` per address (sharing one `Bridge`). **Never bind a
  wildcard (`0.0.0.0`)**: that exposes the bridge to the LAN, which is worse than
  the overlay.
- Add a regression test: an overlay-source request to `/v1/chat/completions`
  gets `403 not-loopback`; to `/admin/list_events` (bad signature is fine) does
  **not**.
- Re-bundle so the change ships in Phase A.

The F1 fix is **landed** (bridge + `peer-node/tests/test_admin_supervise.py`,
two new tests). Live on the cluster2 trees it appears with Phase A.

Do not skip F1. A runbook that only flips `--bind` either ships the environment
injector to the fabric or dead-ends the Master at the source guard.

## Phase A — land the Phases 1–4 code on both cluster2 trees

The live cluster2 trees are from 2026-10-09/11 and **predate** Phases 1–4: their
`peer-node/services/` has no `sparknet-admin-agent.py` and their
`master-node/services/` has no `sparknet-admin-console.py`. Update both trees to
the current tree (which includes F1).

```bash
# from the build host (this fabric root), transport is OUT OF BAND:
make bundle ROLE=master      # -> dist/sparknet-master-worktree-<ts>.tar.gz
make bundle ROLE=peer        # -> dist/sparknet-peer-worktree-<ts>.tar.gz
# scp the peer bundle to agx32 and the master bundle to agx64, then on each host:
#   tar xzf sparknet-<role>-worktree-<ts>.tar.gz --strip-components=1 \
#       -C /home/raxxar/sparknet-cluster2
```

The bundle carries `contracts/`, `shared/sparknet-authz.py`,
`peer-node/services/sparknet-admin-agent.py` + the F1-fixed
`sparknet-dispatch-bridge.py`, `peer-node/configs/ai-stack/docker-compose.yml`,
and `master-node/services/sparknet-admin-console.py`. Preserve the existing
state dir — it is untouched by extraction.

## Phase B — Master grants `admin-supervise` to the peer and publishes

`admin-supervise` authorises the Master to submit requests, but the **peer's own
registry entry** is what the peer bridge checks (`handle_admin`:
`"admin-supervise" not in decision.capabilities`). So the peer's entry must carry
it. Re-sign `node133`'s existing identity with the capability added, then deliver
the registry.

```bash
ssh agx64
cd /home/raxxar/sparknet-cluster2
export SPARKNET_STATE_DIR=/home/raxxar/.local/state/sparknet/cluster2

# 1. Sign node133's identity with admin-supervise ADDED (it exists on the peer):
#    copy the peer's live identity first, or reconstruct the identity object from
#    peer-node/manifests/node-authorizations.json (node_id node133,
#    overlay_ipv4 10.100.0.2/32, wg key from the entry).
make -C master-node authz-sign \
  IDENTITY=/tmp/node133-identity.json \
  CAPS='telemetry,p2p-sync,push-receive,admin-supervise' \
  OUT=/tmp/node133-admin-supervise.json

# 2. Replace node133's entry in the registry copy (keep node131's entry, keep
#    master_public_key_b64) with /tmp/node133-admin-supervise.json.
$EDITOR peer-node/manifests/node-authorizations.json

# 3. Verify the whole registry against the Master key:
make -C master-node registry-verify REGISTRY=peer-node/manifests/node-authorizations.json
```

Deliver the updated registry to the peer (replace its
`peer-node/manifests/node-authorizations.json`), then **restart the peer bridge**
so its `Bridge` reloads the registry, and confirm the grant:

```bash
ssh agx32
sudo systemctl restart sparknet-dispatch-bridge.service
# the node must now report admin-supervise in its own capabilities:
cd /home/raxxar/sparknet-cluster2 && make contract-test   # cross-role contract intact
```

## Phase C — deploy the node admin agent on the peer

The agent ingests the peer's own Open WebUI auth events to a 0600 spool and
registers the webhooks. It holds no signing key and performs no mutation.

**Precondition (found live 2026-10-12):** the peer's Open WebUI rejects any
non-global URL unless `ENABLE_LOCAL_WEB_FETCH=true`
(`open_webui/retrieval/web/utils.py` `_assert_addresses_allowed`). The agent
registers a loopback webhook (`http://127.0.0.1:4130/events`), so without the flag
`POST /api/v1/webhooks` returns `HTTP 400 The URL you provided is invalid` and the
agent crash-loops. Set `ENABLE_LOCAL_WEB_FETCH: "true"` on the `sparknet-webui`
service in `peer-node/configs/ai-stack/docker-compose.yml` and recreate the
container (it runs `NetworkMode: host`, so the URL is reachable; only validation
blocks it). This widens the WebUI's RAG web-fetch SSRF guard to allow loopback —
an explicit operator decision, scoped to the loopback-webhook design.

```bash
ssh agx32
# install the unit + shim (the unit sets SPARKNET_WEBUI, the admin password file,
# and SPARKNET_STATE_DIR=/home/raxxar/.local/state/sparknet/cluster2):
cd /home/raxxar/sparknet-cluster2/peer-node
scripts/sparknet-install-units.sh --apply        # writes /usr/local/libexec/sparknet/sparknet-admin-agent
sudo systemctl daemon-reload
sudo systemctl enable --now sparknet-admin-agent.service
systemctl status sparknet-admin-agent.service --no-pager

# confirm the webhooks registered and the spool appears after a login:
ls -l /home/raxxar/.local/state/sparknet/cluster2/admin-events/events.jsonl
```

The AI stack must already run with signup enabled and pending role
(`peer-node/configs/ai-stack/docker-compose.yml`: `ENABLE_SIGNUP: "true"`,
`DEFAULT_USER_ROLE: "pending"`, `AUDIT_LOG_LEVEL: "METADATA"`). If the compose
changed in Phase A, recreate the webui container once.

**The agent must run as the NODE's own user** — the same user that runs the
dispatch bridge (here `raxxar`). The spool is written 0600 under the state dir and
the bridge reads it to answer `list_events`/`feed`; if the agent runs as `root`
the spool is `root:0600` and the bridge's read fails `HTTP 500 internal`. The
committed unit sets `User=raxxar` for exactly this reason (found live 2026-10-12).

The agent re-syncs its webhook on every start with `PUT
/api/events/webhooks/<id>`; the create path is `POST /api/events/webhooks`
(Open WebUI `main.py`; a `PATCH` on the id answers `405`).

## Phase D — expose `/admin/*` over the overlay (after F1)

```bash
ssh agx32
# edit the deployed unit to listen on loopback AND the peer's overlay address:
#   ExecStart=... sparknet-dispatch-bridge.py --serve --bind 127.0.0.1 --bind 10.100.0.2 --port 4096
sudo systemctl edit --full sparknet-dispatch-bridge.service   # or edit the file the deploy wrote
sudo systemctl daemon-reload
sudo systemctl restart sparknet-dispatch-bridge.service

# prove the local personality holds *from the overlay* (run on the Master, agx64):
ssh agx64
curl -s -o /dev/null -w '%{http_code}\n' http://10.100.0.2:4096/v1/chat/completions   # expect 403 (not-loopback)
# and the admin route is NOT refused for being off-loopback — a bodyless unsigned
# POST reaches the handler as 400 malformed (a signed request is required), never
# 403 not-loopback (verified live 2026-10-12):
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://10.100.0.2:4096/admin/list_users
```

A loopback caller (the peer itself) still gets `401 missing-grant` on the local
routes — that is the correct local behavior, not an overlay refusal. Only an
overlay source sees `403 not-loopback`.

From any non-overlay host the peer's 4096 must be unreachable; from the Master it
must be reachable. That difference is the whole point of the overlay binding.

## Phase E — run the console from the Master

The console composes an unsigned request, signs it over the isolated signer
socket, and posts it to the peer over the overlay.

```bash
ssh agx64
cd /home/raxxar/sparknet-cluster2
export SPARKNET_STATE_DIR=/home/raxxar/.local/state/sparknet/cluster2
export SPARKNET_NODE_ID=node131

REG=/home/raxxar/sparknet-cluster2/peer-node/manifests/node-authorizations.json

make -C master-node console ARGS="--registry $REG users node133"
make -C master-node console ARGS="--registry $REG events node133"
make -C master-node console ARGS="--registry $REG feed"
make -C master-node console ARGS="--registry $REG approve node133 <user_id>"
make -C master-node console ARGS="--registry $REG role node133 <user_id> admin"
```

`--dry-run` composes without signing; `--json` emits machine output. The signer
socket defaults to `$SPARKNET_STATE_DIR/signer/signer.sock` (the cluster2 signer).

**Preconditions (both found live 2026-10-12):**

- The peer's `peer-node/manifests/keys/master-ed25519.pub.b64` must hold the trust
  root's `master_pubkey` (`jq -r .master_pubkey
  /home/raxxar/.local/state/sparknet/cluster2/trust-root.json`). If it still holds
  the repo placeholder `I+8r6I3…`, every admin request fails `403 bad-signature`:
  the bridge's `_master_public_key()` reads that file, **not** the registry's
  `master_public_key_b64`. Provision it and the key is re-read per request (no
  restart needed). (Same defect as 2026-10-07.)
- Restart `sparknet-master-signer-c2.service` if it predates the current code;
  otherwise it refuses with `unknown operation 'sign-admin-request'`.
- Recreating the peer's `sparknet-webui` (Phase C) invalidates the bridge's cached
  service-account token, so `/admin/*` then answers `401 webui-refused` until
  `sparknet-dispatch-bridge.service` is restarted (the bridge mints its token once
  at start). Restart the bridge after any WebUI recreate.
- The console CLI used to prepend the **target node** as the first entity field, so
  `approve node133 <id>` sent `user_id: "node133"` and the peer answered `400`
  `{"detail": "We could not find what you're looking for :/"}` (`USER_NOT_FOUND`) —
  every `user_id` action failed. Fixed live 2026-10-12: `main()` must call
  `build_entity(action, args.entity)` (the target is the `spec`, not an entity
  field). Update the Master's `master-node/services/sparknet-admin-console.py` if
  it predates that fix.

Note that a bare `feed` (no `--node`) polls **every** registry node, including the
Master itself (`10.100.0.1:4096`), where no bridge runs → `Connection refused`. Use
`feed --node node133`, or run a bridge on the Master.

## Phase F — KDE push

The ping is sent by whatever host runs the console. If the Master *is* the
operator's own machine with KDE Connect paired, set the device ids (or leave
unset to discover) and go:

```bash
# on a Master that itself holds the KDE Connect pairing:
export SPARKNET_KDE_DEVICES='<id-a>,<id-b>'   # or leave unset to discover via kdeconnect-cli
make -C master-node console ARGS="--registry $REG feed --node node133 --ping"
```

A missing `kdeconnect-cli` is a silent no-op, exactly like
`scripts/plugins/kde-notify.ts` — never a blocker.

**Headless Master (the cluster2 pair, verified live 2026-10-12).** There the Master
(`agx64`) has no KDE Connect; the paired devices live on the operator's
workstation (`raxxar`, `192.168.178.126`). Forward the ping there — an
`ssh`-to-workstation key, a `raxxar-kde` host alias, and a `kdeconnect-cli` shim
on the Master that runs the real one inside the operator's session bus
(`DBUS_SESSION_BUS_ADDRESS`; a non-interactive shell has no session bus):

```bash
# on the workstation once: authorize the Master's forwarder key
cat agx64-kde-forwarder.pub >> ~/.ssh/authorized_keys

# on the Master (agx64): host alias + forwarder shim (host-local; not committed)
cat >> ~/.ssh/config <<'EOF'
Host raxxar-kde
    HostName 192.168.178.126
    User raxxar
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    BatchMode yes
EOF
sudo tee /usr/local/bin/kdeconnect-cli >/dev/null <<'SH'
#!/bin/sh
exec ssh -o BatchMode=yes raxxar-kde \
  "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus /usr/bin/kdeconnect-cli $*"
SH
sudo chmod +x /usr/local/bin/kdeconnect-cli

# device ids from the workstation (`kdeconnect-cli -a --id-only` there):
export SPARKNET_KDE_DEVICES='ca366bd7…,0a45d061…'
make -C master-node console ARGS="--registry $REG feed --node node133 --ping"   # => "notified": true
```

## Live confirm checklist (`DoD: confirm: user`)

Confirm each on the nodes; none is provable from the build host:

1. A **real signup** on the peer (`http://10.100.0.2:8181`) lands `pending` and
   reaches nothing until approved; the event appears in the peer's spool.
2. `console feed` on the Master shows that signup/login event **over the
   overlay**, read from the peer's own spool (no database access).
3. `console approve node133 <user_id>` succeeds over the overlay and the account
   becomes usable.
4. `console feed --ping` pages a **paired KDE device**.
5. **No human admin on the peer**: the peer's WebUI admin is the machine service
   account (0600 password under the state dir); a human login as admin on the peer
   fails or is impossible.
6. `/admin/*` is reachable **only** over the overlay and the OpenAI/session/vault
   routes stay `403 not-loopback` from the fabric (F1 holds live).

## Rollback

- **Contain the peer binding**: set the bridge back to `--bind 127.0.0.1`,
  `daemon-reload`, restart. The overlay admin surface is off; the node keeps
  working locally.
- **Revoke the grant**: `make -C master-node revoke IDENTITY=/tmp/node133-identity.json
  OUT=/tmp/node133-revoked.json`, replace the entry, `registry-verify`, deliver to
  the peer, restart the bridge. A revoked entry makes the peer refuse admin
  requests (`capability_missing`).
- **Stop ingest**: `sudo systemctl disable --now sparknet-admin-agent.service`.
  The spool is inert without the bridge route.

## Honest boundary

This procedure proves the **topology is coherent and executable**, never that a
deployment held. The live legs above are `DoD: confirm: user` on `.131`/`.133`.
The bridge stays loopback-only until Phase D **and** F1 (route-class declaration)
land together; a binding flip alone is unsafe. Signing the peer's grant proves the
Master *can* authorise, not that any peer *acted*.
