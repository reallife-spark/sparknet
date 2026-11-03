# sparknet — Session Memory

> Standing state only. Read at session start; **replace, never append**.
> History belongs in `log.md` and `sessions/YYYY-MM-DD.md`; pre-2026-10-31
> detail is in `_archives/MEMORY_FULL_2026-10-30.md`.

Updated: 2026-11-02

## Plan cursor
- `PLAN.md` — read its `current:` field; role plans own role work.
## Live fabric
- **`agx64` = peer = `sparknet-node-0001`** (`10.100.0.2/32`); **`agx32` =
  master = `sparknet-node-0002`** (`10.100.0.1/32`). Trust root `fa6f4fa5…`;
  election 2026-10-07, re-formed 2026-10-19, overlay survives reboot.
- Admin surface on agx32 at `10.100.0.1:8088`; Peer AI: Open WebUI on
  `agx64:8181`, Ollama, Qdrant (loopback).
- Live: provisioning/admin ingestion, RFI loop, bridge `vault.rfi`,
  telemetry/checkpoints, self-healing, admin federation, registry re-delivery.
- Qdrant `v1.20.0` loopback on both; 4 KBs/107 files reindexed; 4223 serves
  Qdrant; Chroma stopped (volume kept 14 days).
- Uplift: 41 inventory records mirrored; four snapshots uploaded, one restored;
  one Qwen2.5-7B→1.5B LoRA signed (`run-20261101T101033Z-…`, 0.2226); raw KV
  299 blocks/627 MB pushed (sha256 `f2ece221…`). 4220/4221/4222 live; 4203
  staged; Phase 9 live-restored 2026-11-01.
- User key re-keyed on agx64; `U-27689` and 9 notes preserved.
- **Teacher/student live 2026-11-01:** agx64 Qwen3.6-35B-A3B Q4_K_M via Ollama
  (22.2 tok/s, 21.2 GiB, 100%); agx32 Qwen3.5-9B Q8 (11.3 tok/s, 8.1 GiB,
  100%); 27B Q4 imported but slower (4.75 tok/s). vLLM/aux stopped because
  Q4_K_M + vLLM does not fit; Qwen3.8-Flash-Next blocked on qwen4exp.
- **WebUI console live 2026-11-01:** nginx fronts Open WebUI on agx64:8181 and
  agx32:10.100.0.1:8088, injects the Sparknet launcher and proxies
  `/sparknet-console/` to loopback 8099/8098; Mesh/Qdrant/3D pilot APIs 200.
  User units `sparknet-console@peer|master` persist it; the Master's
  `sparknet-distill-status.timer` writes a sanitized 5-run snapshot; browser
  confirmation remains 84G.
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
## Local vs live
This development host has no GPU and no overlay. Code, tests, contracts, the
ledger and bundles are verifiable here; WireGuard, iptables, `chattr +i`,
systemd, the signer and a live election are target-host checks. Say
"implemented and tested", "deployed live on <host> on <date>", or "unverified here".
