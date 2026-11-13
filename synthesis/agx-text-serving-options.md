---
title: AGX text-serving options
updated: 2026-11-13
type: synthesis
---

# AGX text-serving options

A cross-cut of the runtime choices for the AGX Xavier text engine, the
`jetson-containers` resource review, and the teacher/student model rule. The
decision is [[0021-agx-llm-engine]]; the operating model is
[[agx-llm-engine]]; the source review is
[[dusty-nv-jetson-llm-containers-2026-11-13]].

## The comparison

| Framework | Format | Setup | Xavier fit | Verdict |
|---|---|---|---|---|
| **llama.cpp / `llama-server`** | GGUF | moderate CUDA build | `sm_72`, CUDA, OpenAI API, `--jinja`/template/system-prompt, Q4_K_M | **Primary**; most reliable GPU path and widest model support |
| **Ollama** | GGUF | easy CPU, hard GPU build | llama.cpp backend; simple OpenAI; model store | **Fallback**; the peer's own AI-stack server |
| **MLC-LLM** | MLC/TVM | hard compile | low-overhead OpenAI serving; TVM | optional experiment |
| **TensorRT-LLM** | TensorRT | heavy; INT4/INT8 | NVIDIA-optimized but large | not for the Xavier |
| **ExLlamaV2** | EXL2/GPTQ | hard custom PyTorch | max 4-bit speed | not for this step |
| **NanoLLM** | Python API | moderate | optimized local inference; not OpenAI | alternative, not drop-in |
| **text-generation-webui** | PyTorch | heavy | OpenAI extension | not for the text engine |
| **SGLang / TGI** | Python/CUDA | heavy | high-throughput | not for the Xavier |
| **vLLM** | PyTorch/CUDA/triton | heavy; the current build is the problem | the existing engine | **retire** |

The decisive facts are the **136.5 GB/s** unified-memory bandwidth, `sm_72`,
L4T r35 and the operator's inability to satisfy vLLM's Python/torch/xformers
stack. `llama.cpp` is the least dependency-heavy GPU path and the most
reliable; Ollama wraps the same llama.cpp backend with an easy API but a harder
GPU build. The aux services already use llama.cpp/whisper.cpp, so the text
engine joins an existing runtime family rather than introducing a new one.

## Why not vLLM

vLLM is the current text engine. Its `goagx` build compiles vLLM v0.2.7 from
source with torch 2.0.0, xformers 0.0.20, transformers 4.37.2, Python 3.8 and
the L4T/xformers patches. The dependency surface is the problem, not the
OpenAI contract: the `vllm` service name/port and the OpenAI endpoints stay.

## Why not the other edge frameworks

- **MLC-LLM** has a clean OpenAI server (`mlc_llm serve`) but a TVM compile
  step and a separate model format; it is an optional experiment, not the
  first migration.
- **TensorRT-LLM** is NVIDIA's optimized stack, but it is a heavy build and
  its Xavier fit is not the default; INT4/INT8 would be required for the larger
  teacher and the engine build surface is larger than the benefit here.
- **ExLlamaV2** targets EXL2/GPTQ and a custom PyTorch build; the Xavier
  dependency risk is exactly what this migration avoids.
- **NanoLLM** is optimized local inference, but it is a Python API, not a
  drop-in OpenAI server.
- **text-generation-webui / SGLang / TGI** add UI or high-throughput serving
  surfaces that the node does not need.

## Model rule and memory

Same Qwen version for teacher and student; the tokenizer/family must match so
distillation is a clean transfer.

- **Teacher/main on `agx64` (64 GB):** largest same-version model that fits at
  the best responsive quantization; **Q4_K_M** first; Q5_K_M/Q6_K only if the
  measured tokens/s is acceptable; Q8_0 only for a small model.
- **Student on `agx32` (32 GB):** smallest same-version model at **Q8_0**
  (Q4_K_M if needed).
- Candidate: **Qwen3.6-35B Q4_K_M + Qwen3.6-0.6B Q8_0**; fallback
  **Qwen3-32B Q4_K_M + Qwen3-0.6B Q8_0**.
- Retire the `qwen3.5-9b` / `qwen3.8-27b` pair: different versions, not a clean
  distillation pair.

Approximate weights:

| Model | Q4_K_M | Q5_K_M | Q6_K | Q8_0 | Role |
|---|---|---|---|---|---|
| Qwen3.6-35B / Qwen3-32B | ~20–21 GB | ~23–24 GB | ~27–28 GB | ~34–37 GB | teacher on `agx64` |
| Qwen3.6-0.6B / Qwen3-0.6B | — | — | — | ~0.7 GB | student on `agx32` |
| Qwen3.6-1.7B / Qwen3-1.7B | — | — | — | ~1.9 GB | student if 0.6B is too weak |
| Qwen3.5-9B | — | — | — | 8.06 GiB | measured 11.27 tok/s |
| Qwen3.8-27B | 14.73 GiB | — | — | — | measured 4.75 tok/s |

`llama.cpp` reference points: 7B Q4_K_S 5,268 MB; 13B 8,609 MB; 30B 19,045 MB;
70B 37,655 MB. Weights only; add context/KV, OS and container overhead.

## Runtime selection per host

- **agx64 (64 GB):** `llama.cpp`/`llama-server` primary for the teacher/main;
  Ollama fallback; MLC optional; TensorRT-LLM/ExLlamaV2/vLLM not.
- **agx32 (32 GB):** `llama.cpp`/`llama-server` for the text engine/student;
  Ollama for the node's own AI stack and fallback; MLC optional;
  TensorRT-LLM/ExLlamaV2/vLLM not.

## Deployment shape

- New `sparknet-llm:agx` from `jetson-containers` `llama_cpp`; `llama-server`;
  the precontext; the teacher/student model mount; the OpenAI endpoints.
- Keep the `vllm` service name/port 8000, the `vllm-stub` CPU profile and the
  aux embed/rerank/audio services.
- Remove the vLLM build from the node image; keep goSpark, the Python compute,
  the bundle and the aux engines.
- Active models on the root; cold store, vaults and traces on the data drives;
  keys/state on the root.
- Tune `sm_72`, Q4_K_M, MAXN, `--n-gpu-layers 99`, measured context/parallel.
- Validate on `agx64`/`agx32`; no live claim until the models load and the
  endpoints answer.

## Related

[[0021-agx-llm-engine]] · [[agx-llm-engine]] ·
[[dusty-nv-jetson-llm-containers-2026-11-13]] · [[jetson-containers]] ·
[[dusty-nv]] · `contracts/model-catalog.json` · `contracts/model-store.md`
