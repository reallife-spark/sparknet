# sparknet master-node — Session Memory

> Standing state only. Read at session start; **replace, never append**.
> The plan and cursor live in `PLAN.md`; history belongs in
> `02_Daily/YYYY-MM-DD.md` and `00_System/log.md`.

Updated: 2026-11-02

## Plan cursor

- `PLAN.md` — read its `current:` field. Do not mirror step history here.

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
- **The admin surface** runs on `agx32` at `10.100.0.1:8088`; it carries no
  signing capability. Reachability from an operator client is `DoD: confirm:
  user`.
- `$SPARKNET_STATE_DIR` is outside the vault. The admin surface bind-mounts the
  vault read-only, so the key cannot live inside it. `make keys-check` enforces
  the boundary.
- **Live on agx32 (2026-10-31)**: the 8090 peer intake and scoped RFI
  responder are active; a real peer request was answered and installed; the
  admin console `feed` and `users` paths work over `admin-supervise`; registry
  sequence 2 was re-signed under the current envelope and delivered. The peer
  entry now carries `admin-supervise`.
- **Open items**: Master Steps 10–12 live legs, Phase 9's destructive legs, and
  the live 4203/three-node share transport remain open. 4201/4202, 4220
  (read-only git), 4221 (read-only files), 4222 (status/dry-run) and 4223 are
  live on the pair (2026-10-31); the 4203 queue is built, not enabled. Step 8 live containment was verified on `agx32` 2026-10-28; Step 9
  live arming remains operator-confirmed.
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
