# Role inversion runbook — agx64 Master, agx32 peer

Status: **executed 2026-11-06; core role inversion complete.** The live pair
is now `agx64` Master (`sparknet-node-0001`, `10.100.0.1`) / `agx32` peer
(`sparknet-node-0002`, `10.100.0.2`). Root `c77a3446…` (epoch 1, parent
`fa6f4fa5…`), registry sequence 9. Remaining: secret rotation, old
service/key/data cleanup, and goSpark control/agent placement. Every live leg
below is a dated host observation; do not generalise it.

## Target topology

| Role | Host | Node id | Overlay |
|---|---|---|---|
| Master | `agx64` | `sparknet-node-0001` | `10.100.0.1/32` |
| Peer | `agx32` | `sparknet-node-0002` | `10.100.0.2/32` |

The role change is a **chained re-formation** (`previous_root_id` = the old
root, `epoch` = old + 1), not a fresh election. The same node ids remain; the
identities change because role, overlay address and keys change. Both existing
cluster keys co-sign the new root. The new operational key is generated on
`agx64`; the old operational key on `agx32` is retired.

## Preconditions

- Fabric Step 88 is the active plan step. Master Step 9G is parked; no nocturnal
  window may run during the inversion.
- 84G, 86C/86D and 87 click-through are parked or explicitly deferred.
- Both hosts are reachable by their operators; maintenance is announced; no
  active user sessions, shares or RFI requests.
- The old trust root verifies, the ledger chain verifies, the registry sequence
  and head are recorded, and both cluster keys are present at their state dirs.
- Backups are encrypted, hashed and stored off-host. A restore rehearsal of at
  least one file per archive has passed.

## Phase 1 — Freeze and inventory

1. Stop user-facing and fabric services on both hosts. Leave the WireGuard
   overlay up until the new root is formed.
2. Record the preflight:
   - `systemctl list-unit-files 'sparknet-*'` and `systemctl cat` for the
     signer, ledger, admin, intake, vector, file-share, scheduler, guard,
     bridge, share, memory and engine units
   - `docker ps`, volume names and mounts
   - `ss -ltnup`, `wg show`, firewall rules
   - exact state dirs, `.env` names, role vault paths
   - user count, KB count, chat count, vault hashes, Qdrant collection counts
   - model inventory and runtime status
3. Archive:
   - `/srv/sparknet/knowledge/` (user vaults, `.state`, `master-admin`)
   - `/srv/sparknet/opencode-engine/`
   - `/srv/sparknet/uplift/`, `/srv/sparknet/distill/`
   - role vaults and state dirs
   - Docker volumes: peer WebUI, Master admin WebUI, peer Qdrant, Master Qdrant
   - Master ledger, evidence repo, registry, trust root
   - `.env`, systemd units
4. Verify every archive and store a manifest with SHA-256.

**DoD:** preflight JSON and archive manifests exist under
`/mnt/log/role-swap/`; restore rehearsal passes; no service writes after the
freeze.

## Phase 2 — Identities and roster

Update the committed templates; do not make a committed manifest claim
`role: master`:

- `master-node/manifests/master-identity.json`
  - `node_id: sparknet-node-0001`
  - `role: peer` (the live file flips only after the root is accepted)
  - `overlay_ipv4: 10.100.0.1/32`
- `master-node/manifests/node-identity.json`
  - `node_id: sparknet-node-0001`
  - `role: peer`
  - template overlay (not the Master anchor)
  - `election` block and `operational_key.held: false`
- `peer-node/manifests/node-identity.json`
  - `node_id: sparknet-node-0002`
  - `role: peer`
  - `overlay_ipv4: 10.100.0.2/32`

On the hosts:

- Keep each host's WireGuard key; change only the overlay address.
- Generate a new node identity key on each host. Do not move private keys.
- Generate the new operational key on `agx64` through the election ceremony.
- Keep the existing cluster keys on their hosts.
- Build `cluster-members.json` with the new fingerprints and the existing
  cluster pubkeys:
  - `sparknet-node-0001` → new `agx64` fingerprint, `agx64` WG pubkey,
    `agx64` cluster pubkey
  - `sparknet-node-0002` → new `agx32` fingerprint, `agx32` WG pubkey,
    `agx32` cluster pubkey
- Copy the old root document to `agx64`'s `master-node/manifests/cluster-trust-root.json`
  (or a separate `trust-root.previous.json`) so `accept_root` verifies the
  chain.
- Stop and disable the old signer on `agx32`; archive the old operational key
  offline. Do not copy it to `agx64`.

**DoD:** fingerprints recompute from the new identities; roster has two
distinct node ids; old root verifies; old signer is inactive.

## Phase 3 — Chained re-formation

Run the exchange on a host/IP reachable **before** the address swap:

```bash
shared/sparknet-election.py serve \
  --members cluster-members.json \
  --trust /path/to/old-root.json \
  --bind <reachable-ip> --port 4210
```

On `agx64`:

```bash
make -C master-node election-approve \
  EXPECT=sparknet-node-0001 \
  URL=http://<exchange-ip>:4210 \
  KEY_DIR=<agx64-state>/keys \
  ROOT_DOC=master-node/manifests/cluster-trust-root.json
```

On `agx32`:

```bash
make -C peer-node election-request \
  CANDIDATE=sparknet-node-0001 \
  URL=http://<exchange-ip>:4210 \
  KEY_DIR=<agx32-state>/keys \
  IDENTITY=peer-node/manifests/node-identity.json
```

Verify:

- 2/2 signatures from distinct members
- `master_node_id = sparknet-node-0001`
- `master_pubkey` = the new `agx64` operational public key
- `previous_root_id` = old root id
- `epoch = old epoch + 1`
- `verify_chain(new, old)` passes
- `agx64` identity flips to `role: master`
- `agx32` stays `role: peer` and has no `trust_root` block

Only after the root is formed, start the new signer on `agx64` with the new
root at `$SPARKNET_STATE_DIR/trust-root.json`.

**DoD:** root verifies on both hosts; signer on `agx64` returns the new root id;
old signer on `agx32` is disabled; no second key process exists.

## Phase 4 — Overlay and firewall

- `agx64`: render the Master WireGuard config at `10.100.0.1/32`; peer stanza
  for `agx32` at `10.100.0.2/32`.
- `agx32`: render the peer config at `10.100.0.2/32`; `AllowedIPs =
  10.100.0.1/32`.
- `agx64` Master: unrestricted egress; overlay-only Master ports.
- `agx32` peer: egress restricted to `10.100.0.1`; peer ports only.

**DoD:** `wg show` correct; both directions ping; peer egress restriction
proven; Master admin binds `10.100.0.1:8088` only.

## Phase 5 — Move Master state and services to agx64

Copy, verify, then start:

- ledger, evidence repo, registry, old/new roots
- `master-admin` vault
- Master admin WebUI volume
- Master Qdrant data
- `/srv/sparknet/uplift`, `/srv/sparknet/distill`
- share-ratify and scheduler state

Do **not** copy the old operational key or signer socket. Set
`SPARKNET_NODE_ID=sparknet-node-0001`. Start in order:

1. overlay/firewall anchor
2. signer
3. ledger
4. parity
5. registry install
6. admin console and admin surface
7. peer intake `8090`, uplift `8091`, RFI responder
8. file share `4221`, git `4220`, NAT `4222`, vector `4223`, share ratify
   `4203`, scheduler

**DoD:** signer returns the new root id; ledger chain verifies; admin `8088`
returns 200; `8090`, `8091` and `4220`–`4223` listen; no old key present.

## Phase 6 — Move peer state and services to agx32

Copy, verify, then start:

- `/srv/sparknet/knowledge/peer-*` and `.state`
- peer WebUI volume
- peer Qdrant data
- memory state and OpenCode engine state
- share, admin-event and self-heal state

Generate the new peer node identity key on `agx32`; do not copy `agx64` peer
private keys. Set `SPARKNET_NODE_ID=sparknet-node-0002`. Start:

- guard `9090`, bridge `4096`
- share `4201`/`4202`
- telemetry, checkpoint, inventory, RFI client
- memory `4110`/`4093`
- WebUI `8181`, engine `4204`, Qdrant
- provisioner, admin agent, self-healing timer

**DoD:** peer WebUI 200; user/KB/chat parity; memory `/api/memory` 200; engine
chat works; Qdrant counts match; guard verifies the new registry.

## Phase 7 — Registry, grants and secrets

- On `agx64`, sign a higher-sequence registry for both new identities with the
  **existing capability sets**; do not add blueprint capabilities in Step 88.
- Deliver to `agx32`'s guard; verify both entries.
- Re-issue grants/tokens bound to old fingerprints: WebUI, memory, engine,
  admin federation, goSpark control/agent.
- Rotate: WebUI secret, admin password, engine token, memory tokens, Qdrant API
  key, share-ratify token. Never echo values.

**DoD:** new sequence higher; both entries verify; peer guard installs; old
grants refused; all services healthy with new secrets.

## Phase 8 — Model placement

- `contracts/model-catalog.json`: Master `agx64` = teacher; peer `agx32` =
  student.
- `contracts/model-store.md`: update role placement prose.
- Move/copy teacher compose to `master-node/configs/model-runtime/` and student
  compose to `peer-node/configs/model-runtime/`.
- Update `runtime.json`, `scripts/sparknet-model-runtime.py`,
  `scripts/sparknet-model-pull.py`, `scripts/sparknet-model-bench.py`,
  `scripts/sparknet-model-survey.py`, WebUI model filters, manifests and tests.
- Keep the weights in place.

**DoD:** `make model-catalog-check`; teacher runs on `agx64`; student runs on
`agx32`; teacher is not eligible on `agx32`; benchmark recorded.

## Phase 9 — Verification and cleanup

Run the full matrix:

- root/signer/registry/overlay/firewall
- Master and peer service health
- data parity and model placement
- `make contract-test`, `make test-all`, `make lint`, `make format-check`,
  `make shellcheck`, `make render-check`, `make sbom-check`,
  `make drift-check`, `make context-check`, `make validate`, `make keys-check`,
  `make shims-check`, `make bundle-verify ROLE=peer|master`, `make ci`,
  `make -C gospark ci`

Then:

- disable/remove old role units from the wrong hosts
- archive old keys/root/registry; destroy after the new pair is stable
- remove old peer user data from `agx64` only after `agx32` is verified
- update `MEMORY.md`, `log.md`, today's session, `CONTEXT.md`, deployment and
  role-transition docs, model docs and `goagx`

**DoD:** all local gates green; every live leg dated and `DoD: confirm: user`;
no old role claim remains.

## Rollback

- **Before the new root is formed:** restore both hosts from backup, restore
  the old overlay addresses, old signer/trust root, old registry and services.
- **After the new root is formed:** the old root is superseded. Rollback is a
  new chained re-formation back to `agx32` as Master with a new operational key,
  then data restore. Do not restore the old root by editing files.
- Keep the old keys/root/registry offline until the new pair has run cleanly for
  the agreed period.

## What this runbook deliberately does not claim

No step here is a live observation from the development host. WireGuard,
iptables, systemd, the signer, Docker volume moves and browser surfaces are
target-host checks. A step is complete only when the host operator records the
dated evidence in `log.md` and the plan cursor advances.
