# sparknet — Session Memory

> Standing state only. Read at session start; **replace, never append**.
> The plan and cursor live in `PLAN.md`. History belongs in `log.md` and
> `sessions/YYYY-MM-DD.md`; the pre-2026-10-31 detail is in
> `_archives/MEMORY_FULL_2026-10-30.md`.

Updated: 2026-11-01

## Plan cursor
- `PLAN.md` — read its `current:` field; role plans own role work.
## Live fabric

- **`agx64` = peer = `sparknet-node-0001`** (`10.100.0.2/32`) and the local
  inference path; **`agx32` = master = `sparknet-node-0002`**
  (`10.100.0.1/32`), text vLLM stopped. Underlay `10.99.0.0/30`.
- Trust root `fa6f4fa5…` names agx32 Master; election proven 2026-10-07,
  re-formed 2026-10-19, overlay survives reboot. The 2026-10-07 root is archived.
- The admin surface runs on agx32 at `10.100.0.1:8088`; reachability is
  `DoD: confirm: user`. Peer AI: Open WebUI on `agx64:8181`, Ollama, ChromaDB.
- **Live on agx64/agx32 (2026-10-31)**: provisioning/admin ingestion, the RFI
  loop, bridge `vault.rfi`, telemetry/checkpoints, self-healing, admin
  federation and registry re-delivery run. Registry sequence 2 grants
  `admin-supervise`. A disposable signup→approval→KB→provisioning→deletion
  cycle was verified and fully cleaned; peer Step 11 is complete.
- **Live 2026-10-31:** share-1/2 over 4201/4202 staged in
  `master-node/01_Inbox/share-share-{1,2}/`; 4223 serves signed
  `sparknet-fabric`/`sparknet-shared`, and the peer has an 897-chunk local
  index. Registry sequence 4 grants `cluster-dispatch`. 4220 (read-only git),
  4221 (read-only files) and 4222 (NAT status/dry-run) are live. 4203/time-boxed
  stanza open; Phase 9 live-restored 2026-11-01; registry seq 5; 4203 staged; KillSwitch verified 2026-10-28.
- **User key re-keyed on agx64 (2026-10-31)** after `.state/keys` was lost;
  `U-27689` and 9 notes were preserved by re-signing; WG/node keys recovered.
## Durable facts

- A peer is the user's node; a Master supplies authority and scoped knowledge.
  Knowledge and authority never share a channel (`contracts/knowledge-flow.md`).
- `shared/sparknet-authz.py` is the one signed-authorization implementation.
  Never copy it; `../shared` is loaded by path where needed.
- A role subvault is not a deployment; `make bundle` + `bundle-verify` proves one.
- The shipped registry is empty on purpose; a fresh node grants nothing. Keys
  live in `$SPARKNET_STATE_DIR`, never in a vault; `make keys-check` and
  `make shims-check` are the hygiene gates.
- The live fleet uses iptables, not nftables; both AGX hosts use userspace WireGuard.

## Command gotchas
- Local gates are authoritative: `make ci` (or `CI_QUICK=1`), `make test-all`;
  a full `make ci` needs more than the default 120 s shell timeout. `gh` is at
  `~/.local/bin/gh`; a non-interactive PATH omits it.
- `make bundle-verify` checks only the newest archive; rebuild first. Never read
  large tool output through a pipe — redirect to a file. `make shellcheck`
  enforces its pinned version; the wiki suite resolves the nearest `.env`, so
  run `make wiki-preflight` first.

## Local vs live

This development host has no GPU and no overlay. Code, tests, contracts, the
ledger and bundles are verifiable here; WireGuard, iptables, `chattr +i`,
systemd, the signer and a live election are target-host checks. Say
"implemented and tested", "deployed live on <host> on <date>", or "unverified here".
