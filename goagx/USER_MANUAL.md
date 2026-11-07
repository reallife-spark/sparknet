---
title: goagx — user manual
updated: 2026-10-30
---

# goagx — user manual

> The manual for the **AGX Xavier twin** of the sparknet node image surface:
> the same node contract, the same 14-service compose graph, the same role
> vaults and the same cross-role contract — on a different piece of silicon
> (Volta, `sm_72`) with a different toolchain (L4T r35, cu114, Python 3.8).
>
> `goagx/` is a **subtree of the fabric**, and the `goagx` repository is a
> **generated distribution** of it. Fixes belong upstream in the fabric; this
> tree is overwritten by the next publish.
>
> The **master manual** for the whole system lives in the `sparknet`
> repository as `USER_MANUAL.md`, and is published at the root of the `goagx`
> distribution as well.

---

## Table of contents

1. [What goagx is](#1-what-goagx-is)
2. [Orientation](#2-orientation)
3. [The hardware truth table](#3-the-hardware-truth-table)
4. [What differs from the Spark image](#4-what-differs-from-the-spark-image)
5. [The resource-first verdict](#5-the-resource-first-verdict)
6. [The image](#6-the-image)
7. [The compose surface](#7-the-compose-surface)
8. [The audio shim](#8-the-audio-shim)
9. [Bootstrap](#9-bootstrap)
10. [The goSpark pin](#10-the-gospark-pin)
11. [Publishing](#11-publishing)
12. [The gates](#12-the-gates)
13. [How to make a change correctly](#13-how-to-make-a-change-correctly)
14. [Configuration reference](#14-configuration-reference)
15. [Memory service](#15-memory-service)
16. [Troubleshooting](#16-troubleshooting)
17. [Spec vs implemented](#17-spec-vs-implemented)
18. [Glossary](#18-glossary)

---

## 1. What goagx is

The fabric ships **one node contract** on **two platforms**:

| | DGX Spark | AGX Xavier |
|---|---|---|
| Platform flag | `--platform spark` (the default) | `--platform agx` |
| Image | `../spark.docker` | `sparknet.agx.docker` |
| Compose | `../spark.compose.yml` | `sparknet.agx.compose.yml` |

The contract is identical: the same 15 services, the same container names,
the same profiles, the same published ports, the same env-key surface, the
same precontext and RAG paths, the same `--engine stub` smoke. The *engine
underneath* differs, and only that.

`--platform` selects the compose file **and** the env-file together, so a
node can never build the AGX image against the Spark compose, and switching
platforms never inherits the other's base image or model lines.

**Who this manual is for:** a developer changing the AGX image surface, the
compose file, the audio shim, the bootstrap script or the goSpark pin — and
anyone deploying a node on an Xavier and wanting to know which knobs exist
and why.

---

## 2. Orientation

| Path | What it is |
|---|---|
| `README.md` | The resource-first record: the verdict, the hardware table, the deltas, the measurements, the build and run commands. |
| `sparknet.agx.docker` | The AGX node image. The build context is the **fabric root**, not this directory. |
| `sparknet.agx.compose.yml` | The 14-service graph for the AGX. |
| `sparknet-audio-shim.py` | The OpenAI-transcriptions adapter in front of whisper.cpp. |
| `bootstrap-agx.sh` | The Xavier preflight and bootstrap: swap, disk, goSpark at the pin, then the setup script. |
| `GOSPARK_PIN` | The one goSpark revision this distribution builds against. |
| `publish-templates/` | The templates the publish renders into the distribution: the root README and the verify workflow. |
| `../contracts/` | The cross-role contract. A node cannot run without it. |
| `../peer-node/`, `../master-node/` | The two role vaults. |
| `../shared/` | The signed-authorization implementation. |
| `../scripts/` | The bundle, env-init and publish tooling. |
| `../sparknet-node-setup.sh` | The one-command bring-up. |

---

## 3. The hardware truth table

| | DGX Spark | AGX Xavier |
|---|---|---|
| GPU / arch | GB10, `sm_121a` (Blackwell family) | Xavier, `sm_72` (Volta) |
| Memory | 128 GB unified | 16 GB LPDDR4X (~137 GB/s); Orin variants 32/64 GB |
| Stack | cu128-era, torch ≥ 2.7 | JetPack r35 / L4T r35, **cu114**, torch 2.0.0, **Python 3.8**, Ubuntu 20.04 |
| Base image | the DGX base | `nvcr.io/nvidia/l4t-pytorch:r35.2.1-pth2.0-py3` (arm64) |
| Arch build flag | `sm_121a` | `TORCH_CUDA_ARCH_LIST="7.0+PTX"` |
| Engine | prebuilt vLLM wheels | **vLLM v0.2.7, built from source** |

Two consequences of the arch flag: vLLM v0.2.7 accepts only `7.0+PTX` for
this family, so the `sm_72` code path arrives by **PTX JIT** rather than from
a native SASS build. And the whole toolchain is a decade-old stack — which is
the reason the image pins as tightly as it does.

---

## 4. What differs from the Spark image

Everything below is a deliberate, tested delta. Everything *not* listed here
is identical, and the fabric's test suite asserts that.

### 4.1 The base image and the toolchain gate

`l4t-pytorch:r35.2.1-pth2.0-py3` (arm64) replaces the DGX base, and an
`nvcc` gate asserts the toolchain is actually present in the base layer — so
a silently different base fails the build instead of the inference.

### 4.2 vLLM built from source

`VLLM_GIT_REF=v0.2.7`, with `ARG VLLM_GIT_URL` kept as the escape hatch: if
the pinned ref ever stops building on this stack, point it at a maintained
fork's `packages/llm/vllm` recipe instead of re-deriving the build.

Three build-time relaxations exist because the base is old:

| Arg | Value | Why |
|---|---|---|
| `TORCH_CUDA_ARCH_LIST` | `7.0+PTX` | v0.2.7 accepts only this for the family. |
| `XFORMERS_PIP_SPEC` | `xformers==0.0.20` | A version that builds against torch 2.0.0. |
| `TRANSFORMERS_PIP_SPEC` | `transformers==4.37.2` | Matching the same era. |

xformers is built from its sdist here. **Expect hours of compilation on the
Xavier, not minutes.** The gate after installation is `import vllm, vllm._C` —
the import alone is not enough, because the compiled extension is what
matters.

### 4.3 `VLLM_CLI` decides the engine command

The image default is `python3 -m vllm.entrypoints.openai.api_server`. When the
last word is `serve`, the launcher speaks the modern dialect
(`--enable-prefix-caching`, `--limit-mm-per-prompt`); otherwise it passes only
`--model` positionally.

That one switch is what lets the same image run v0.2.7 today and a newer
engine later via `VLLM_GIT_REF` + `VLLM_CLI` overrides — **without forking
the entrypoint**.

### 4.4 Rerank and embed are llama.cpp, not vLLM

llama.cpp `v0.7.0` is baked with `llama-server -h | grep -- --port` as its
build gate, built `BUILD_SHARED_LIBS=OFF` (static, because upstream has no
`llama-server` install rule). It serves `/v1/embeddings` and `/v1/rerank`
(plus the `/v1/reranking` alias).

### 4.5 Audio is whisper.cpp plus a shim

See [§8](#8-the-audio-shim).

### 4.6 Defaults that fit 16 GB

| Setting | Value | Why |
|---|---|---|
| Model | `mistralai/Mistral-7B-Instruct-v0.2` | The Spark default (Qwen2.5-32B) does not fit here. |
| `VLLM_MAX_MODEL_LEN` | `8192` | Fits the 8 192-token window with headroom. |
| `VLLM_SHM_SIZE` | `4gb` | Shared-memory sizing for the engine. |

Every one of them is an overridable compose env.

---

## 5. The resource-first verdict

The standing rule in this project is **resource-first**: check NVIDIA's
catalog before building something of our own, and record the verdict. The
record for this platform is in `README.md` §"Resource-first verdict"; the
summary:

- **NVIDIA publishes no vLLM container for the r35 branch** — stated by an
  NVIDIA moderator in the "Suitable VLLM Container for Jetson Xavier NX with
  JetPack 5.1.4" thread, pointing at the jetson-containers Dockerfile as the
  way to build one.
- `nvcr.io/nvidia/vllm` (NGC) is current-generation only: tags 25.09-py3 …
  26.06-py3 on a Python 3.12 base. It covers neither `sm_72` nor the
  r35/cu114 stack.
- The community route (`jetson-containers build vllm:<modern>`) fails on
  JetPack 5 exactly where expected: modern vLLM needs Python ≥ 3.10 and
  triton, while r35 ships Python 3.8 (reported on AGX Xavier r35.6,
  2026-02/03).

**Verdict:** build vLLM from source inside the image, pinned to a version
whose era still supported `sm_72` and Python 3.8, and keep the URL as an
escape hatch. Everything else — NATS, Open WebUI, goSpark, llama.cpp,
whisper.cpp — was already pinned per ref or commit in the Spark image and
carries over unchanged.

The search helper is `make nv-search q="…"` from the fabric root; the wider
record lives in the fabric's `references/nvidia-build-catalog.md`.

---

## 6. The image

```sh
# The build context IS the fabric root — not this directory.
cd <fabric-root>
docker buildx build --platform linux/arm64 \
  -f goagx/sparknet.agx.docker \
  -t sparknet-agx-node:dev --load .
```

Stages and their pins:

| Stage / arg | Value |
|---|---|
| `L4T_BASE` | `nvcr.io/nvidia/l4t-pytorch:r35.2.1-pth2.0-py3` |
| `VLLM_GIT_URL` / `VLLM_GIT_REF` | the vLLM repository / `v0.2.7` |
| `TORCH_CUDA_ARCH_LIST` | `7.0+PTX` |
| `XFORMERS_PIP_SPEC` | `xformers==0.0.20` |
| `TRANSFORMERS_PIP_SPEC` | `transformers==4.37.2` |
| `MAX_JOBS` | `4` — the compile parallelism the 16 GB machine can survive |
| `OPENCODE_VERSION` | `2.2.5` |
| `NATS_VERSION` | `2.14.2` |
| `LLAMA_CPP_REF` | `v0.7.0` |
| `WHISPER_CPP_REF` | `v1.9.5` |
| `TARGETARCH` | the build architecture |

Three L4T-specific compatibility shims are applied at build time, each
patching a real incompatibility rather than working around it:
`../torch-dist-l4t-compat.py`, `../spark-vllm-l4t-patch.py` and
`../spark-vllm-xformers-gqa-patch.py`.

The image also carries the goSpark binaries (copied from the `gospark` stage),
the compute plane (`/opt/sparknet/compute/`), the goSpark configs, the peer
bundle tarball, the precontext builder, the audio shim, and the entrypoint at
`/usr/local/bin/spark-entrypoint`.

---

## 7. The compose surface

`sparknet.agx.compose.yml` declares the **same 15 services** as the Spark
compose, with the same names, container names, profiles and published ports:

`nats` · `vllm` · `vllm-embed` · `vllm-rerank` · `vllm-audio` · `compute` ·
`kvrouter` · `agent` · `control` · `gpu` · `webui` · `ingest` · `backup` ·
`opencode`

Profiles: `kv` (kvrouter), `control`, `webui`, `ingest`, `backup`,
`opencode`, `embed`, `rerank`, `audio`.

The state directory is bind-mounted from the host:
`${SPARKNET_STATE_HOST:-../peer-node/.state}` → `/srv/sparknet/peer-node/.state`.

The `ipc: host` and `ulimits` blocks are inherited from the Spark compose
unchanged — the state contract is the same, so the same host behaviour
applies.

The fabric's test suite asserts the parity: the same service set, the same
container names, the same profiles, the same published ports.

---

## 8. The audio shim

`sparknet-audio-shim.py` exists because of a genuine API mismatch:

- whisper.cpp's server speaks its own `POST /inference` with a multipart
  body, plus `/`, `/load`, `/health`.
- the node's audio contract — and what every OpenAI-compatible client
  actually sends — is `POST /v1/audio/transcriptions`.

The shim exposes `/v1/audio/transcriptions` on `VLLM_PORT` and forwards to
whisper on `127.0.0.1:8004`. **The engine underneath differs; the contract
does not.**

Field mapping: `file`, `response_format`, `language` and `prompt` are
understood; `model` is accepted and ignored (one baked model per image);
anything else a client sends is dropped, and whisper's own fallback ladder
handles `temperature`. Known engine responses are relayed unchanged, so
`text` unwraps to a bare string exactly as OpenAI specifies.

Two implementation notes that matter if you touch it:

- it runs from the **compute venv** (fastapi / uvicorn / httpx), with
  `python-multipart` for form parsing;
- it must stay **Python 3.8 compatible** — the L4T r35 base has Python 3.8,
  where a PEP 604 `X | None` annotation cannot survive FastAPI's runtime
  annotation evaluation, so `Optional[...]` is the correct spelling there and
  not a stale one. The file carries an explicit `ruff: noqa` for that reason,
  and the publish verifier checks the audio shim's Python 3.8 grammar.

Both whisper and the shim are started by the entrypoint's `whisper-asr`
subcommand and supervised with `wait -n`, so if either dies the pair goes
down rather than leaving a half-serving profile.

---

## 9. Bootstrap

`bootstrap-agx.sh` is the device-side entry point. It preflights the
hardware, uses `./gospark` when a fabric checkout is present (otherwise fetches
goSpark at the pin into `.cache/goSpark`), builds it, and then hands over to the
fabric's setup script.

```sh
./bootstrap-agx.sh                       # preflight + goSpark (or the pin), then setup
./bootstrap-agx.sh --gospark DIR         # use an existing goSpark checkout
./bootstrap-agx.sh --allow-low-swap      # continue despite < 8 GiB swap
./bootstrap-agx.sh --allow-low-disk      # continue despite < ~25 GB free
./bootstrap-agx.sh -h                    # this text
```

### 9.1 The preflight

| Check | Floor | Override |
|---|---|---|
| Swap | 8 GiB (`8388608` KB) | `--allow-low-swap` |
| Free disk | ~25 GB (`25600` MB) | `--allow-low-disk` |

Both floors exist for the same reason: **the vLLM / xformers source build
OOM-kills itself on a 16 GB machine without them.** The xformers sdist
compile and the vLLM link are the expensive steps, and a machine that runs
out of memory mid-build fails hours in, with an error that does not obviously
point at the cause. The overrides exist for machines where the operator has
judged the risk; they are not the default.

### 9.2 What it does, in order

1. Resolve its own location, so it works from a clone at any path.
2. Read `GOSPARK_PIN` for the repository and the SHA.
3. Preflight swap and disk.
4. Fetch goSpark at the pinned SHA into the goSpark directory — the repo is
   **private**, so the device needs a fine-grained PAT or a deploy key with
   read access. Never commit one.
5. Build the goSpark binaries (`make build build-gpu`).
6. Hand over to `../sparknet-node-setup.sh --platform agx`.

---

## 10. The goSpark pin

`GOSPARK_PIN` is the single source of truth for which goSpark revision this
distribution builds against. It carries two values:

```
GOSPARK_REPO=https://github.com/reallife-spark/goSpark.git
GOSPARK_SHA=91a6ef9ad28a0f4daa3a33eb1e80a026274125fa
```

Consumed by:

- `bootstrap-agx.sh` — fetch + build on the device;
- `../scripts/sparknet-goagx-publish.sh` — `VERSIONS.json` in the published
  manifest.

**A bump is a reviewed commit:** change the SHA, run the publish, and note
the goSpark changelog in the release message. The SHA is also pinned in the
published repository's `VERSIONS.json` and `SHA256SUMS`, so a distribution
always states exactly which goSpark it was built against.

---

## 11. Publishing

The `goagx` repository is **generated**. It is exported from the fabric in
one direction and is never hand-edited.

```sh
make goagx-publish        # from the fabric root: export and push
make goagx-drift-check    # fail if the published repo drifted from this tree
```

The export surface is selected with git's own view of the tree: tracked
files, plus untracked files git would not refuse to add. That keeps `.env`,
`.state`, `.obsidian` and the staged bundle tarball out automatically —
**anything gitignore hides in the fabric stays hidden in the distribution**,
so the staged tree and the published commit can never disagree on contents.

Exported subtrees: `peer-node`, `master-node`, `contracts`, `shared`,
`scripts`, `.opencode/skills`, `.opencode/agents`, `goagx`.

Root files: the entry scripts, the compose files, both dockerfiles, the
setup script, the bootstrap script, `.env.example`, `.dockerignore`,
`.gitignore`, `opencode.json`, `requirements.txt`, and the master
`USER_MANUAL.md`.

The published root README is rendered from
`publish-templates/README.md.tmpl` — never edited in place — and carries the
published timestamp, the fabric SHA, the goSpark SHA, the pins, the deploy
commands and the layout table.

The distribution ships the whole manual set, and every one of them resolves
inside the distribution:

| In the published tree | Covers |
|---|---|
| `USER_MANUAL.md` | The master manual for the whole system. |
| `goagx/USER_MANUAL.md` | This surface (this file). |
| `peer-node/USER_MANUAL.md` | The peer role. |
| `master-node/USER_MANUAL.md` | The master role. |

That is possible because the distribution carries `contracts/` and `shared/`:
the cross-repository references in those manuals are real files here, not
promises.

The distribution also ships `VERSIONS.json` and `SHA256SUMS`, and a `verify`
workflow that runs the publish tool's `--verify` mode on every push.

---

## 12. The gates

From the fabric root:

```sh
make ci                  # the full local pre-merge gate
make goagx-drift-check   # the published distribution still matches this tree
```

The AGX surface has its own dedicated test in the fabric suite, which
asserts the parity with the Spark image: the same 15 services, the same
container names, the same profiles, the same published ports, and the same
env-key surface. A change that drifts the two platforms apart fails there
rather than on an Xavier.

The publish tool's `--verify` mode checks the SHA256SUMS manifest, the pin
files, the `--help` surface of the entry scripts, the audio shim's Python 3.8
grammar, and the compose resolution.

---

## 13. How to make a change correctly

### 13.1 Changing the AGX image

- Keep every pin an `ARG` with an explicit default, so a build can be
  overridden without editing the file.
- Keep the `nvcc` gate and the `import vllm, vllm._C` gate. They are what
  turn "the base changed under us" from a runtime surprise into a build
  failure.
- Keep the arch flag at `7.0+PTX`.
- Keep the audio shim **Python 3.8 compatible**. The linter's opinion does
  not override the base image's interpreter.
- Every `COPY` source must be in the export manifest; the publish's
  `COPY` audit fails the build if it is not.

### 13.2 Changing the compose file

- **Every change must also be made in the Spark compose**, or the parity
  test fails. That is the point of the test: the two platforms differ in the
  engine, not in the contract.
- Keep the same service names, container names, profiles and published ports.
- Keep the state bind-mount and the env-key surface identical.

### 13.3 Changing `bootstrap-agx.sh`

- Keep the preflight floors, or change them deliberately *and* record why.
- Keep the pin indirection: the script must not hard-code a goSpark SHA.
- Keep it resolving its own location, so it works from a clone at any path.

### 13.4 Changing `GOSPARK_PIN`

- Change the SHA, run the publish, and note the goSpark changelog in the
  release message.
- Do not hand-edit `VERSIONS.json` or `SHA256SUMS` in the published
  repository — they are generated.

### 13.5 Writing documentation

- One page per file, in its category directory.
- Cite sources. A distilled page without provenance is a guess — mark it as
  one.
- Check the spec/impl boundary before making a claim.

---

## 14. Configuration reference

| Thing | Where | Notes |
|---|---|---|
| Model | compose env | `mistralai/Mistral-7B-Instruct-v0.2` by default; overridable. |
| `VLLM_MAX_MODEL_LEN` | compose env | `8192`. |
| `VLLM_SHM_SIZE` | compose env | `4gb`. |
| `VLLM_CLI` | compose env | Decides the engine dialect. |
| `VLLM_GIT_URL` / `VLLM_GIT_REF` | build args | The escape hatch for the pinned vLLM. |
| `MAX_JOBS` | build arg | `4` — the compile parallelism 16 GB can survive. |
| `WHISPER_UPSTREAM` | shim env | `http://127.0.0.1:8004` by default. |
| `SPARKNET_IMAGE_TAG` | compose env | The image tag; `dev` by default. |
| `SPARKNET_STATE_HOST` | compose env | The host state directory; `../peer-node/.state` by default. |
| `SPARKNET_PLATFORM` | setup script | `spark` or `agx`; picks the compose and the env-file together. |
| goSpark pin | `GOSPARK_PIN` | The one goSpark revision this distribution builds against. |
| Swap floor | `bootstrap-agx.sh` | 8 GiB. |
| Disk floor | `bootstrap-agx.sh` | ~25 GB. |

**Secrets** live on the host, never in an image layer. The device needs
credentials to read the private goSpark repository — a fine-grained PAT or a
deploy key — and those are supplied to the environment, never committed.

---

## 15. Memory service

The node runs `spark-entrypoint memory`, which starts `sparknet-memory` on
loopback `4110`. It stores one typed-memory store per vault and delegate runs;
it holds no key and signs nothing. The Python memory gateway (`4093`) is the
authority front door: a signed grant or an Open WebUI session is narrowed to one
vault before the Go store is touched. The service is part of the default
profile, so OpenCode and Open WebUI see the same memory for the same vault.

## 16. Troubleshooting

| Symptom | Likely cause | Where to look |
|---|---|---|
| The image build OOM-kills during the xformers or vLLM build | The machine has under 8 GiB swap. | `bootstrap-agx.sh`'s preflight; `--allow-low-swap` if you have judged the risk. |
| The image build fails on disk space | Under ~25 GB free. | `--allow-low-disk`; the disk floor. |
| `import vllm` succeeds but the engine does not start | The compiled extension `vllm._C` did not build. | The `import vllm, vllm._C` gate in the Dockerfile. |
| The engine rejects a modern CLI flag | `VLLM_CLI` is in the "modern" dialect but the pinned vLLM is v0.2.7. | `VLLM_CLI`; the entrypoint's last-word switch. |
| The GPU is not used | The arch flag is wrong. | `TORCH_CUDA_ARCH_LIST="7.0+PTX"`; the `nvcc` gate. |
| The audio profile returns 404 | The shim is not running, or whisper is not up. | `spark-entrypoint whisper-asr`; `WHISPER_UPSTREAM`. |
| The shim fails at import on a modern host | The file is Python 3.8 grammar by design — `Optional[...]`, not `X \| None`. | The file's `ruff: noqa` header; the verifier's 3.8 grammar check. |
| The model does not fit in memory | The Spark default is still set. | `mistralai/Mistral-7B-Instruct-v0.2`; `VLLM_MAX_MODEL_LEN`. |
| The compose does not start on the Xavier | The wrong platform's env-file was used. | `--platform agx`; `spark-agx.env`. |
| `make goagx-drift-check` fails | The published repository is behind this tree. | `make goagx-publish`. |
| The publish refuses | The private remote cannot be fetched. | It self-skips with a notice; check credentials. |
| The node comes up but the guard will not bind | No overlay, or an empty registry. The shipped registry is empty on purpose. | `make -C peer-node guard-status`; `../contracts/deployment-runbook.md`. |
| The device cannot fetch goSpark | The repository is private and the device has no credential. | A fine-grained PAT or a deploy key with read access. Never commit one. |

---

## 17. Spec vs implemented

Broadly:

- **Implemented and exercised** — the AGX image build with a source-built
  vLLM, the 14-service compose surface, the audio shim, the llama.cpp
  embed/rerank profiles, the bootstrap preflight and the goSpark fetch, the
  publish and drift-check tooling, and the platform parity assertions. The
  battery was run end to end on real AGX Orin nodes on 2026-10-21; the
  measurements are recorded in `README.md`.
- **Contracted and scaffolding** — the master-side surfaces the AGX inherits
  from the fabric (registry push listener, scheduler, share ratification).
- **Deliberately parked** — the destructive legs of the deployment runbook
  (rollback; replace-Master re-formation) are documented and deliberately
  left unexecuted by operator decision.

The honest test: **if you cannot point at a command that exercises it, it is
specified.**

---

## 18. Glossary

| Term | Meaning |
|---|---|
| **goagx** | The AGX Xavier twin of the node image surface, and the generated distribution of it. |
| **AGX Xavier / Orin** | NVIDIA Jetson AGX, Volta `sm_72` (Orin is the newer Ampere variant). |
| **L4T r35 / JetPack 5** | The base OS branch: cu114, torch 2.0.0, Python 3.8, Ubuntu 20.04. |
| **`7.0+PTX`** | The arch build flag for this family; the `sm_72` path arrives by PTX JIT. |
| **Resource-first** | Check NVIDIA's catalog before building our own, and record the verdict. |
| **Escape hatch** | The `*_GIT_URL` / `*_GIT_REF` args that let a pinned build be redirected without forking the file. |
| **Audio shim** | The OpenAI-transcriptions adapter in front of whisper.cpp. |
| **Pin** | A recorded exact version — a SHA, a tag or a ref — that a build is bound to. |
| **Publish** | The one-way export of the fabric tree into the `goagx` repository. |
| **Drift check** | The proof that the published distribution still matches the fabric tree. |
