---
title: dusty-nv
updated: 2026-11-13
type: entity
source: https://github.com/dusty-nv
license: per repository — see the reference review
---

# dusty-nv

The GitHub user behind the Jetson AI container and tutorial ecosystem used as
the resource-first reference for the AGX Xavier text-engine migration.

## Why this entity matters here

The fabric needed a Jetson-compatible replacement for the vLLM source build on
`agx64`/`agx32` (AGX Xavier, `sm_72`, L4T r35, 64 GB / 32 GB). `dusty-nv`'s
repositories contain the maintained Jetson container build system and the
runtime recipes that avoid the vLLM Python/PyTorch/xformers stack.

## Relevant repositories

| Repository | Use |
|---|---|
| [`jetson-containers`](https://github.com/dusty-nv/jetson-containers) | Primary resource: `llama_cpp`/`ollama` packages, `autotag`/`build`, L4T support |
| [`NanoLLM`](https://github.com/dusty-nv/NanoLLM) | Optimized local inference; alternative, not a drop-in OpenAI server |
| [`llama.cpp`](https://github.com/dusty-nv/llama.cpp) / [`llama-cpp-python`](https://github.com/dusty-nv/llama-cpp-python) | Engine and bindings behind `llama_cpp` |
| [`jetson-ai-lab`](https://github.com/dusty-nv/jetson-ai-lab) / [`gpt-llm-lab`](https://github.com/dusty-nv/gpt-llm-lab) | LLM recipes and tutorials |
| `MLC`, `text-generation-webui`, `vLLM`, `SGLang`, `TGI`, `TensorRT-Edge-LLM` | Packages/alternatives reviewed; not the primary path |
| The remaining ~60 repositories | CV, robotics, ROS, TensorRT vision, simulation, forks — not relevant to the text engine |

The full 74-repository inventory and the per-repository verdicts are in
[[dusty-nv-jetson-llm-containers-2026-11-13]].

## Verdict

Use `jetson-containers` as the existing Jetson resource; use `llama.cpp` /
`llama-server` as the primary runtime and `ollama` as the fallback. No code is
vendored; the licenses are recorded in the reference page.

## Related

[[dusty-nv-jetson-llm-containers-2026-11-13]] · [[jetson-containers]] ·
[[0021-agx-llm-engine]] · [[agx-llm-engine]] · [[agx-text-serving-options]]
