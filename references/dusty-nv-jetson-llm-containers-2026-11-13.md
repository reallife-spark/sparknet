---
title: dusty-nv Jetson LLM containers — review 2026-11-13
updated: 2026-11-13
source: https://github.com/dusty-nv (74 repositories; GitHub API 2026-11-13)
license: mixed — per repository; jetson-containers is NOASSERTION, llama.cpp/llama-cpp-python MIT, NVIDIA L4T base under its own terms; no code vendored
type: reference
---

# dusty-nv Jetson LLM containers — review 2026-11-13

A dated review of the GitHub user [`dusty-nv`](https://github.com/dusty-nv) as
the resource-first check for replacing vLLM on the two AGX Xavier nodes. The
question was narrow: **which existing Jetson runtime can serve the fabric's
OpenAI-compatible text engine on `sm_72`, L4T r35, 64 GB (`agx64`) and 32 GB
(`agx32`) without the vLLM Python/PyTorch/xformers dependency stack?**

Reviewed 2026-11-13 via the GitHub API (`gh repo list`, 74 repositories), the
`jetson-containers` package READMEs/configs/Dockerfiles, and the host audit.
No code is vendored; this page is provenance, not a package.

## Hardware truth (audited 2026-11-13)

| Host | Module | SoC / arch | L4T | Cores | Power | Root free | Data free |
|---|---|---|---|---|---|---|---|
| `agx64` (Master) | **64 GB** (61 GiB visible) | AGX Xavier, `sm_72`, aarch64 | R35 (JetPack 5) | 8 | MAXN | 137 GB | 1.4 TB (`/mnt/ai`) |
| `agx32` (peer) | **32 GB** (30 GiB visible) | AGX Xavier, `sm_72`, aarch64 | R35 (JetPack 5) | 8 | MAXN | 808 GB | 131 GB (`/mnt/ai`) |

The live `goagx/README.md` still says “AGX Xavier — 16 GB”; the `log.md`
contains an older “AGX Orin” note. Both are stale: the hosts are **AGX Xavier
64 GB / 32 GB**. The root `index.md`, `hot.md`, `MEMORY.md`, this page and the
new ADR record the audited truth now; the `goagx` distribution, runbook and
role manuals are corrected in the Step 108 implementation.

Xavier constraints that drive the decision:

- **136.5 GB/s unified memory bandwidth** is the bottleneck, not raw capacity.
- `sm_72` (Volta Tensor Cores); compile with `CUDA_ARCHITECTURES=72` /
  `-DCMAKE_CUDA_ARCHITECTURES=72`; PyTorch-based auxiliaries use
  `TORCH_CUDA_ARCH_LIST=7.2`.
- **Q4_K_M** is the responsive choice for the 32B/35B teacher; Q5_K_M/Q6_K only
  when the measured tokens/s stays acceptable; Q8_0 is for the small student.
- **MAXN** (`sudo nvpmodel -m 0`, `sudo jetson_clocks`) is the baseline for
  inference; both hosts already report `NV Power Mode: MAXN`.
- `tegrastats` is the telemetry tool on this fleet; `nvidia-smi` is a dGPU tool.

## Relevant repositories and verdicts

| Repository | What it is | Verdict for this fabric |
|---|---|---|
| [`jetson-containers`](https://github.com/dusty-nv/jetson-containers) | Modular ML container build system for Jetson/JetPack-L4T; packages include `llama_cpp`, `ollama`, `mlc`, `vllm`, `nano_llm`, `text-generation-webui`, `transformers`, `sglang`, `tensorrt_edgellm`; `autotag`/`build`; `requires >=34.1.0` | **Primary resource.** `llama_cpp` (default `b9016`) for `llama-server`; `ollama` (0.23.0) as the fallback/peer AI-stack server; `mlc` optional; do not use its `vllm` package for this migration |
| [`NanoLLM`](https://github.com/dusty-nv/NanoLLM) | Optimized local inference with HuggingFace-like APIs; the `nano_llm` container | Useful alternative/experiment; **not a drop-in OpenAI server**; not the primary |
| [`llama.cpp`](https://github.com/dusty-nv/llama.cpp) / [`llama-cpp-python`](https://github.com/dusty-nv/llama-cpp-python) | Upstream engine fork and Python bindings (MIT) | The engine and packaging behind `llama_cpp`; **primary** |
| [`jetson-ai-lab`](https://github.com/dusty-nv/jetson-ai-lab) / [`gpt-llm-lab`](https://github.com/dusty-nv/gpt-llm-lab) | LLM tutorials and recipes for Jetson | Reference for the `llama.cpp`/Ollama recipes; not the runtime |
| [`MLC`](https://github.com/dusty-nv/jetson-containers/tree/master/packages/llm/mlc) (package) | MLC/TVM compiled LLM runtime with `mlc_llm serve` | Optional experiment; compile cost; not the primary |
| `vLLM` / `SGLang` / `TGI` / `TensorRT-Edge-LLM` packages | High-throughput Python/CUDA servers | Heavy; vLLM is the dependency problem; TensorRT-LLM is not the Xavier default; not for this step |
| `text-generation-webui` | PyTorch UI with an OpenAI extension | Heavy; not a text-engine replacement here |
| `ExLlamaV2` / `GPTQ` packages | EXL2/GPTQ, custom PyTorch | Custom build; max 4-bit speed; not for this step |
| The remaining ~60 repos | CV, robotics, ROS, TensorRT vision, forks | Not relevant to the text LLM engine; full inventory below |

The `jetson-containers` package metadata:

- `llama_cpp`: default `b9016`; `llama.cpp` + `llama-cpp-python`; CUDA build with
  `GGML_CUDA=ON`, `GGML_CUDA_F16=ON`, `LLAMA_CURL=ON`, `LLAMA_OPENSSL=ON`,
  `GGML_CUDA_FA_ALL_QUANTS=ON`; `CUDA_ARCHITECTURES` from the host; L4T
  `>=34.1.0`.
- `ollama`: 0.23.0 default; Go + CUDA build; `OLLAMA_HOST=0.0.0.0`;
  `OLLAMA_MODELS=/data/models/ollama/models`; `CMD /start_ollama`; L4T
  `>=34.1.0`.
- License: the repository reports `NOASSERTION`; `llama.cpp` and
  `llama-cpp-python` are MIT; the NVIDIA L4T base carries its own terms. No
  legal review was requested; this page records the facts only.

## Framework comparison

| Framework | Format | Setup | Xavier fit | Verdict |
|---|---|---|---|---|
| **llama.cpp / `llama-server`** | GGUF | Moderate (CUDA build) | `sm_72`, CUDA, `llama-server` OpenAI, `--jinja`/`--chat-template-file`/`--system-prompt-file` | **Primary**; most reliable GPU acceleration and widest model support |
| **Ollama** | GGUF | Easy CPU / hard GPU build | llama.cpp backend; simple OpenAI API; model store | **Fallback** and the peer's own AI-stack server |
| **MLC-LLM** | MLC/TVM | Hard (compile) | Low-overhead OpenAI serving; TVM | Optional experiment |
| **TensorRT-LLM** | TensorRT engines | Heavy; INT4/INT8 | NVIDIA-optimized but a large build surface | Not for the Xavier in this step |
| **ExLlamaV2** | EXL2/GPTQ | Hard (custom PyTorch) | Maximum 4-bit speed | Not for this step |
| **NanoLLM** | Python API | Moderate | Optimized local inference; not OpenAI | Alternative, not a drop-in |
| **text-generation-webui** | PyTorch | Heavy | OpenAI extension | Not for the text engine |
| **SGLang / TGI** | Python/CUDA | Heavy | High-throughput servers | Not for the Xavier |
| **vLLM** | PyTorch/CUDA/triton | Heavy; the current build is the problem | The existing engine; dependencies cannot be fulfilled | **Retire** |

The user's framework table and Xavier tips (2026-11-13) are consistent with
this review: target `sm_72`, prefer Q4_K_M for the 32B/35B class, and set MAXN
before inference.

## Why vLLM is being replaced

The current `goagx/sparknet.agx.docker` builds **vLLM v0.2.7 from source** on
the L4T r35 base with torch 2.0.0, xformers 0.0.20, transformers 4.37.2 and
Python 3.8, plus the L4T/xformers patches. The operator reports that the
requirements/dependencies cannot be fulfilled on the two Xavier hosts. The
`jetson-containers` `llama_cpp`/`ollama` path avoids the vLLM Python stack:
`llama.cpp` is C++/CUDA, Ollama is Go + llama.cpp, and both serve an
OpenAI-compatible API. The decision is recorded in
[[0021-agx-llm-engine]]; this page is the source review behind it.

## Model selection rule

Same Qwen version for teacher and student, so the tokenizer/family is shared
and distillation is a clean teacher→student transfer:

- **Teacher/main on `agx64`:** the largest model of the chosen Qwen version
  that fits 64 GB at the best responsive quantization. Start at **Q4_K_M**;
  Q5_K_M/Q6_K only if the measured tokens/s is acceptable; Q8_0 only for a
  model small enough to stay responsive.
- **Student on `agx32`:** the smallest model of the **same version**, at
  **Q8_0** (or Q4_K_M if memory/speed requires).
- Candidate pair: **Qwen3.6-35B Q4_K_M** teacher + **Qwen3.6-0.6B Q8_0**
  student; fallback **Qwen3-32B Q4_K_M** + **Qwen3-0.6B Q8_0** if the 3.6
  small model is unavailable or the 35B Q4_K_M does not fit with the desired
  context.
- Retire the current `qwen3.5-9b` / `qwen3.8-27b` pair: it is not same-version.
- The exact pair is confirmed after the Phase 0 model inventory (GGUF,
  tokenizer, license, memory, tokens/s). The `model-catalog`, `agent-models`,
  `ai-stack` and `distillation-schema` are updated in Step 108.

Approximate GGUF footprints:

| Model | Quantization | Weights | Host fit |
|---|---|---|---|
| Qwen3.6-35B / Qwen3-32B | Q4_K_M | ~20–21 GB | `agx64` 64 GB, Q4_K_M teacher |
| Qwen3.6-35B / Qwen3-32B | Q5_K_M | ~23–24 GB | only if tokens/s acceptable |
| Qwen3.6-35B / Qwen3-32B | Q6_K | ~27–28 GB | only if tokens/s acceptable |
| Qwen3.6-35B / Qwen3-32B | Q8_0 | ~34–37 GB | too slow/too tight for the teacher; not the first choice |
| Qwen3.6-0.6B / Qwen3-0.6B | Q8_0 | ~0.7 GB | `agx32` 32 GB student |
| Qwen3.6-1.7B / Qwen3-1.7B | Q8_0 | ~1.9 GB | student if 0.6B is too weak |
| Qwen3.5-9B | Q8_0 | 8.06 GiB | measured 11.27 tok/s on the student |
| Qwen3.8-27B | Q4_K_M | 14.73 GiB | measured 4.75 tok/s; not same-version with the 9B |

`llama.cpp` reference points from the `jetson-containers` README: 7B Q4_K_S
5,268 MB; 13B Q4_K_S 8,609 MB; 30B Q4_K_S 19,045 MB; 70B Q4_K_S 37,655 MB.
The `ollama` README lists the same class of footprints. These are weights only;
add context/KV, the OS and the Docker/container overhead.

## Storage contract

- **Root NVMe (`/`)** — the fast model-calculation path: the active
  teacher/student GGUF, tokenizer, model config, precontext and KV cache under
  `/opt/sparknet/models/...`; the Docker images; the service code; the
  state/keys under `~/.local/state/sparknet` (0700/0600).
- **Data drives (`/mnt/ai`)** — the vaults (fabric, role and per-user), the
  cold model store, `hf-cache`, `uplift`, `distill`, Qdrant snapshots and
  backups. The vaults never move to the root; the model container never mounts
  a vault.
- Space budget: `agx64` root has 137 GB free; the 35B Q4_K_M weights ~21 GB
  plus context/KV and images (~40.6 GB images, 30.7 GB reclaimable) fit after
  pruning the old vLLM image/build cache. `agx32` root has 808 GB free; the
  0.6B student is negligible. The data drives hold the 317/328 GB Ollama store;
  only the active pair is staged on the root.
- The migration is reversible: keep the current vLLM image/service and the
  model store untouched until the new path is validated; tag both images.

## Runtime selection and deployment

| Host | Runtime | Model | Why |
|---|---|---|---|
| `agx64` | **llama.cpp / `llama-server`** (CUDA, `sm_72`) | Teacher/main, Qwen3.6-35B Q4_K_M (fallback Qwen3-32B Q4_K_M) | Most reliable GPU path; OpenAI API; precontext; 64 GB |
| `agx32` | **llama.cpp / `llama-server`** for the text engine; **Ollama** for the peer's own AI stack and fallback | Student, Qwen3.6-0.6B Q8_0 (fallback Qwen3-0.6B Q8_0) | Same engine/API as the teacher; Ollama is the peer's simple chat plane |

The `vllm` compose service name and port 8000 stay stable; the new image is
`sparknet-llm:agx`; the `vllm-stub` CPU profile stays; the aux
`vllm-embed`/`vllm-rerank`/`vllm-audio` engines remain. The precontext is
injected through `llama-server --jinja` plus
`--chat-template-file`/`--system-prompt-file`; the `spark-precontext.py`
`digest`/MASTERSPIKE text is the source. The full implementation is Step 108.

## Resource-first check

`make nv-search q="llama"` (2026-11-13) returned NVIDIA catalog model IDs
(e.g. `meta/codellama-70b`, `nvidia/llama-3.1-nemotron-70b-instruct`,
`nvidia/llama-3.1-nemotron-51b-instruct`), not a Jetson container runtime;
`make nv-search q="vllm"` returned no model. The existing resource for the
Jetson runtime is **`jetson-containers`** (`llama_cpp`/`ollama`), not a new
engine. The verdict is recorded here and in [[0021-agx-llm-engine]].

## Full repository inventory

All 74 repositories returned by the GitHub API on 2026-11-13. The LLM-relevant
ones are assessed above; the rest are CV, robotics, ROS, TensorRT vision,
simulation or forks and are not part of the text-engine decision.

<details>
<summary>74 repositories (name, language, stars, fork, archived, updated, description)</summary>

| Repository | Language | ★ | Fork | Archived | Updated | Description |
|---|---|---|---|---|---|---|
| `jetson-containers` | Jupyter Notebook | 4900 | false | false | 2026-11-13 | Machine Learning Containers for NVIDIA Jetson and JetPack-L4T |
| `jetson-utils` | C++ | 914 | false | false | 2026-11-10 | C++/CUDA/Python multimedia utilities for NVIDIA Jetson |
| `jetson-inference` | C++ | 9033 | false | false | 2026-11-12 | Hello AI World guide to deploying deep-learning inference networks and deep vision primitives with TensorRT and NVIDIA Jetson. |
| `openvla` | Python | 10 | true | false | 2026-05-05 | OpenVLA: An open-source vision-language-action model for robotic manipulation. |
| `sudonim` | Python | 13 | false | false | 2026-05-12 | NIMs powershell for launching local AI microservices and open-stack model templates |
| `NanoDB` | Python | 65 | false | false | 2026-11-05 | Zero-copy multimodal vector DB with CUDA and CLIP/SigLIP |
| `jetson-ai-lab` | Python | 21 | true | false | 2026-02-13 |  |
| `nanosaur_cli` | Python | 0 | true | false | 2025-10-03 | 📦 nanosaur CLI to manage and control nanosaur |
| `nanosaur` | Python | 0 | true | false | 2025-10-03 | 🦕 nanosaur is a little robot, powered by ROS 2. Made for NVIDIA Jetson |
| `nanosaur_perception` | Python | 0 | true | false | 2025-10-03 | 🖼️ Perception for nanosaur. Works with Isaac ROS |
| `nanosaur_simulation` | Python | 0 | true | false | 2025-10-03 | 👨‍💻 run nanosaur in a simulated world! |
| `nanosaur_robot` | Python | 1 | true | false | 2025-10-03 | ⚙️ ROS 2 packages to interact with the nanosaur hardware |
| `transfusion-pytorch` | Python | 4 | true | false | 2025-10-03 | Pytorch implementation of Transfusion, "Predict the Next Token and Diffuse Images with One Multi-Modal Model", from MetaAI |
| `IsaacLab` | Python | 3 | true | false | 2025-10-03 | Unified framework for robot learning built on NVIDIA Isaac Sim |
| `awesome-foundation-model-ros` | - | 7 | true | false | 2025-02-23 | A collection ROS projects utilizing foundation models. |
| `ros2_pololu` | C++ | 7 | false | false | 2025-10-16 | ROS2 nodes for Pololu Maestro, Jrk, and Simple Motor Controller |
| `VILA` | Python | 6 | true | false | 2025-11-23 | VILA - a multi-image visual language model with training, inference and evaluation recipe, deployable from cloud to edge (Jetson Orin and laptops) |
| `NanoLLM` | Python | 380 | false | false | 2026-11-05 | Optimized local inference for LLMs with HuggingFace-like APIs for quantization, vision/language models, multimodal agents, speech, vector DB, and RAG. |
| `diffusion_policy` | Python | 2 | true | false | 2025-10-03 | [RSS 2023] Diffusion Policy Visuomotor Policy Learning via Action Diffusion |
| `3D-Diffusion-Policy` | Python | 3 | true | false | 2025-10-03 | [RSS 2024] 3D Diffusion Policy: Generalizable Visuomotor Policy Learning via Simple 3D Representations |
| `clip_trt` | Python | 37 | false | false | 2026-09-16 | CLIP and SigLIP models optimized with TensorRT with a Transformers-like API |
| `ODM` | Python | 1 | true | false | 2025-10-03 | A command line toolkit to generate maps, point clouds, 3D models and DEMs from drone, balloon or kite images. 📷 |
| `crossformer` | Python | 1 | true | false | 2025-10-03 |  |
| `pypopsift` | C++ | 4 | true | false | 2025-10-03 | Python module for CUDA accelerated SIFT on GPUs |
| `mimicgen` | Python | 2 | true | false | 2025-10-03 | This code corresponds to simulation environments used as part of the MimicGen project. |
| `robosuite` | Python | 4 | true | false | 2025-10-03 | robosuite: A Modular Simulation Framework and Benchmark for Robot Learning |
| `ros_deep_learning` | C++ | 985 | false | false | 2026-11-10 | Deep learning inference nodes for ROS / ROS2 with support for NVIDIA Jetson and TensorRT |
| `whisper_trt` | Python | 7 | true | false | 2026-03-01 | A project that optimizes Whisper for low latency inference using NVIDIA TensorRT |
| `camera-capture` | C++ | 45 | false | false | 2026-07-29 | GUI tool for collecting & labeling data from live camera feed |
| `jetson-presentations` | - | 66 | false | false | 2026-09-02 | PDF slides about NVIDIA's Jetson embedded platform and deep learning. |
| `gtc-llm-lab` | Shell | 9 | false | false | 2025-10-03 | Jetson AI Lab - LLM Inference |
| `TTS` | Python | 5 | true | false | 2025-10-03 | 🐸💬 - a deep learning toolkit for Text-to-Speech, battle-tested in research and production |
| `jetson-voice` | Python | 229 | false | false | 2026-11-03 | ASR/NLP/TTS deep learning inference library for NVIDIA Jetson using PyTorch and TensorRT |
| `cudf` | C++ | 0 | true | false | 2026-08-12 | cuDF - GPU DataFrame Library  |
| `llama-cpp-python` | Python | 3 | true | false | 2025-10-03 | Python bindings for llama.cpp |
| `llama.cpp` | C | 3 | true | false | 2025-10-03 | Port of Facebook's LLaMA model in C/C++ |
| `pytorch-classification` | Python | 33 | false | false | 2026-09-01 | Training of image classification models with PyTorch |
| `llm-awq` | Python | 0 | true | false | 2025-10-03 | AWQ: Activation-aware Weight Quantization for LLM Compression and Acceleration |
| `cuml` | C++ | 2 | true | false | 2026-08-10 | cuML - RAPIDS Machine Learning Library |
| `small-stable-diffusion` | Python | 9 | true | false | 2026-02-14 |  |
| `pytorch-detection` | - | 16 | false | false | 2026-11-12 | Training of object detection networks with PyTorch |
| `pytorch-ssd` | Python | 55 | true | false | 2026-06-30 | MobileNetV1, MobileNetV2, VGG based SSD/SSD-lite implementation in PyTorch. Out-of-box support for retraining on Open Images dataset. ONNX and Caffe2 support. Experiment Ideas like CoordConv. |
| `bitsandbytes` | Python | 6 | true | false | 2026-06-13 | 8-bit CUDA functions for PyTorch, modified to build on NVIDIA Jetson |
| `stable-diffusion-webui-tensorrt` | Python | 1 | true | false | 2025-10-03 |  |
| `pytorch-timeseries` | Python | 10 | false | false | 2025-10-03 |  |
| `dash-draggable` | JavaScript | 0 | true | false | 2025-10-03 | Dash components for building draggable and resizable grid layouts. Based on the well-known STRML/react-grid-layout. |
| `jetbot_ros` | Python | 401 | false | false | 2026-11-12 | ROS nodes and Gazebo model for NVIDIA JetBot with Jetson Nano |
| `jetson-reinforcement` | C++ | 933 | false | false | 2026-11-13 | Deep reinforcement learning GPU libraries for NVIDIA Jetson TX1/TX2 with PyTorch, OpenAI Gym, and Gazebo robotics simulator. |
| `rl-baselines3-zoo` | Python | 2 | true | false | 2025-10-03 | A training framework for Stable Baselines3 reinforcement learning agents, with hyperparameter optimization and pre-trained agents included. |
| `isaac_ros_visual_odometry` | C++ | 1 | true | false | 2026-10-06 | Visual odometry package based on hardware-accelerated NVIDIA Elbrus library with world class quality and performance. |
| `DockerHub-API` | Python | 0 | true | false | 2025-10-03 | Python Docker Hub API client library |
| `zed-ros2-wrapper` | C++ | 3 | true | false | 2025-10-03 | ROS 2 wrapper beta for the ZED SDK |
| `ORB_SLAM2_CUDA` | C++ | 5 | true | false | 2025-10-03 | ORB_SLAM2 with GPU Enhancement running on NVIDIA Jetson TX1. Focus on ROS part. |
| `trt_pose` | Python | 5 | true | false | 2026-09-15 | Real-time pose estimation accelerated with NVIDIA TensorRT |
| `py3gazebo` | Python | 2 | true | false | 2025-10-03 | Python bindings for the Gazebo multi-robot simulator. |
| `vision_msgs` | C++ | 2 | true | false | 2025-10-03 | Algorithm-agnostic computer vision message types for ROS. |
| `OpenSeq2Seq` | Python | 2 | true | false | 2025-10-03 | Toolkit for efficient experimentation with Speech Recognition, Text2Speech and NLP |
| `pytorch-segmentation` | Python | 34 | false | false | 2025-10-03 | Training of semantic segmentation networks with PyTorch |
| `kenlm` | C++ | 2 | true | false | 2025-10-03 | KenLM: Faster and Smaller Language Model Queries |
| `pytorch` | C++ | 3 | true | false | 2025-10-03 | Tensors and Dynamic neural networks in Python with strong GPU acceleration |
| `git` | C | 1 | true | false | 2025-10-03 | Git Source Code Mirror - This is a publish-only repository and all pull requests are ignored. Please follow Documentation/SubmittingPatches procedure for any of your improvements. |
| `gcc` | C | 1 | true | false | 2025-10-03 |  |
| `pytorch-odometry` | Python | 16 | false | false | 2025-10-03 | Training of visual odometry estimation networks using PyTorch |
| `pytorch-depth` | Python | 12 | true | false | 2025-10-03 | MonoDepth Estimation - ICRA 2018 "Sparse-to-Dense: Depth Prediction from Sparse Depth Samples and a Single Image" |
| `vision` | Jupyter Notebook | 9 | true | false | 2025-10-03 | Datasets, Transforms and Models specific to Computer Vision |
| `jetson-scripts` | Shell | 96 | false | false | 2026-10-26 | Configuration scripts and install guides for NVIDIA Jetson platform |
| `super-resolution` | Python | 31 | false | false | 2026-01-16 | PyTorch super resolution model with RGB support and ONNX exporter |
| `deep-homography` | C++ | 2 | true | false | 2025-10-03 | Building a homography dataset and training with PyTorch |
| `a3c_continuous` | Python | 4 | true | false | 2025-10-03 | A continuous action space version of A3C LSTM in pytorch plus A3G design |
| `turbo2` | C++ | 89 | false | false | 2025-10-03 | Tegra Unmanned Retrieval Bot gen2, with NVIDIA Jetson and deep reinforcement learning |
| `imagenet_downloader` | Python | 3 | true | false | 2025-10-03 | Download ImageNet images from list of IDs and URLs |
| `rovernet` | C++ | 35 | false | false | 2025-10-03 | Deep reinforcement learning-driven robotic controller and navigation library using Torch. |
| `jetson-screencasts-sources` | C++ | 15 | true | false | 2025-10-03 | Code for accompanying our OpenCV video tutorial series. |
| `homography-dlt` | C | 6 | true | false | 2025-10-03 | Normalized Direct Linear Transform (DLT) for 4-point Homography Estimation  |

</details>

## Limits and open questions

- No legal review was requested; the `jetson-containers` `NOASSERTION` and the
  `llama.cpp`/`llama-cpp-python` MIT terms are recorded above.
- The exact Qwen version/pair is confirmed after the Phase 0 model inventory.
- The `jetson-containers` `llama_cpp`/`ollama` build on L4T r35/`sm_72` is a
  Step 108 validation, not a claim here.
- The `goagx` distribution, `contracts/spark-node-runbook.md` and the role
  manuals still describe vLLM; Step 108 corrects them.
- The storage migration and the MAXN boot persistence are Step 108 changes.
- No live claim is made for the new engine in this page.

## Related

[[0021-agx-llm-engine]] · [[agx-llm-engine]] ·
[[agx-text-serving-options]] · [[dusty-nv]] · [[jetson-containers]] ·
[[nvidia-build-catalog]]
