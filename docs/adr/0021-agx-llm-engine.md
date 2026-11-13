# 0021 — The AGX text engine is llama.cpp/llama-server, not vLLM

## Status

Proposed (2026-11-13; Step 107 knowledge capture). Implementation is Step 108.

## Context

The AGX node image (`goagx/sparknet.agx.docker`) builds **vLLM v0.2.7 from
source** on the L4T r35 base with torch 2.0.0, xformers 0.0.20, transformers
4.37.2 and Python 3.8, plus the L4T and xformers patches. The operator reports
that the vLLM requirements/dependencies cannot be fulfilled on the two AGX
Xavier hosts.

The audited hardware is:

- `agx64` — Master, **AGX Xavier 64 GB**, `sm_72`, L4T r35, MAXN.
- `agx32` — peer, **AGX Xavier 32 GB**, `sm_72`, L4T r35, MAXN.
- Unified memory bandwidth is ~136.5 GB/s; `sm_72` Volta Tensor Cores;
  `tegrastats` is the telemetry tool.

The current `goagx` page says 16 GB and an older log note says AGX Orin; the
audit above is the truth. The `goagx` distribution, `contracts/spark-node-runbook.md`
and the role manuals are corrected in Step 108.

The fabric has two model planes and they must stay distinct:

1. the **node's own AI stack** — Open WebUI, Ollama on 11434 and Qdrant
   (`peer-node/manifests/ai-stack.json`; the user's chat);
2. the **fabric text engine** — the `vllm` service on 8000, fronted by the
   agent/compute and used for delegated work and cluster jobs.

The text engine's service name, port 8000 and OpenAI-compatible endpoints are a
stable contract (`contracts/ports.json` 8000; `GOSPARK_GATEWAY_UPSTREAM` and
`VLLM_ENDPOINT`). The CPU `vllm-stub` is the no-GPU profile. The embed, rerank
and audio services (`vllm-embed`, `vllm-rerank`, `vllm-audio`) already use
llama.cpp/whisper.cpp and are separate from the text engine.

The resource-first review of [`dusty-nv`](https://github.com/dusty-nv) found the
maintained Jetson resource: **`jetson-containers`**, with `llama_cpp` (default
`b9016`) and `ollama` (0.23.0) packages, both L4T `>=34.1.0`. `llama.cpp` is
the most reliable GPU path and the widest model support; Ollama is the easy
OpenAI wrapper but its GPU build is harder; MLC-LLM, TensorRT-LLM, ExLlamaV2,
NanoLLM, text-generation-webui, SGLang and TGI are heavier or not drop-in for
this step. The full review is
[[dusty-nv-jetson-llm-containers-2026-11-13]].

## Decision

Replace the AGX **text engine** with a `jetson-containers` **`llama.cpp` /
`llama-server`** container, `sparknet-llm:agx`, as the primary path. Keep
**Ollama** as the fallback and as the peer's own AI-stack server.

- Keep the compose service name `vllm`, port **8000**, and the OpenAI endpoints
  `/v1/models`, `/v1/chat/completions`, `/health`; keep the `vllm-stub` CPU
  profile and the `vllm-embed`/`vllm-rerank`/`vllm-audio` aux services.
- Remove the vLLM source build, patches and Python stack from the node image.
  The node image keeps goSpark, the Python compute plane, the bundle, the aux
  engines and the stub; `sparknet-llm:agx` carries `llama-server` and the
  precontext.
- Inject the precontext through a thin OpenAI proxy in front of
  `llama-server`: it merges the MASTERSPIKE text + fabric digest into the first
  system message, and `llama-server --jinja` renders the model's own template.
  The source is `spark-precontext.py` (`digest` + MASTERSPIKE text) and the
  `masterspike` manifests. The b9016 build has no `--system-prompt-file` flag.
- **Teacher/main on `agx64`:** the largest Qwen model of the chosen version
  that fits 64 GB at the best responsive quantization, starting at **Q4_K_M**
  (Q5_K_M/Q6_K only if measured tokens/s is acceptable; Q8_0 only for a small
  model). Candidate: Qwen3.6-35B Q4_K_M.
- **Student on `agx32`:** the smallest Qwen model of the **same version**, at
  the best responsive quantization. The Qwen3.6 family has no 0.6B/1.7B
  release; its smallest model is **Qwen3.6-27B**, so the student is
  **Qwen3.6-27B Q4_K_M** (~17 GB). Fallback pair only if the teacher is
  switched to Qwen3: Qwen3-32B Q4_K_M + Qwen3-0.6B Q8_0. Retire the mismatched
  `qwen3.5-9b` / `qwen3.8-27b` pair.
- **Storage:** active teacher/student GGUF, tokenizer, precontext and KV cache
  on the root NVMe; the cold model store, vaults, uplift/distillation traces,
  HF cache and backups on the data drives; keys/state in the secure state dir
  on the root. The model container mounts only the root model directory.
- **Tuning:** `sm_72` (`CUDA_ARCHITECTURES=72`), Q4_K_M teacher, Q8_0/Q4_K_M
  student, `--n-gpu-layers 99`, `--ctx-size`/`--parallel` measured, MAXN
  (`sudo nvpmodel -m 0`, `sudo jetson_clocks`).

## Consequences

- The vLLM/PyTorch/xformers/CUDA dependency surface leaves the node image; the
  image build becomes much shorter and the failure mode is the Jetson
  `llama.cpp` build, not a Python extension build.
- The text engine gains a single C++/CUDA binary with an OpenAI API, the
  precontext controls and the GGUF model store.
- The `vllm` service name and `VLLM_*` environment names remain historical;
  the implementation maps `VLLM_MODEL`/`VLLM_PORT`/`VLLM_MAX_MODEL_LEN`/
  `VLLM_EXTRA_ARGS` to `llama-server` and adds an explicit model-file path.
- `model-catalog`, `agent-models`, `ai-stack`, `distillation-schema`,
  `model-store`, `goagx`, the runbook and the role manuals change in Step 108.
- The teacher/student pair becomes same-version, so the distillation is a clean
  tokenizer/family transfer; the teacher traces/uplift stay training data,
  never an answer corpus.
- The `jetson-containers` repository is `NOASSERTION`; `llama.cpp` and
  `llama-cpp-python` are MIT; no legal review was requested. No code is
  vendored; the images are built/pulled as containers.
- The live claim waits for Step 108: the teacher/student models load, the
  OpenAI endpoints answer, the precontext is present, the agent/compute path
  works, and the aux/stub paths still work on `agx64`/`agx32`.
- Rollback keeps the current vLLM image/service and the model store until the
  new path is validated; both images are tagged.

## Alternatives

- **vLLM** — rejected; the dependency build is the problem.
- **Ollama** — accepted as the fallback and the peer's own AI-stack server;
  its GPU build is harder and it is not the primary text engine.
- **MLC-LLM** — optional experiment; TVM compile; not the primary.
- **TensorRT-LLM** — NVIDIA-optimized but heavy; not the Xavier default.
- **ExLlamaV2** — EXL2/GPTQ, custom PyTorch; not for this step.
- **NanoLLM** — optimized local inference but not a drop-in OpenAI server.
- **text-generation-webui / SGLang / TGI** — heavier serving surfaces; not for
  this step.

## References

[[dusty-nv-jetson-llm-containers-2026-11-13]] · [[agx-llm-engine]] ·
[[agx-text-serving-options]] · [[dusty-nv]] · [[jetson-containers]] ·
[[0016-pin-agx-base-digest]] · [[0018-keep-gpu-embedder-behind-vllm-embed]] ·
`contracts/model-catalog.json` · `contracts/model-store.md` ·
`contracts/ports.json` (8000) · `contracts/spark-node-runbook.md` ·
`peer-node/manifests/agent-models.json` · `peer-node/manifests/ai-stack.json` ·
`goagx/sparknet.agx.docker` · `goagx/sparknet.agx.compose.yml`
