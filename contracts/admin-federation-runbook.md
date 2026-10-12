# Admin federation runbook — Phase 5 live deploy (node131 + node133)

> Status: **procedure, not proof.** Every claim below about a deployed node is
> `DoD: confirm: user` until a human who can see that node confirms it. The
> companion design is [`../ADMIN_FEDERATION_DESIGN.md`](../ADMIN_FEDERATION_DESIGN.md);
> the signed shapes live in `capabilities.json`, `identity-schema.json` and
> `shared/sparknet-authz.py`. If a command here disagrees with a contract, the
> contract wins — this runbook is a script the operator reads, not a norm.

This is the operational translation of ADMIN_FEDERATION_DESIGN Phase 5: turn the
already-landed code (Phases 1–4) into a **running** cross-node admin surface on
the two physical hosts, prove the live legs, and keep every live leg
`confirm: user`.

## Hosts and addressing

The two nodes were moved onto the flat `192.168.178.0/24` LAN on **2026-10-12**.
The old `192.168.10.64` / `192.168.20.32` legs are **retired** and no longer
resolve; do not use them. `~/.ssh/config` carries the current aliases.

| Role | SSH alias | Hostname | LAN | Overlay `wg1` | Node id | Cluster tree | State dir |
|---|---|---|---|---|---|---|---|
| Master | `ssh agx64` | `red-team` | `192.168.178.131` | `10.100.0.1/32` | `node131` | `/home/raxxar/sparknet-cluster2` | `/home/raxxar/.local/state/sparknet/cluster2` |
| Peer | `ssh agx32` | `blue-team` | `192.168.178.133` | `10.100.0.2/32` | `node133` | `/home/raxxar/sparknet-cluster2` | `/home/raxxar/.local/state/sparknet/cluster2` |

Declared surfaces this touches (see `ports.json`): the peer bridge **4096**
(`dispatch-bridge`, currently `--bind 127.0.0.1`) and the Master admin surface
**8080** (`admin-surface`, `10.100.0.1`). The console dials the peer bridge on
`<peer-overlay-ip>:4096/admin/<action>`.

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

1. `serve()` in `peer-node/services/sparknet-dispatch-bridge.py` hard-codes
   `server.loopback_only_routes = ()` — it declares **no** local-personality
   route class. The shared transport only protects a route that is *named* in
   `loopback_only_routes` (`shared/sparknet-http.py`, `check_source_policy`).
   So binding the bridge to the overlay as-is exposes the **entire** surface —
   including the OpenAI proxy that "injects the user environment profile", and
   the `/session/`, `/vault/` routes — to every overlay node. That violates the
   `ports.json` 4096 note ("Local-only by design: it injects the user environment
   profile, so it must not be exposed") and the invariant "Peer-side listeners
   that inject local identity or accept mutations stay off the overlay."
2. Binding to a single address (`--bind 10.100.0.2`) drops the loopback listener,
   so the bridge's own local consumers of port 4096 stop resolving.

**Required minimal change, landed as code + test before Phase D:**

- Declare the local personality. Add a module constant and use it:
  ```python
  OPENAI_LOCAL_ONLY = ("/v1/models", "/v1/chat/completions", "/v1/openapi.json", "/session/", "/vault/")
  ...
  server.loopback_only_routes = OPENAI_LOCAL_ONLY   # was: ()
  ```
  `/admin/` and the signed `/v1/status` are then reachable from the fabric, and a
  request from an overlay source to any OpenAI/session/vault route is refused
  `403 not-loopback` **before the request is read**.
- Listen on **both** loopback and the overlay. Make `--bind` repeatable and run
  one `ThreadingHTTPServer` per address (sharing one `Bridge`), or run a second
  loopback listener beside the overlay one. **Never bind a wildcard (`0.0.0.0`)**:
  that exposes the bridge to the LAN, which is worse than the overlay.
- Add a regression test: an overlay-source request to `/v1/chat/completions`
  gets `403 not-loopback`; to `/admin/list_events` (bad signature is fine) does
  **not**.
- Re-bundle so the change ships in Phase A.

Do not skip F1. A runbook that only flips `--bind` ships the environment injector
to the fabric.

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

## Phase D — expose `/admin/*` over the overlay (after F1)

```bash
ssh agx32
# edit the deployed unit to listen on loopback AND the peer's overlay address:
#   ExecStart=... sparknet-dispatch-bridge.py --serve --bind 127.0.0.1 --bind 10.100.0.2 --port 4096
sudo systemctl edit --full sparknet-dispatch-bridge.service   # or edit the file the deploy wrote
sudo systemctl daemon-reload
sudo systemctl restart sparknet-dispatch-bridge.service

# prove the local personality still holds (from the peer itself, both must 403):
curl -s -o /dev/null -w '%{http_code}\n' http://10.100.0.2:4096/v1/chat/completions   # expect 403
# and the admin route is NOT refused for being off-loopback (403 capability/bad-sig is fine):
curl -s -o /dev/null -w '%{http_code}\n' -X POST http://10.100.0.2:4096/admin/list_users
```

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

## Phase F — KDE push

```bash
# on the Master, with a paired device:
export SPARKNET_KDE_DEVICES='<device-id>'   # or leave unset to discover via kdeconnect-cli
make -C master-node console ARGS="--registry $REG feed --ping"
```

A missing `kdeconnect-cli` is a silent no-op, exactly like
`scripts/plugins/kde-notify.ts` — never a blocker.

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
