---
title: jetson-containers
updated: 2026-11-13
type: entity
source: https://github.com/dusty-nv/jetson-containers
license: NOASSERTION (repository); llama.cpp/llama-cpp-python MIT; NVIDIA L4T base under its own terms
---

# jetson-containers

The modular machine-learning container build system for NVIDIA Jetson and
JetPack-L4T, maintained by [[dusty-nv]]. It is the existing resource behind the
AGX Xavier text-engine migration.

## What it provides

- `packages/llm/llama_cpp` — `llama.cpp` and `llama-cpp-python`; default
  `b9016`; CUDA build with `GGML_CUDA=ON`, `GGML_CUDA_F16=ON`,
  `LLAMA_CURL=ON`, `LLAMA_OPENSSL=ON`, `GGML_CUDA_FA_ALL_QUANTS=ON`;
  `CUDA_ARCHITECTURES` from the host; `llama-server`; L4T `>=34.1.0`.
- `packages/llm/ollama` — Ollama 0.23.0 default; Go + CUDA build;
  `OLLAMA_HOST=0.0.0.0`; `OLLAMA_MODELS=/data/models/ollama/models`;
  `/start_ollama`; L4T `>=34.1.0`.
- `packages/llm/mlc`, `vllm`, `nano_llm`, `text-generation-webui`,
  `transformers`, `sglang`, `tensorrt_edgellm` — reviewed alternatives; not the
  primary path for this migration.
- `autotag`/`build` resolve the L4T-compatible image or build it on the host.

## Use in this fabric

- `agx64` (64 GB): `llama.cpp` / `llama-server` for the Qwen teacher/main.
- `agx32` (32 GB): `llama.cpp` / `llama-server` for the Qwen student and text
  engine; `ollama` for the peer's own AI stack and fallback.
- The `vllm` compose service name and port 8000 stay stable; the new image is
  `sparknet-llm:agx`; the `vllm-stub` CPU profile stays.
- Build with `CUDA_ARCHITECTURES=72` for the AGX Xavier; use Q4_K_M for the
  teacher, Q8_0/Q4_K_M for the small student; set MAXN before inference.

The exact package/image tags and the build validation are Step 108 work. The
source review, licenses and the full repository inventory are in
[[dusty-nv-jetson-llm-containers-2026-11-13]].

## Related

[[dusty-nv]] · [[dusty-nv-jetson-llm-containers-2026-11-13]] ·
[[0021-agx-llm-engine]] · [[agx-llm-engine]] · [[agx-text-serving-options]]
