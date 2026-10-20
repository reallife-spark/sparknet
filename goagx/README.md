# goagx — the node surface on NVIDIA AGX Xavier

`goagx/` is the goSpark node distribution retargeted from the DGX Spark
(GB10) to a Jetson AGX Xavier (16 GB, `sm_72`), plus the remake of the node
image Dockerfile that makes that possible. It is part of the fabric, not of
either role: same contract (`contracts/`), same service graph, same ports,
same entrypoint — different silicon.

Nothing in `peer-node/`, `master-node/` or `contracts/` changes to run on
Xavier. The platform selection is a setup-script flag.

| File | Role |
|---|---|
| `sparknet.agx.docker` | the AGX node image (remake of `spark.docker`) |
| `sparknet.agx.compose.yml` | same 14 services / profiles / ports as `spark.compose.yml`, AGX defaults |
| `sparknet-audio-shim.py` | OpenAI `/v1/audio/transcriptions` over whisper.cpp |
| `bootstrap-agx.sh` | device-side entry: preflight, goSpark at the pin, hand over to the setup script |
| `GOSPARK_PIN` | the one goSpark revision this distribution builds against |
| `publish-templates/` | README + workflow templates for the standalone repo |

## Standalone deployment repo (reallife-spark/goagx)

`reallife-spark/goagx` is the **generated distribution** of this surface: a
private repo holding everything a fresh Xavier needs to become a fully
functioning sparknet node — both role subvaults, `contracts/`, `shared/`, the
setup script, the root files the image build COPYs, and this directory — laid
out as a clone of the fabric so every code path runs unmodified. It is
exported by `scripts/sparknet-goagx-publish.sh` (`make goagx-publish`), never
hand-edited; the next publish overwrites the tree, and `VERSIONS.json` +
`SHA256SUMS` record the sparknet SHA, the goSpark pin and the image pins.

On the device:

```sh
git clone https://github.com/reallife-spark/goagx.git && cd goagx
./goagx/bootstrap-agx.sh     # preflight (aarch64/L4T r35/docker/swap/disk),
                             # goSpark at the pin, then setup --platform agx up
```

`make goagx-drift-check` compares this tree against the published tip
(self-skipping with a notice where the private remote cannot be fetched); the
published repo's generated `verify` workflow re-runs
`sparknet-goagx-publish.sh --verify` on every push. The hardware legs — the
source build completing on the Xavier, real tok/s — stay where the table
below puts them: proven on silicon, not in CI.

The goSpark binaries (`bin/` via the BuildKit named context `gospark`) are
consumed **unchanged**; `goSpark` itself is not forked for AGX.

## Resource-first verdict (STYLE_GUIDE §1)

Looked up before building anything (`make nv-search q="vllm L4T r35"` plus
the browser surfaces and the NVIDIA developer forums):

- **NVIDIA publishes no vLLM container for the r35 branch** — stated by an
  NVIDIA moderator in the "Suitable VLLM Container for Jetson Xavier NX
  with JetPack 5.1.4" thread, pointing at the jetson-containers Dockerfile
  as the way to build one ourselves.
- `nvcr.io/nvidia/vllm` (NGC) is current-generation only: tags 25.09-py3 …
  26.06-py3, Python 3.12 base. It neither covers `sm_72` nor the r35/cu114
  stack.
- The community route (`jetson-containers build vllm:<modern>`) fails on
  JetPack 5 exactly where expected: modern vLLM needs Python ≥ 3.10 and
  triton, while r35 ships Python 3.8 (reported on AGX Xavier r35.6,
  2026-02/03).

**Verdict:** build vLLM from source inside the image, pinned to a version
whose era still supported `sm_72` and Python 3.8 — `VLLM_GIT_REF=v0.2.7` —
and keep `ARG VLLM_GIT_URL` as the escape hatch: if the pinned ref ever
stops building on this stack, point it at dusty-nv/jetson-containers'
`packages/llm/vllm` recipe (or a fork of it) instead of re-deriving the
build. Everything else (NATS, Open WebUI, goSpark, llama.cpp,
whisper.cpp) was already pinned per ref/commit in `spark.docker` and
carries over unchanged.

## Hardware truth table

| | DGX Spark (the original) | AGX Xavier (this) |
|---|---|---|
| GPU / arch | GB10, `sm_121a` (Blackwell-family) | Xavier, `sm_72` (Volta) |
| Memory | 128 GB unified | 16 GB LPDDR4X (~137 GB/s) |
| Stack | cu128-era, torch ≥ 2.7 (base `spark.docker`) | JetPack r35 / L4T r35, **cu114**, torch 2.0.0, Python 3.8, Ubuntu 20.04 (base `nvcr.io/nvidia/l4t-pytorch:r35.2.1-pth2.0-py3`) |
| Arch build flag | `sm_121a` | `TORCH_CUDA_ARCH_LIST="7.0+PTX"` — vLLM v0.2.7 accepts only `7.0+PTX` for this family; the `sm_72` code comes from PTX JIT |

## What differs from `spark.docker`

1. **Base**: `l4t-pytorch:r35.2.1-pth2.0-py3` (arm64, r35 branch) instead of
   the DGX base. An `nvcc` gate asserts the toolchain in the base layer.
2. **vLLM v0.2.7 from source**, with build-time requirement relaxations
   (`ARG TORCH_CUDA_ARCH_LIST`, `ARG XFORMERS_PIP_SPEC`,
   `ARG TRANSFORMERS_PIP_SPEC`): torch comes from the base (2.0.0/cu114),
   `xformers==0.0.20`, `transformers==4.37.2`. xformers is built from its
   sdist here — expect **hours** of compilation on the Xavier, not minutes.
   Gate after install: `import vllm, vllm._C`.
3. **`VLLM_CLI` env decides the engine command** (image default
   `python3 -m vllm.entrypoints.openai.api_server`). When the last word is
   `serve` the launcher speaks the modern dialect (`--enable-prefix-caching`,
   `--limit-mm-per-prompt`); otherwise it passes only `--model` positionally.
   This is what lets the same image run v0.2.7 today and a newer engine via
   `VLLM_GIT_REF` + `VLLM_CLI` overrides later, without forking the
   entrypoint.
4. **Rerank/embed are llama.cpp, not vLLM**: llama.cpp `v0.7.0` is baked
   with `llama-server -h | grep -- --port` as its build gate, built
   `BUILD_SHARED_LIBS=OFF` static (no `llama-server` install rule upstream),
   serving `/v1/embeddings` and `/v1/rerank` (plus `/v1/reranking` alias).
5. **Audio is whisper.cpp v1.9.5 + the shim**: whisper.cpp serves only
   `/`, `/inference`, `/load`, `/health` — there is no OpenAI transcription
   route to match. `sparknet-audio-shim.py` (fastapi/uvicorn/httpx from the
   compute venv, `python-multipart` for form parsing) exposes
   `/v1/audio/transcriptions` on `VLLM_PORT` and forwards to whisper on
   `127.0.0.1:8004`. ffmpeg is installed so whisper's `--convert` handles
   non-WAV uploads. Both are started by the entrypoint's `whisper-asr`
   subcommand and supervised with `wait -n`.
6. **Defaults fit 16 GB**: `mistralai/Mistral-7B-Instruct-v0.2` (the Spark
   default, Qwen2.5-32B, does not fit here), `VLLM_MAX_MODEL_LEN=8192`,
   `VLLM_SHM_SIZE=4gb`. Every one of them is an overridable compose env.

Everything else — service names, container names, profiles, published
ports, the env-key surface of the core services, precontext/rag, the
stub/CPU overlay, `--engine stub` smoke — is identical by test
(`tests/test_agx_node.py` asserts the parity).

## Build

```sh
# 1. goSpark binaries (unchanged, arm64):
make -C ../goSpark build build-gpu          # from a sibling checkout

# 2. the image (on an arm64 host with Docker BuildKit):
./sparknet-node-setup.sh --platform agx build
# equivalent manual form (build context IS the fabric root):
docker buildx build --network=host \
  -f goagx/sparknet.agx.docker \
  --build-context gospark=<path-to-goSpark> \
  -t sparknet-agx-node:dev --load .
```

`--network=host` is required (no DNS inside the BuildKit sandbox on this
fleet). Budget:

- **Disk**: ~20 GB for the image plus base layers, like the Spark one.
- **Swap**: the 16 GB machine builds a CUDA extension (xformers sdist,
  then vLLM) with `MAX_JOBS` defaulting to 4 — add swap first, the OOM
  killer otherwise takes the build at its most expensive step.
- **Time**: the source-build leg is hours on Xavier (sdist + nvcc + link),
  against minutes on the Spark for prebuilt wheels. It is a one-off per
  image revision.

## Run

```sh
./sparknet-node-setup.sh --platform agx up                # text node
./sparknet-node-setup.sh --platform agx --role master up  # + control plane
./sparknet-node-setup.sh --platform agx --engine stub up  # CPU smoke, no GPU
```

`--platform` picks `goagx/sparknet.agx.compose.yml` + `spark-agx.env`
together; the default stays `spark`, so every existing invocation and every
existing test fixture is untouched. Profiles (`embed`, `rerank`, `audio`,
`webui`, …) behave exactly as the runbook's Spark section describes.

The CPU/stub smoke works on AGX too: `spark.compose.cpu.yml` overrides only
command/env/device reservations, never the image, so it layers onto the AGX
file as-is. Same warning as ever: the `gpu-sim.json` fixture is theatre;
never use it on a host with, or due to get, a real GPU.

## What is proven where

`contracts/spark-node-runbook.md` keeps its split — everything in its §1
"provable on any host" column proves packaging parity for the AGX image as
well (CPU smoke, stub agent↔vLLM↔compute path, containerised election);
the `confirm: user` column gains the AGX-specific physics:

- vLLM v0.2.7 + xformers source build actually completing on this hardware
  (the build gates fail loudly if not);
- real tokens/s from a 7B model on `sm_72` within the 16 GB budget;
- NVML/gpu-sidecar telemetry reading Jetson's driver honestly
  (`available=true` from a driver, not a file);
- whisper.cpp `detect_language` per-request behaviour through the shim;
- `--language auto` (if ever enabled in the engine dialect) at runtime.

The machine-readable parity for services, ports, images, pins and the
setup/entrypoint wiring lives in `tests/test_agx_node.py`; it runs in the
fabric suite (`make test-all`).
