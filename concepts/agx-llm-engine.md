---
title: AGX LLM engine
updated: 2026-11-13
type: concept
---

# AGX LLM engine

How the two AGX Xavier nodes serve language models, and where the boundary
between the node's own chat plane and the fabric's text engine sits. The
decision to replace vLLM with `llama.cpp` is [[0021-agx-llm-engine]]; the
source review is [[dusty-nv-jetson-llm-containers-2026-11-13]].

## Two model planes, not one

A node has two model-serving surfaces. They share the model store and the
hardware, but they are different contracts.

| Plane | What it serves | Default surface | Authority |
|---|---|---|---|
| Node's own AI stack | the user's chat: Open WebUI, the student/chat model, Qdrant RAG | Ollama `127.0.0.1:11434`; Open WebUI `8181`/`8180`; Qdrant `6333` | none; it is the user's local AI |
| Fabric text engine | delegated work: agent/compute, cluster jobs, the `vllm` service | OpenAI-compatible `vllm:8000`; `/v1/models`, `/v1/chat/completions`, `/health` | none; the model is compute, not authority |

The `peer-node/manifests/ai-stack.json` owns the first plane. The
`goagx` compose, `contracts/ports.json` 8000 and the `GOSPARK_GATEWAY_UPSTREAM`
/ `VLLM_ENDPOINT` wiring own the second. The two must not be conflated: a
failure of the chat plane is not a failure of the text engine, and the text
engine never becomes a knowledge channel.

## The service contract

- Compose service name: `vllm`; host/container port **8000**; the OpenAI
  endpoints above; the `vllm-stub` CPU profile for `--engine stub`.
- `VLLM_MODEL` is the model alias; `VLLM_PORT` the port;
  `VLLM_MAX_MODEL_LEN` maps to `llama-server --ctx-size`; `VLLM_EXTRA_ARGS`
  passes extra `llama-server` flags; the explicit GGUF path is
  `SPARKNET_LLM_MODEL_FILE`.
- The `vllm-embed` (8001), `vllm-rerank` (8002) and `vllm-audio` (8003) aux
  services are separate; they already use llama.cpp/whisper.cpp and stay on the
  node image. The names are historical, not a vLLM dependency.
- The `vllm-stub` is the deterministic CPU OpenAI stub; it keeps the
  agent ↔ engine ↔ compute path testable with no GPU/model.

## Runtime selection

| Host | Runtime | Model | Why |
|---|---|---|---|
| `agx64` (64 GB) | **llama.cpp / `llama-server`** (CUDA, `sm_72`) | teacher/main Qwen3.6-35B Q4_K_M (fallback Qwen3-32B Q4_K_M) | most reliable GPU path; OpenAI API; precontext; 64 GB |
| `agx32` (32 GB) | **llama.cpp / `llama-server`** for the text engine; **Ollama** for the node's own AI stack and fallback | student Qwen3.6-27B Q4_K_M (the smallest Qwen3.6 release; fallback Qwen3-0.6B only with a Qwen3 teacher) | same engine/API as the teacher; Ollama is the peer's simple chat plane |

Ollama is the fallback and the peer's own chat server; MLC-LLM is an optional
experiment. TensorRT-LLM, ExLlamaV2, text-generation-webui, SGLang, TGI and
vLLM are not the path for these Xavier nodes. The exact same-version pair is
confirmed after the model inventory: Qwen3.6-35B-A3B Q4_K_M (teacher) and
Qwen3.6-27B Q4_K_M (student).

## Model store and precontext

- **Active teacher/student** GGUF, tokenizer, model config, precontext and KV
  cache: root NVMe (`/opt/sparknet/models/...`) for fast load.
- **Cold model store**, HF download cache, uplift/distillation traces, Qdrant
  snapshots and backups: data drives (`/mnt/ai/...`).
- **Vaults** (fabric, role, per-user) stay on the data drives; the model
  container never mounts a vault.
- **Keys/state** stay in the secure state dir on the root (0700/0600); no model
  container mounts the state dir.
- The precontext is the MASTERSPIKE format + fabric digest from
  `spark-precontext.py`, injected as the system/chat template. It carries the
  fabric vocabulary and format, never a capability or a secret.

## Image split

The node image and the text-engine image have different jobs:

| Image | Contains | Does not contain |
|---|---|---|
| `sparknet-agx-node` | goSpark binaries, Python compute, the bundle, the aux llama.cpp/whisper.cpp, the `vllm-stub` | the vLLM source build/patches, torch/xformers, the teacher/student GGUF |
| `sparknet-llm:agx` | `llama-server` from `jetson-containers` `llama_cpp`, the precontext entrypoint, the model mount | the fabric vault, keys, signer, ledger, the aux services |

The `vllm` compose service uses `sparknet-llm:agx`; the CPU overlay uses the
node image's `vllm-stub`. The aux services stay on the node image.

## Performance rules

- Target **`sm_72`** (`CUDA_ARCHITECTURES=72`); do not leave the CUDA
  architecture on auto-detect.
- **Q4_K_M** for the 32B/35B teacher; Q5_K_M/Q6_K only if the measured
  tokens/s is acceptable; Q8_0/Q4_K_M for the small student.
- **MAXN** before inference: `sudo nvpmodel -m 0`; `sudo jetson_clocks`.
- Use `--n-gpu-layers 99`, a measured `--ctx-size`/`--parallel`, and watch
  `tegrastats`; the 136.5 GB/s memory bandwidth is the bottleneck.

## Failure modes and boundaries

- Model load/OOM: check the root model file, the context/KV size and the
  unified memory; fall back to a lower quantization or the smaller model.
- Missing precontext: `llama-server` can serve without it, but the fabric
  format is lost; fix the precontext file, do not silently accept the default.
- Text-engine failure: the node's own chat plane (Ollama/Open WebUI) can keep
  working; the agent/compute path reports the engine error.
- The teacher traces/uplift are training evidence, never an answer corpus; the
  model store is not a vault; the precontext is not authority.

## Related

[[0021-agx-llm-engine]] · [[agx-text-serving-options]] ·
[[dusty-nv-jetson-llm-containers-2026-11-13]] · [[jetson-containers]] ·
`contracts/model-catalog.json` · `contracts/model-store.md` ·
`contracts/ports.json` (8000) · `peer-node/manifests/ai-stack.json` ·
`peer-node/manifests/agent-models.json` · `goagx/sparknet.agx.compose.yml`
