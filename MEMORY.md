# sparknet — Session Memory
> Standing state only. Read at session start; **replace, never append**.
> History belongs in `log.md` and `sessions/YYYY-MM-DD.md`.
Updated: 2026-11-13
## Plan cursor
- `PLAN.md` — `current: 111` (Step 108 engine + Step 109 bake-off done;
  Step 110 Qwen3-2507 stack done; Step 111 auto-distill blocked on
  Qwen3/Python 3.8 trainer). `master-node/PLAN.md` — `current: done`.
- #8/#9/#11 closed with dated agx32/agx64 evidence (0 open).
## Live fabric
- `agx64` = Master = `sparknet-node-0001` (`10.100.0.1/32`, `red-team`),
  **AGX Xavier 64 GB**, `sm_72`, L4T r35, MAXN; `agx32` = peer =
  `sparknet-node-0002` (`10.100.0.2/32`, `blue-team`), **AGX Xavier 32 GB**,
  `sm_72`, L4T r35, MAXN. Peer egress only to Master; overlay `wg1`.
- 9G window 2026-11-13 02:00–02:10: plan/arm/lease, signed eval job,
  `network_evals fail:1`, no promotion; abort. Cluster execute, wg observer and
  idle-ignore remain enabled. Model-prompt job not claimed (Ollama upstream).
- Text engine: **llama.cpp/llama-server** (`sparknet-llm:agx`) live on
  `agx64`/`agx32` 2026-11-13; ADR 0021 accepted; vLLM retired. Ollama is the
  fallback and peer AI-stack server; MLC-LLM optional; TensorRT-LLM/ExLlamaV2
  not the path. `vllm:8000`, `vllm-stub`, aux embed/rerank/audio stay.
- Main/teacher `agx64`: Qwen3-30B-A3B-2507 Q4_K_M. Student `agx32`:
  Qwen3-4B-2507 Q4_K_M; both 262k q8 KV. 4B candidate synced to agx64.
  Qwen3.6 and old Qwen3 sets cold. Peer: Qwen3-Coder-30B 65k,
  Qwen3-Embedding-0.6B, Qwen3-VL-4B in Ollama.
- **Auto-distill 2026-11-14:** dataset/collect/doctor/8091 upload/sync work;
  training is blocked because the L4T r35 image is Python 3.8 /
  transformers 4.37.2 and Qwen3 needs >=4.51 (Python >=3.9).
- **Storage:** vaults on `/mnt/ai/...`; active GGUF/tokenizer/precontext/KV
  on root `/opt/sparknet/models/...`; cold store/HF cache/uplift/distill/
  Qdrant snapshots/backups on data; keys/state on root. `agx64` root 114 GB,
  data 1.4 TB; `agx32` root 790 GB, data 130 GB. Model container mounts only
  the root model dir.
- **Tuning:** `sm_72`; Q4_K_M teacher, Q4_K_M/Q8_0 student; `--n-gpu-layers
  99`; `--no-mmap --fit off` for the 27B; MAXN; `tegrastats`; 136.5 GB/s.
  goagx pinned `07e9dda`.
## Durable facts
- Memory plane: Go `sparknet-memory` 4110 behind Python gateway 4093; one store, per-vault scope; Qdrant 6333/6334; 4223 the only signed surface.
- `model-uplift` carries consented training/backup evidence only, never answers; teacher traces/uplift are not an answer corpus.
- One `shared/sparknet-authz.py`; a role subvault is not a deployment (`make bundle` + `bundle-verify`); keys live in `$SPARKNET_STATE_DIR` at 0700/0600.
- Live fleet uses iptables and userspace WireGuard; registry ships empty.
- Understand graph is a build artifact (`.ua/`); issues are work items (`.scratch/issues/`); neither is knowledge or authority.
- Skill-eval: `contracts/skill-eval-schema.json` + `shared/sparknet-skill-eval.py` is the one digest-bound record; audit evidence, never authority or knowledge.
- Skill access: `.opencode/skills/.catalog.json` (base/peer/master) + the read-only MCP; `permission.skill` advertises the featured set only.
- Architecture decisions: 0009 issue, 0010 skill catalog, 0011 core split, 0013 sandbox policy, goSpark 0018 graph, 0019 eval audit, 0020 skill access, 0021 AGX text engine.
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
are dated target-host checks from 2026-11-13, not this host.
