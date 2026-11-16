# sparknet — Session Memory
> Standing state only. Read at session start; **replace, never append**.
> History belongs in `log.md` and `sessions/YYYY-MM-DD.md`.
Updated: 2026-11-16
## Plan cursor
- `PLAN.md` — `current: 113` (federated admin identity + offline break-glass;
  **live 2026-11-16** on agx32/agx64/0003 for the admin client-certificate and
  signed-assertion paths: Dex 9443 + lldap, Master SSO 8092, peer admin 8182,
  `/nodes/` 200 for 0002/0003, user 8181 unchanged, offline-repair simulation
  accepted with `applied: false`. OIDC browser login via oauth2-proxy, live IdP
  role propagation and signed `bundle-verify` remain).
  `master-node/PLAN.md` — `current: done` with a Step 113 pointer.
- #8/#9/#11 closed with dated agx32/agx64 evidence (0 open).
## Live fabric
- **`agx32` = Master = `sparknet-node-0001` (`10.100.0.1/32`, `blue-team`),
  AGX Xavier 32 GB, `sm_72`, L4T r35, MAXN; `agx64` = peer =
  `sparknet-node-0002` (`10.100.0.2/32`, `red-team`), AGX Xavier 64 GB,
  `sm_72`, L4T r35, MAXN; `sparknet-node-0003` = peer on `vmx`
  (`10.100.0.3/32`, Ubuntu 26.04 VM, 4 vCPU/12 GiB).** Direct `eth0`
  `10.99.0.0/30` carries `wg1`; 0003 joins over the LAN/vmx host DNAT.
- **Third node 2026-11-15:** `sparknet-node-0003` on `vmx` joined the pair.
  Final root `9157113f…` (1.3, epoch 4, master `0001`, prev `2dfc07db…`);
  registry sequence `12`; WG keys rotated on `0001/0002`; all three hold the
  child `trust_root`. `agx64` uses `dJcT…` for 0002, not peer-state `G08…`.
- Text engine: **llama.cpp/llama-server** (`sparknet-llm:agx`) live on
  `agx64`/`agx32` 2026-11-13; ADR 0021 accepted; vLLM retired. Ollama is the
  fallback and peer AI-stack server; MLC-LLM optional; TensorRT-LLM/ExLlamaV2
  not the path. `vllm:8000`, `vllm-stub`, aux embed/rerank/audio stay.
- Peer `agx64`: Qwen3-30B-A3B-2507 Q4_K_M; Master `agx32`: Qwen3-4B-2507
  Q4_K_M; both 262k q8 KV. Peer Ollama has coder/VL tags; embedding is CPU
  `:8001` on both. Qwen3.6 and old Qwen3 sets cold.
- **Auto-distill 2026-11-15:** 16k bundle `sparknet-distill-e69b5e6f6247110d-20261115T024212Z.tar.gz` (sha256 `9d28…`) from the current 24-trace dataset; external GPU still missing. `raxxaramd` is online as a general x86 VM/build node (`.107` via WiFi, `agx32` trainer key installed, Tailscale boot-before-login verified), but its GTX 1650M 4 GB has no driver/CUDA and is **not** the 16k trainer. agx64 llama.cpp is full-finetune, not 16k QLoRA. Peer Qdrant 1247/1024; embedding `:8001`; cron 03:15; trainer Python 3.8.
- **Storage:** vaults/data on `/mnt/ai`; active GGUF/KV on `/opt/sparknet/models`;
  keys/state on root; model containers mount only the root model dir.
- **Tuning:** `sm_72`; Q4_K_M teacher, Q4_K_M/Q8_0 student; `--n-gpu-layers
  99`; `--no-mmap --fit off` for the 27B; MAXN; `tegrastats`; 136.5 GB/s.
- **Router 2026-11-14:** model router `8101` (local + signed support),
  resource directory `8089`, memory router `4094`; user data is refused remotely.
  goagx pinned `dd64bfd`; goSpark spec `85815b3`; signed resource directory refreshes on demand.
## Durable facts
- Human identity is federated: Master-hosted IdP (`sparknet-admins` /
  `sparknet-users`), node auth gateway trusted headers, offline admin mTLS
  break-glass, per-node signed role overrides. Authentication, never a fabric
  capability; the signed admin console is retained for audited actions.
- Live admin identity 2026-11-16: Dex `10.100.0.1:9443`, Master SSO
  `10.100.0.1:8092`, peer admin `10.100.0.2:8182` and `10.100.0.3:8182`
  (overlay + LAN); user ingresses remain 8181. Admin cert/key and the lldap
  human password live under `~/.local/state/sparknet/master-node/identity/`
  on agx32 (0600); never copy them into the tree.
- Memory plane: Go `sparknet-memory` 4110 behind Python gateway 4093; one store, per-vault scope; Qdrant 6333/6334; 4223 the only signed surface.
- `model-uplift` carries consented training/backup evidence only, never answers; teacher traces/uplift are not an answer corpus.
- One `shared/sparknet-authz.py`; a role subvault is not a deployment (`make bundle` + `bundle-verify`); keys live in `$SPARKNET_STATE_DIR` at 0700/0600.
- Cluster root 1.3 is live: `9157113f…` epoch 4 names 0001/0002/0003; Master unchanged; 0003 peer at `10.100.0.3`; CPU llama.cpp + Open WebUI stack live.
- Live fleet uses iptables and userspace WireGuard; registry ships empty.
- Understand graph is a build artifact (`.ua/`); issues are work items (`.scratch/issues/`); neither is knowledge or authority.
- Skill-eval: `contracts/skill-eval-schema.json` + `shared/sparknet-skill-eval.py` is the one digest-bound record; audit evidence, never authority or knowledge.
- Skill access: `.opencode/skills/.catalog.json` (base/peer/master) + the read-only MCP; `permission.skill` advertises the featured set only.
- Architecture decisions: 0009 issue, 0010 skill catalog, 0011 core split, 0013 sandbox policy, goSpark 0018 graph, 0019 eval audit, 0020 skill access, 0021 AGX text engine.
- Base skill tree: 81 skills; role catalogs peer 125 / master 1614.
- AGX text-engine pages: ADR 0021; `references/dusty-nv-jetson-llm-containers-2026-11-13`; `concepts/agx-llm-engine`; `synthesis/agx-text-serving-options`.
## Security hardening 2026-11-08
- Signer live on agx32; operational key 0600, ledger verifies, socket allowlisted; goSpark pinned mTLS and bearer-gated admin.
- 2026-11-15: WG private keys were exposed during live inspection. WG keypairs on agx32/agx64 were rotated; per-peer PSKs are applied on all three links and the old keys are no longer active.
## Command gotchas
- `make ci`/`make test-all` are authoritative; full run >120 s.
- Rebuild before `bundle-verify`; run `wiki-preflight` before wiki suite.
## Local vs live
This development host has no GPU/overlay. Code, tests, contracts, ledger and
bundles are verifiable here; WireGuard, iptables, `chattr +i`, systemd, signer
and live election are target-host checks. The AGX runtime/model/storage claims
are dated target-host checks from 2026-11-13, not this host.
