# sparknet — Session Memory
> Standing state only. Read at session start; **replace, never append**.
> History belongs in `log.md` and `sessions/YYYY-MM-DD.md`; pre-2026-10-31
> detail is in `_archives/MEMORY_FULL_2026-10-30.md`.
Updated: 2026-11-06
## Plan cursor
- `PLAN.md` — `current: 88` (role inversion: `agx64` Master / `agx32` peer; Step 89 is the Gemini blueprint adoption).
- Parked live legs: 84G browser click; 86C/86D full survey/promotion drill; 87 browser click-through; Master 9G nocturnal window.
- **Role inversion core live 2026-11-06:** root `c77a3446…` (epoch 1, parent `fa6f4fa5…`), registry sequence 9, signer on agx64. Old peer/master data copies removed, old units disabled, old keys retired; goSpark control on agx64, agent on agx32. Remaining: 88G loopback token rotation and browser click-through.
## Live fabric
- **`agx64` = Master = `sparknet-node-0001`** (`10.100.0.1/32`); **`agx32` = peer = `sparknet-node-0002`** (`10.100.0.2/32`). Overlay handshake both ways; peer overlay egress only to Master.
- Master on agx64: signer/ledger/parity, 8088 admin, 8098 console, 8090/8091 intake, 4220–4223, 4201/4202 share, 4204 engine, Qdrant 6333, teacher config.
- Peer on agx32: 9090 guard, 4096 bridge, 4201/4202 share, 4110/4093 memory, 8181 WebUI, 8099 console, 4204 engine, Qdrant 6333, student config.
- Data moved: user vaults/WebUI/Qdrant/memory to agx32; master-admin/WebUI/Qdrant/uplift/distill/ledger/evidence to agx64. RFI loop, telemetry, inventory (18 records), admin federation and memory_status verified live 2026-11-06; old copies removed after verification.
- **Teacher/student:** agx64 teacher Qwen3.6-35B-A3B Q4_K_M via Ollama (22.2 tok/s, 21.2 GiB, 100%); agx32 student Qwen3.5-9B Q8 (11.3 tok/s, 8.1 GiB, 100%); 27B Q4 slower (4.75 tok/s). vLLM/aux stopped; Qwen3.8-Flash-Next blocked on qwen4exp.
- **WebUI/OpenCode live 2026-11-05:** both nodes run Open WebUI `v0.13.0`; the peer is the user surface on agx32, the Master is admin-only on agx64; the loopback OpenCode engine (`4204`) runs one vault-only sandbox per user. The live sandbox is now `2.2.5` on agx64/agx32 (rebuilt 2026-11-06); peer and Master chat returned `OK` with HTTP 200. Browser click-through remains.
- **Memory/evidence live 2026-11-04:** memory `4110`/gateway `4093` now on agx32; Master `memory_status`/`memory-read` 200; registry sequence 9; share/evidence preserved.
## Durable facts
- **Memory plane (2026-11-02):** per-vault typed memory runs in Go
  (`sparknet-memory`, `4110`) behind the Python gateway (`4093`); OpenCode and
  Open WebUI share one store. `memory-supervise` is on-demand; no mirror.
- Qdrant is the vector store (loopback 6333/6334); 4223 is its only signed
  surface. ChromaDB is retired.
- `model-uplift` is the peer-held capability for consented inventory, snapshots,
  traces and KV manifests on 8091; uplift is training data, never an answer corpus.
- A peer is the user's node; a Master supplies authority and scoped knowledge.
  Authority and knowledge never share a channel.
- `shared/sparknet-authz.py` is the one signed-authorization implementation.
  Never copy it; `../shared` is loaded by path where needed.
- A role subvault is not a deployment; `make bundle` + `bundle-verify` proves one.
- The registry ships empty; a fresh node grants nothing. Keys live in `$SPARKNET_STATE_DIR`; `make keys-check`/`shims-check` are hygiene gates.
- The live fleet uses iptables, not nftables; both AGX hosts use userspace WG.
- `contracts/model-catalog.json`: teacher only on `agx64`, student only on
  `agx32`; teacher backup forbidden. `sparknet-model-runtime.py` leases on demand.
## Command gotchas
- `make ci`/`make test-all` are authoritative; a full run needs >120 s.
  Rebuild before `bundle-verify`; run `wiki-preflight` before the wiki suite.
- A long-running service loads `shared/sparknet-authz.py` once at start. After a
  capability is added, restart the consumer or a valid registry entry is refused
  as `unknown_capability`. The agx64 bridge was restarted 2026-11-03 for this.
- OpenCode v2 certification: `make -C peer-node opencode-certify` downloads the
  pinned binary, starts a real server and proves auth, session, SSE and interrupt.
## Local vs live
This development host has no GPU and no overlay. Code, tests, contracts, the
ledger and bundles are verifiable here; WireGuard, iptables, `chattr +i`,
systemd, the signer and a live election are target-host checks. Say
"implemented and tested", "deployed live on <host> on <date>", or "unverified here".
