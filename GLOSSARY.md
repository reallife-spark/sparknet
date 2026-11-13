---
title: sparknet glossary
updated: 2026-11-13
type: reference
---

# sparknet glossary

The vocabulary of the two-role fabric. Entries name concepts; `contracts/` owns
rules and `docs/adr/` owns decisions. An unqualified term is safe only when the
layer or collision does not matter.

## Language

### Roles and authority

**fabric**:
The two-role system in this repository: the contract, the shared
implementation, a peer role and a Master role.

_Avoid_: platform, mesh

**peer**:
The user's local node. It runs chat, agentic work, a private vault and
self-healing. It holds an identity key, not the operational key.

_Avoid_: client, worker

**Master**:
The elected signing role. It holds the operational key and supplies authority
and scoped fabric knowledge.

_Avoid_: controller, admin node

**authority**:
The right to make a privileged decision. In the fabric it comes only from
possession of the operational key; a capability, a registry entry, a role name
or a prompt cannot create it.

_Avoid_: permission, privilege, control

**identity key**:
The peer's Ed25519 key. It proves the peer's identity and signs its requests;
it cannot grant, revoke or escalate.

_Avoid_: node key, signing key

**operational key**:
The Master's Ed25519 key. It signs registry entries, approvals and scoped
answers; it never leaves the Master.

_Avoid_: master key, root key

**capability**:
A named permission in the closed fabric vocabulary. It is inert until the
Master grants it to a node.

_Avoid_: permission, role

**capability grant**:
The Master's signed inclusion of a capability in one node's registry entry.
The entry's node carries the grant; the holder is the role that may exercise
it.

_Avoid_: capability (as a verb), permission

**capability holder**:
The role that may exercise a capability. A supervision capability is
master-held: the Master issues, the peer executes.

_Avoid_: grantee, owner

**supervision capability**:
A master-held capability whose signed request makes a peer act against its own
service. `admin-supervise`, `sandbox-supervise` and `memory-supervise` are the
supervision capabilities; the peer carries the grant.

_Avoid_: admin capability, control capability

**registry**:
The Master-signed list of node identities, capabilities and revocations.

_Avoid_: directory, roster

**guard**:
The peer service that verifies Master-signed requests before a protected file
is changed.

_Avoid_: firewall, sentinel

**guard approval**:
A Master-signed authorization to change one protected file on one peer. It is
not a policy approval.

_Avoid_: approval (unqualified), patch

**signed surface**:
An endpoint that accepts only signed authority requests. It is not a console
surface and not a knowledge channel.

_Avoid_: surface (unqualified), API

**inert capability**:
A capability that is contracted but cannot act because its route, executor or
signed grant is absent. It is not a disabled permission a user can turn on.

_Avoid_: unused capability, disabled capability

### Knowledge and work

**vault**:
A role's or user's knowledge tree. Knowledge lives here; secrets live in a
state directory.

_Avoid_: store, knowledge base

**user vault**:
The `peer-<id>` vault belonging to one sandbox user. It is the only vault a
session sandbox may mount.

_Avoid_: vault (unqualified), user KB

**role vault**:
The peer role's own vault. No execution sandbox may mount it.

_Avoid_: vault (unqualified)

**knowledge**:
Content a peer's AI may answer from within its scope: its vault, the user's
vault or KB, an accepted RFI answer, an accepted share, or the build-time
context pack. Authority artifacts are never knowledge.

_Avoid_: data, information, context

**scope**:
An allow-list that bounds what a request may read or receive. A scope narrows
on receipt and never widens.

_Avoid_: permission, range

**protected file**:
A file whose change requires a Master-signed guard approval. It is not
knowledge.

_Avoid_: system file, immutable file

**RFI**:
A request for information: a peer asks the Master a scoped question, and the
signed answer is installed in the peer's inbox and accepted before it is
knowledge.

_Avoid_: query, ticket

**issue**:
An operational work item tracked outside the vault. It is not knowledge and
not authority.

_Avoid_: ticket, bug

**issue module**:
The shared model that owns issue parsing, redaction, validation, state
transitions and the read projection. It is not authority and never signs a
report.

_Avoid_: issue service, tracker

**issue projection**:
The canonical read view of recorded issues and their triage state. It carries
no authority and is not a knowledge corpus.

_Avoid_: issue view, dashboard

**triage ledger**:
The append-only record of issue triage transitions; the latest triage view is
derived from it.

_Avoid_: triage log, history

### Execution sandbox

**sandbox**:
The umbrella term for the peer's execution environment. Qualify it as
`execution sandbox`, `sandbox record`, `sandbox backend` or `OpenShell driver`
when the layer matters.

_Avoid_: container, workspace, runtime

**execution sandbox**:
The per-user, vault-scoped environment in which the peer runs agentic work. It
is an execution surface, not a knowledge channel.

_Avoid_: container, workspace, runtime

**sandbox backend**:
The peer engine's choice of who supervises the execution sandbox: the legacy
Docker backend (`docker`) or OpenShell (`openshell`). It is not the OpenShell
driver.

_Avoid_: driver, runtime, engine

**OpenShell driver**:
The mechanism OpenShell uses to realise a sandbox: rootful Docker or a
microVM. Rootless Podman is excluded. The gateway selects it from local
configuration; a sandbox request never does.

_Avoid_: backend, runtime

**sandbox record**:
The gateway's object for one sandbox: its name, phase, stored policy, mounts
and resolved workload identity. It is not the sandbox's contents or its vault.

_Avoid_: sandbox (unqualified), container

**sandbox image**:
The image a sandbox record is created from. The peer refuses an image outside
its local execution whitelist.

_Avoid_: container image, runtime

**sandbox gateway**:
The loopback OpenShell service that owns sandbox records and is the only peer
process that talks to the container or VM runtime. It is not the model proxy
and not the Master.

_Avoid_: gateway (unqualified), supervisor

**gateway credential**:
The peer-local mTLS bundle and token the engine uses to reach its sandbox
gateway. It never leaves the peer or enters a sandbox.

_Avoid_: gateway token, API key

**sandbox workload**:
The process an execution sandbox runs. In an OpenShell sandbox it has no
network interface; its egress is the sandbox policy's network rules.

_Avoid_: agent, container, app

**workload identity**:
The Unix UID/GID a sandbox workload runs as, reconciled to the node owner. It
is not the sandbox user's WebUI identity.

_Avoid_: sandbox user, owner (unqualified)

**node owner**:
The Unix account that owns the peer node and every `peer-<id>` vault on it. All
sandbox users share it; isolation between them is mount-scoped, not
UID-scoped.

_Avoid_: owner (unqualified), admin

**sandbox user**:
The WebUI principal whose `peer-<id>` vault is mounted into a session sandbox.
All sandbox users share the node owner's Unix identity.

_Avoid_: owner, Unix user

**node operator**:
The human responsible for a peer node's configuration and service manifest.

_Avoid_: admin, root

**vault mount**:
The one read-write bind of a user vault into a session sandbox. It is the
sandbox's data boundary and is never deleted with the sandbox record.

_Avoid_: data mount, workspace mount, mount (unqualified)

**config mount**:
The one read-only bind of generated OpenCode configuration into a VM sandbox.
It carries runtime configuration, not user knowledge.

_Avoid_: second mount, config volume

**mount list**:
The set of binds a sandbox is created with. It is the security boundary for
bind-mounted paths; a sandbox request cannot add a mount outside it.

_Avoid_: mount set, volumes

**sandbox policy**:
The declared filesystem, Landlock, process and network rules for a sandbox. It
states intent; for bind-mounted paths the mount list is the boundary.

_Avoid_: policy (unqualified), profile

**local execution whitelist**:
The peer's own closed list of images, mounts, actions and ports it will execute
for a sandbox request. It is narrower than the signed contract and is checked
before the gateway is called.

_Avoid_: whitelist (unqualified), policy

**policy proposal**:
A workload-generated request to change its own sandbox policy. It is inert
until the local approver accepts it; for a session sandbox that is the sandbox
user. The Master cannot approve it.

_Avoid_: proposal (unqualified), request

**policy approval**:
The local decision that accepts or rejects a policy proposal. For a session
sandbox the approver is the sandbox user; a service sandbox's approver is not
yet contracted. It is not a guard approval and carries no Master signature.

_Avoid_: approval (unqualified), consent

**execution request**:
A user-only, signed request to run one argv-only action on the peer inside the
local execution whitelist. It is not a sandbox request and not a shell.

_Avoid_: exec, shell request

**sandbox request**:
A Master-signed envelope asking a peer to inspect or change one sandbox record,
its policy or its service exposure. It carries authority, never knowledge.

_Avoid_: command, instruction, sandbox message

**sandbox supervision**:
The authority a `sandbox-supervise` grant confers: the Master may issue signed
sandbox requests, and the peer executes them against its own gateway within the
local execution whitelist. It does not include approving a workload policy
proposal.

_Avoid_: control, admin, supervision (unqualified)

**service exposure**:
In an OpenShell sandbox, one sandbox-local TCP port made reachable to the peer
through an authenticated gateway forward. It never exposes a host path or the
gateway credential.

_Avoid_: publish, port-forward, proxy (unqualified)

**model proxy**:
The host-side endpoint an OpenShell execution sandbox reaches as
`host.openshell.internal:<port>` for model traffic. It is not a service
exposure.

_Avoid_: model gateway, inference proxy

**session sandbox**:
An execution sandbox created for one sandbox user's session and stopped when
idle.

_Avoid_: user sandbox, temporary sandbox

**service sandbox**:
An execution sandbox declared in a peer's service manifest and never
idle-stopped. Its mount and approval rules are a separate contract decision,
not an extension of a session sandbox.

_Avoid_: persistent sandbox, system sandbox

**sandbox recreation**:
The separate stop/delete/create sequence required after a policy change that
cannot be applied live. It is not a sandbox action and not a restart.

_Avoid_: restart, reload, recreate (unqualified)

### Model serving

**model plane**:
One of the two model-serving surfaces on a node: the node's own AI stack
(Open WebUI/Ollama/Qdrant) or the fabric text engine (`vllm:8000`). They share
the model store and hardware, not a contract.

_Avoid_: model layer, LLM stack

**text engine**:
The OpenAI-compatible inference server behind the `vllm` service on port 8000;
today vLLM, proposed `llama.cpp`/`llama-server` in ADR 0021. It serves the
agent/compute and cluster work, never the vault.

_Avoid_: model server (unqualified), LLM

**OpenAI-compatible engine**:
The `/v1/models`, `/v1/chat/completions` and `/health` surface of the text
engine. The service name and port are historical and stable.

_Avoid_: OpenAI (the vendor), API

**vLLM**:
The current text engine; a Python/PyTorch/xformers/CUDA stack. Its dependency
build is the reason for the migration; it is retired from the AGX text engine.

_Avoid_: engine (unqualified)

**llama.cpp**:
The C++/CUDA inference engine; GGUF; the `llama-server` HTTP surface. The
primary proposed text engine for the AGX nodes.

_Avoid_: Llama (the model family), llama-cpp-python (the bindings)

**llama-server**:
The `llama.cpp` OpenAI-compatible HTTP server; `--jinja`,
`--chat-template-file` and `--system-prompt-file` inject the precontext.

_Avoid_: server (unqualified), vLLM

**GGUF**:
The quantized model file format used by `llama.cpp` and Ollama. A GGUF blob is
a model file, not a vault page.

_Avoid_: model file (unqualified), GGML (the old format)

**quantization**:
The Q4_K_M/Q5_K_M/Q6_K/Q8_0 weight formats; the quality/size/speed tradeoff.
The 136.5 GB/s memory bandwidth makes Q4_K_M the teacher default.

_Avoid_: compression, precision

**Q4_K_M**:
The 4-bit k-quant used for the 32B/35B teacher on the Xavier; responsive, with
Q5_K_M/Q6_K only when the measured tokens/s is acceptable.

_Avoid_: 4-bit (unqualified)

**Q8_0**:
The 8-bit quantization used for the small student; near-lossless and small
enough for the 32 GB peer.

_Avoid_: 8-bit (unqualified)

**n-gpu-layers**:
The `llama.cpp` `--n-gpu-layers` count; 99 means all layers on the unified
GPU/CPU memory.

_Avoid_: GPU layers (unqualified), offload

**context size**:
The `llama-server --ctx-size` / `VLLM_MAX_MODEL_LEN` window; it sets the KV
cache and memory footprint.

_Avoid_: context window (unqualified), max length

**precontext**:
The MASTERSPIKE format plus the fabric digest, injected as the system/chat
template by `spark-precontext.py`; it carries the fabric vocabulary and format,
never a capability or a secret.

_Avoid_: prompt (unqualified), system prompt (the whole)

**MASTERSPIKE**:
The llm-wiki format carrier (a model/prompt, not a capability); the
`masterspike` manifests and the `spark-precontext.py` source.

_Avoid_: master model, master prompt

**model store**:
The on-disk GGUF/model files. The active teacher/student live on the root NVMe;
the cold store, HF cache and traces live on the data drives.

_Avoid_: cache, models (unqualified)

**model catalog**:
`contracts/model-catalog.json`, the role-placement declaration for teacher,
student and embeddings; the `agent-models` and `ai-stack` surfaces are the
node-local views.

_Avoid_: model list, registry (the authority)

**teacher/main model**:
The largest same-version Qwen model on `agx64`; the Q4_K_M distillation source.

_Avoid_: main model (unqualified), teacher (the human)

**student model**:
The smallest same-version Qwen model on `agx32`; the Q8_0/Q4_K_M distillation
target.

_Avoid_: student (the human), small model

**distillation**:
The same-family teacher→student training pipeline; the teacher traces/uplift
are training evidence, never an answer corpus.

_Avoid_: training (unqualified), fine-tuning

**uplift**:
The consented teacher traces, Qdrant snapshots and raw-KV manifests sent to the
Master for training/backup; never served, never knowledge.

_Avoid_: backup, data

**jetson-containers**:
The `dusty-nv` modular container build system; the `llama_cpp`/`ollama`/`mlc`
packages; `autotag`/`build`; the L4T-compatible images.

_Avoid_: containers (unqualified), jetson-containers (the CLI)

**autotag**:
The `jetson-containers` command that resolves the L4T-compatible image tag or
falls back to a build.

_Avoid_: tag (unqualified)

**L4T**:
Linux for Tegra, the Jetson BSP; the AGX Xavier runs r35 (JetPack 5).

_Avoid_: JetPack (the SDK), Ubuntu (the distro)

**JetPack**:
The NVIDIA Jetson SDK; its L4T r35 is the AGX Xavier baseline.

_Avoid_: L4T (the BSP), CUDA

**sm_72**:
The AGX Xavier compute capability; compile with `CUDA_ARCHITECTURES=72` and
`-DCMAKE_CUDA_ARCHITECTURES=72`.

_Avoid_: sm72, arch

**Volta Tensor Cores**:
The AGX Xavier GPU tensor cores; the `sm_72` target keeps them available.

_Avoid_: tensor cores (unqualified), GPU

**unified memory**:
The Jetson CPU/GPU shared memory; 64 GB on `agx64`, 32 GB on `agx32`, with
~136.5 GB/s bandwidth. The model, context and KV cache share it.

_Avoid_: RAM, VRAM

**MAXN**:
The `nvpmodel -m 0` power mode plus `jetson_clocks`; the maximum clocks before
inference.

_Avoid_: max power, performance mode

**nvpmodel**:
The Jetson power-mode tool; `-m 0` selects MAXN, `-q` reports the mode.

_Avoid_: power (unqualified)

**jetson_clocks**:
The Jetson clock tool; `sudo jetson_clocks` fixes the clocks for inference.

_Avoid_: overclock, clocks (unqualified)

**tegrastats**:
The Jetson telemetry tool (RAM/GPU/EMC/temps); the benchmark companion.

_Avoid_: nvidia-smi (the dGPU), telemetry (the fabric)

**Ollama**:
The Go/llama.cpp model server with an OpenAI API; the peer's own AI-stack
server and the fallback text engine.

_Avoid_: LLM (unqualified), model server (unqualified)

**MLC-LLM**:
The TVM-compiled LLM runtime with `mlc_llm serve`; an optional experiment, not
the primary.

_Avoid_: MLC (the library), TVM (the compiler)

**TensorRT-LLM**:
NVIDIA's optimized LLM runtime; heavy, INT4/INT8; not the Xavier default here.

_Avoid_: TensorRT (the general), TRT

**ExLlamaV2**:
The EXL2/GPTQ runtime with a custom PyTorch build; not the path for this
migration.

_Avoid_: ExLlama (the old), GPTQ (the format)

**NanoLLM**:
The `dusty-nv` optimized local inference library; not a drop-in OpenAI server.

_Avoid_: NanoLLM (the container), LLM

**text-generation-webui**:
The oobabooga UI with an OpenAI extension; heavier than the text engine needs.

_Avoid_: WebUI (Open WebUI), UI

**SGLang / TGI**:
High-throughput serving stacks; not the Xavier text-engine path.

_Avoid_: server (unqualified), inference

**vllm-stub**:
The CPU-only deterministic OpenAI stub behind `--engine stub`; the node image
keeps it for the no-GPU graph.

_Avoid_: stub (unqualified), mock

**aux engines**:
The `vllm-embed`, `vllm-rerank` and `vllm-audio` services; llama.cpp/whisper.cpp,
separate from the text engine. The names are historical.

_Avoid_: vLLM (the engine), sidecars (unqualified)

**model file**:
The GGUF/tokenizer/config/precontext set; the active copy on the root, the cold
copy on the data drives.

_Avoid_: model (unqualified), weights

**KV cache**:
The runtime key/value cache; it grows with the context and lives with the
active model on the root.

_Avoid_: cache (unqualified), memory

**HF cache**:
The HuggingFace download cache; a cold artifact on the data drives, not the
active model store.

_Avoid_: model store, cache

**root drive / data drive**:
The NVMe root (`/`) for the active model files, precontext, KV, state and
Docker; the data drives (`/mnt/ai`) for the vaults, cold store, traces and
backups.

_Avoid_: disk (unqualified), SSD

**storage contract**:
The rule that vaults stay on the data drives and active model-calculation files
stay on the root; the `model-store`, runbook and Step 108 implement it.

_Avoid_: storage (unqualified), layout

**teacher traces**:
The teacher model outputs/traces used for distillation; training evidence on
the data drives, never served.

_Avoid_: logs (unqualified), data

**no-teacher-backup**:
The rule that the teacher model is not a backup or an answer corpus; the
model-store/uplift boundary.

_Avoid_: backup (unqualified), mirror

**same-version pair**:
The teacher and student share the Qwen version/tokenizer; the model-selection
rule for a clean distillation.

_Avoid_: same model, family (unqualified)

**model-selection rule**:
Teacher = largest same-version Qwen that fits 64 GB at the best responsive
quantization (Q4_K_M first); student = smallest same-version Qwen at Q8_0.

_Avoid_: model choice, sizing

### Fabric components

**skill catalog**:
The build-time catalog that owns skill copy, digest, manifest and drift checks.
Family adapters supply sources, destinations, exclusions and transforms.

_Avoid_: skill sync, installer

**skill family adapter**:
The skill-catalog adapter for one vendored family or the role catalogs. It owns
that family's source policy and transformations.

_Avoid_: plugin, family

**understand graph**:
The derived code-structure graph built by `/understand`. It is a build
artifact, not an answer corpus.

_Avoid_: code graph, dependency map

**graph producer**:
The side of the understand graph that produces graph data and deltas; it owns
scan and diff semantics.

_Avoid_: scanner, builder

**graph consumer**:
The side that reads an existing understand graph and exposes query, export and
MCP; it does not produce graph data or deltas.

_Avoid_: viewer, server

**graph seam**:
The single stable entry point through which a graph consumer asks the producer
for graph data and deltas. It is not an installed package.

_Avoid_: API, bridge

**graph production**:
The producer's file-scanning and project-metadata work: what files exist, what
language they use and what project they form.

_Avoid_: scanning, parsing

**graph algebra**:
The producer's operations over graph data: normalize, merge, validate, diff,
layers and tour.

_Avoid_: analysis, processing

**opencode workspace**:
One of the three editing contexts: the fabric root, the peer role and the
Master role.

_Avoid_: project, workspace (unqualified)

**release export**:
The build-time process that stages a distribution surface, writes its checksum
manifest and verifies those checksums and the detached signature. It is not a
runtime module and not a knowledge channel.

_Avoid_: release, publish

**listener**:
The shared HTTP surface that owns request parsing, route auth and source
policy, refusals, health and lifecycle. A route handler owns the service
behaviour; the listener owns the transport.

_Avoid_: server, router

**envelope**:
A signed artifact whose canonical bytes are defined by an envelope
specification.

_Avoid_: message, payload

**envelope catalog**:
The single registry of envelope kinds and their fields, signed projection,
signer and verifier. Named message, signing and verification functions are
adapters over it.

_Avoid_: schema, message table

**console surface**:
One read-only view exposed by the node console: its endpoints, `session` or
`admin` auth class and optional menu metadata.

_Avoid_: dashboard, panel

**provenance facade**:
The single entry point through which callers use the provenance lifecycle and
its CLI.

_Avoid_: wrapper, API

**provenance primitives**:
The loader, YAML error re-exports, canonical form, crypto loaders, contract
reader, time and key-path helpers, and shared key-shaped patterns behind the
provenance facade.

_Avoid_: utilities, base

**provenance lifecycle**:
The note, ledger, grant and scan concerns behind the provenance facade. Each
lifecycle is separate, while callers use the one stable entry point.

_Avoid_: provenance, signing

**signer operation catalog**:
The one catalog that names each signer operation's request field, response key,
ledger event and prepare method. The common signer path owns root pinning,
validation, ledger append and response.

_Avoid_: signer API, operation list
