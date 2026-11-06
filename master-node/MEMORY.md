# sparknet master-node — Session Memory
> Standing state only. Read at session start; **replace, never append**.
> The plan and cursor live in `PLAN.md`; history belongs in
> `02_Daily/YYYY-MM-DD.md` and `00_System/log.md`.
Updated: 2026-11-06
## Plan cursor
- `PLAN.md` — read its `current:` field. Do not mirror step history here.
- **Role inversion planned, not executed:** `agx64` will become Master and
  `agx32` the peer in Step 26/88. Until the live re-formation lands, the
  current deployment line below remains the truth. Step 9G is parked until
  after Step 26.
- **Admin-only WebUI live 2026-11-05:** Open WebUI `v0.13.0` on `10.100.0.1:8088`
  has exactly one `admin@sparknet.local` account and signup off. The old
  cluster2 `sparknet-webui` on `8181` was retired after Jennifer's chat was
  migrated to the peer. The admin engine runs on loopback `4204` over
  `/srv/sparknet/knowledge/master-admin`; the role vault is never mounted.
## Durable facts
- **Fleet memory (2026-11-02):** the Master inspects peer memory only through
  signed, on-demand `memory-supervise`; no mirror. The peer audits the read and
  the user sees the access log. Other memory data is counts and posture.
- **Current deployment**: `agx32` is the elected Master
  (`sparknet-node-0002`, `wg1 10.100.0.1/32`); `agx64` is the peer
  (`0001`, `10.100.0.2/32`). The `agx32` text vLLM is deliberately stopped;
  `agx64` is the fabric inference path.
- **The election/signer arc is proven live** (2026-10-07, re-formed 2026-10-19):
  a 2/2 trust root, `sparknet-master-signer.service`, a signed registry entry
  verified by a still-peer, a real reboot, and a revoke→inert→re-authorize
  cycle. That is a dated claim about those hosts, not a general guarantee.
- **A Master is a peer that won an election.** `manifests/node-identity.json`
  says `role: peer`; the signed root confers authority. The signer is enabled
  only by an election (`make signer-unit` stages it, `make units` excludes it).
- **The admin surface** runs on `agx32` at `10.100.0.1:8088`; it carries no signing capability. Operator reachability is `DoD: confirm: user`.
- `$SPARKNET_STATE_DIR` is outside the vault. The admin surface bind-mounts the
  vault read-only, so the key cannot live inside it. `make keys-check` enforces
  the boundary.
- **Learning link (2026-11-04):** the Master writes a sanitized snapshot to
  `/srv/sparknet/share/learning/status.json`; 4221 serves it to the peer console.
  Master console accepts authenticated `user` and `admin` for read-only pages.
- **Live on agx32 (2026-11-04)**: 8090 intake/RFI responder active; admin `users`/`events`/`knowledge` 200; registry sequence 8 carries the peer node key, `cluster-serve` and `memory-supervise`; Master `memory_status`/read-200 through the peer gateway. A long-running bridge must be restarted after a capability is added.
- **Open items**: Step 9G is parked until after the Step 26 role inversion — the signed dispatcher is built but the live 02:00–05:00 window is operator-confirmed. Step 10 is closed by operator scope (two-node `peer_pair`); 4203 stays staged, disabled and inactive. Steps 11–12 and 24 are live-verified (2026-11-04); Step 25 is live-verified 2026-11-05.
- **Knowledge flow**: a signed RFI answer is the only Master→peer knowledge
  channel. Registry, approvals, telemetry and admin requests are not knowledge;
  see `../contracts/knowledge-flow.md`.
## Blockers
- A three-node cluster cannot survive the loss of a member under the current
  unanimity rule; the open question is in
  `../contracts/consensus-protocol.md`.
- Live signer, overlay, admin-surface and RFI delivery claims require the real
  pair; this development host has none of them.
## Local vs live
- The code, tests, ledgers and boundaries are verifiable here. WireGuard,
  systemd, the isolated signer, the browser surface and a live election are not.
- Say "implemented and tested", "deployed live on agx32/agx64 on <date>", or
  "unverified here" — never generalise a live run.
