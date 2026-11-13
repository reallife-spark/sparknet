# sparknet — Session Memory
> Standing state only. Read at session start; **replace, never append**.
> History belongs in `log.md` and `sessions/YYYY-MM-DD.md`.
Updated: 2026-11-13
## Plan cursor
- `PLAN.md` — `current: 108` (Step 107 knowledge capture complete; Step 108
  `sparknet-llm`/`llama.cpp` next). `master-node/PLAN.md` — `current: done`
  (9G live window 2026-11-13).
- #8/#9/#11 closed with dated agx32/agx64 evidence (0 open). Next: Step 108
  `sparknet-llm`/`llama.cpp`, sandbox 20E/20F, Step 10 4203 third host, Phase 9.
## Live fabric
- `agx64` = Master = `sparknet-node-0001` (`10.100.0.1/32`, `red-team`),
  **AGX Xavier 64 GB**, `sm_72`, L4T r35, MAXN; `agx32` = peer =
  `sparknet-node-0002` (`10.100.0.2/32`, `blue-team`), **AGX Xavier 32 GB**,
  `sm_72`, L4T r35, MAXN. Peer egress only to Master; overlay `wg1`.
- 9G window 2026-11-13 02:00–02:10: plan/arm/lease, signed eval job,
  `network_evals fail:1`, no promotion; abort. Cluster execute, wg observer and
  idle-ignore remain enabled. The model-prompt job is not claimed (Ollama
  upstream down); Step 108's `llama.cpp` path is the replacement.
- Text engine: **vLLM v0.2.7 today**; ADR 0021 (proposed) replaces it with
  `jetson-containers` `llama.cpp`/`llama-server` (`sparknet-llm:agx`); Ollama
  is the fallback and the peer's own AI-stack server; MLC-LLM optional;
  TensorRT-LLM/ExLlamaV2/vLLM not the path. `vllm:8000`, `vllm-stub` and the
  aux embed/rerank/audio stay.
- Teacher/main on `agx64`: Qwen3.6-35B Q4_K_M (largest same-version that fits
  64 GB at the best responsive quantization). Student on `agx32`:
  Qwen3.6-0.6B Q8_0 (smallest same-version; 1.7B if too weak). Fallback
  Qwen3-32B Q4_K_M + Qwen3-0.6B Q8_0. Old `qwen3.5-9b`/`qwen3.8-27b` retired.
- **Storage:** vaults on the data drives (`/mnt/ai/...`); active
  teacher/student GGUF/tokenizer/precontext/KV on the root NVMe
  (`/opt/sparknet/models/...`); cold store/HF cache/uplift/distill/Qdrant
  snapshots/backups on the data; keys/state on the root. `agx64` root 137 GB,
  data 1.4 TB; `agx32` root 808 GB, data 131 GB. Model container mounts only
  the root model dir.
- **Tuning:** `sm_72` (`CUDA_ARCHITECTURES=72`); Q4_K_M teacher, Q8_0/Q4_K_M
  student; `--n-gpu-layers 99`; measured ctx/parallel; MAXN (`nvpmodel -m 0`,
  `jetson_clocks`); `tegrastats`; 136.5 GB/s. goagx pinned `4563567`; disk,
  agents and secrets are in `sessions/2026-11-12.md`.
## Durable facts
- Memory plane: Go `sparknet-memory` 4110 behind Python gateway 4093; one store, per-vault scope; Qdrant 6333/6334; 4223 the only signed surface.
- `model-uplift` carries consented training/backup evidence only, never answers; teacher traces/uplift are not an answer corpus.
- One `shared/sparknet-authz.py`; a role subvault is not a deployment (`make bundle` + `bundle-verify`); keys live in `$SPARKNET_STATE_DIR` at 0700/0600.
- Live fleet uses iptables and userspace WireGuard; registry ships empty.
- Understand graph is a build artifact (`.ua/`); issues are work items (`.scratch/issues/`); neither is knowledge or authority.
- Skill-eval: `contracts/skill-eval-schema.json` + `shared/sparknet-skill-eval.py` is the one digest-bound record; audit evidence, never authority or knowledge.
- Skill access: `.opencode/skills/.catalog.json` (base/peer/master) + the read-only MCP; `permission.skill` advertises the featured set only.
- Architecture decisions: 0009 issue, 0010 skill catalog, 0011 core split, 0013 sandbox policy, goSpark 0018 graph, 0019 eval audit, 0020 skill access, 0021 AGX text engine (proposed).
- Base skill tree: 81 skills; role catalogs peer 125 / master 1614.
- AGX text-engine pages: ADR 0021; `references/dusty-nv-jetson-llm-containers-2026-11-13`; `concepts/agx-llm-engine`; `synthesis/agx-text-serving-options`.
## Security hardening 2026-11-08
- Signer live on agx64; operational key 0600, socket 0660/allowlist, 54-block ledger verified; goSpark pinned mTLS and bearer-gated admin.
## Command gotchas
- `make ci`/`make test-all` are authoritative; full run >120 s.
- Rebuild before `bundle-verify`; run `wiki-preflight` before wiki suite.
## Local vs live
This development host has no GPU/overlay. Code, tests, contracts, ledger and
bundles are verifiable here; WireGuard, iptables, `chattr +i`, systemd, signer
and live election are target-host checks. The AGX runtime/model/storage claims
are Step 108 target-host checks, not this host.
