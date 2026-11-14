---
title: sparknet — user manual
updated: 2026-11-05
---

# sparknet — user manual

> The **master manual** for the `reallife-spark` repository set. It explains the
> whole system: what it is, how the five repositories fit together, what the
> contracts are, how the code is laid out, which invariants the build enforces,
> and how to change something without breaking the fabric.
>
> The four sibling repositories have their own manuals, listed in
> [§11](#11-where-the-rest-of-the-system-lives). Read this one first.

---

> **Current deployment (2026-11-05).** `agx64` is the peer and the only human
> user surface. `agx32` is the Master and is **admin-only**. Open WebUI is
> `v0.13.0` on both; the agent execution path is the loopback OpenCode engine
> (`2.2.5`, live 2026-11-06) on `4204`, with one sandbox per user's `peer-<user_id>` vault. The
> old cluster2 Master WebUI on `8181` is retired. Prompts, tools, functions and
> per-user models are installed by `peer-node/scripts/sparknet-webui-workspace.py`.

---

## Table of contents

1. [What sparknet is](#1-what-sparknet-is)
2. [Orientation](#2-orientation)
3. [The five repositories](#3-the-five-repositories)
4. [The architecture](#4-the-architecture)
5. [The authority model](#5-the-authority-model)
6. [The contracts](#6-the-contracts)
7. [The node image and its services](#7-the-node-image-and-its-services)
8. [The knowledge vault](#8-the-knowledge-vault)
9. [Build, run, test](#9-build-run-test)
10. [The gate](#10-the-gate)
11. [Where the rest of the system lives](#11-where-the-rest-of-the-system-lives)
12. [How to make a change correctly](#12-how-to-make-a-change-correctly)
13. [Configuration reference](#13-configuration-reference)
14. [Troubleshooting](#14-troubleshooting)
15. [Spec vs implemented](#15-spec-vs-implemented)
16. [Glossary](#16-glossary)

---

## 1. What sparknet is

sparknet is a **two-role fabric** for self-hosted GPU nodes. One node in the
cluster — the **Master** — holds an Ed25519 private key and decides what every
other node may do. Every other node is a **peer**: it verifies the Master's
decisions and can never authorise anything for itself. The two roles talk over a
WireGuard overlay (`10.100.0.0/24`); each node serves its own knowledge vault
and its own local inference.

The central security property, and the thing to understand before reading any
code here:

> **Authority comes from key possession, not from a capability grant.**

A peer that somehow obtained the entire capability vocabulary would still be
unable to grant, revoke or escalate anything, because the signature it would
need to produce requires a private key it does not have. Capabilities say *what*
a node is allowed to do; the key says *whether anyone believes it*.

The repository you are in is not a node. It is the **fabric root**: the contract
both roles obey, the shared implementation both roles load, the two role
subtrees, the node image surface, and the tooling that keeps all of it in
agreement.

**Who this manual is for:** a developer who has to change something in this
repository — and needs to know which of the five repositories owns it, which
contract it must not violate, and which gate will tell them they got it wrong.

**What this manual is not:** an operator runbook. The operational procedures
live in `contracts/deployment-runbook.md` and
`contracts/spark-node-runbook.md`, and are referenced from here rather than
duplicated.

---

## 2. Orientation

If you read nothing else, read this table.

| Path | What it is |
|---|---|
| `contracts/` | The cross-role **single source of truth**: overlay, capabilities, identity, ports, and the guard / share / consensus / health / provenance / proposal protocols. Nothing executable. |
| `shared/` | The one implementation of the signed canonical form and the protocols that ride on it. Loaded **by path** by both roles. |
| `peer-node/` | The peer role: a working node with its own vault, guard, anchor, dispatch bridge, and wiki suite. Published as the `sparknet-peer` repository. |
| `master-node/` | The master role: the elected signing node. Runs the peer's services *by path*; owns the isolated signer. Published as the `sparknet-master` repository. |
| `goagx/` | The AGX Xavier twin of the node image surface. Published as the `goagx` repository. |
| `scripts/` | Fabric-level tooling: bundling, env init, contract rendering, SBOM, the resource-first search helper, the pre-merge gate. |
| `tests/` | The fabric-level suite: contract conformance, layout, claims, election, consensus, layout registries. |
| `sbom/` | The generated CycloneDX SBOM. Never hand-edited. |
| `spark.docker`, `spark.compose.yml` | The DGX Spark node image and its compose graph. The image build context **is the repository root**. |
| `goagx/sparknet.agx.docker`, `goagx/sparknet.agx.compose.yml` | The AGX Xavier equivalents. Same service contract, different silicon. |
| `sparknet-node-setup.sh` | The one-command host bring-up (`--platform spark|agx`). |
| `spark-entrypoint.sh` | The in-container dispatcher every service runs. |
| `.opencode/skills/` | The base skill tree — 81 skills (32 vendored wiki suite, 2 local, 9 understand, 38 mattpocock), pinned where vendored, no global skill farm. |
| `<role>/.opencode/skills/` | The role-local sellable catalog, generated by `scripts/sync-role-skills.py`; provenance and licenses in `.inventory.json`. |
| `VERSION` | The single source of truth for the fabric version (SemVer). |

Read [README.md](README.md) for the one-screen orientation, and the charter
(`AGENTS.md`) before you read anything else: it states the roles, the layout,
the Memory and Plan protocols, and the boundaries. This manual explains the
*code*; the charter explains the *rules*.

> **Link discipline.** Every link in this manual resolves in the repository it
> is published into. The fabric root publishes this manual at the root of the
> `goagx` distribution as well, where `README.md` is the generated distribution
> README and the charter is the role charters' — so the charter is named here
> in prose rather than linked, and every other cross-repository path in this
> manual is written the same way.

---

## 3. The five repositories

The `reallife-spark` organisation holds five private repositories. They are not
independent products — they are five views of one system.

```
                        reallife-spark/sparknet            ← THIS repository
                        (the fabric root: contracts + shared + both roles)
                                  │
        ┌─────────────────────────┼──────────────────────────┐
        │                         │                          │
        ▼                         ▼                          ▼
 reallife-spark/         reallife-spark/           reallife-spark/
   sparknet-peer           sparknet-master             goagx
   (peer-node/ subtree)   (master-node/ subtree)     (generated distribution)
        │                         │                          │
        └─────────────────────────┴──────────────────────────┘
                                  │
                                  ▼
                        reallife-spark/goSpark
                        (the Go control/service plane)
```

| Repository | Contains | Published how | Manual |
|---|---|---|---|
| `sparknet` | The fabric root. `contracts/`, `shared/`, both role subtrees, the node image surface, the tooling, the gates. | Normal git. | **This manual.** |
| `sparknet-peer` | The `peer-node/` subtree, verbatim. The role alone — no `contracts/`, no `shared/`. | Verbatim copy of the subtree. | `sparknet-peer/USER_MANUAL.md` |
| `sparknet-master` | The `master-node/` subtree, verbatim. The role alone. | Verbatim copy of the subtree. | `sparknet-master/USER_MANUAL.md` |
| `goagx` | A generated mirror of the fabric: both role subtrees, `contracts/`, `shared/`, the AGX image surface, the setup script. | One-way export (`make goagx-publish`). Never hand-edited. | `goagx/USER_MANUAL.md` |
| `goSpark` | The Go control and service plane: identity, authz, dispatch, routing, gateway, GPU telemetry, KV transfer. A sibling, not a replacement; checked out locally at `gospark/` (its own `.git`, gitignored). | Normal git. | `gospark/USER_MANUAL.md` |

### 3.1 The rule that explains the layout

> **A role subvault alone is not a deployment.**

A peer cannot verify a signature without `contracts/` and `shared/`. If you
clone only `sparknet-peer` and try to run it, validation fails **on purpose**
rather than pretending to work. `make bundle` assembles what a node actually
needs: the role, plus `contracts/`, plus `shared/`, plus `scripts/`, plus the
vendored wiki suite and `opencode.json`.

This is also why `sparknet-peer` and `sparknet-master` carry no `contracts/`
directory: they are the role, not the deployment. The `goagx` repository is
different in kind — it is a *complete* deployment tree, generated in one
direction from the fabric.

### 3.2 The Go/Python split

`goSpark` implements the fabric's **control and service plane**; the fabric
itself implements the **compute plane**. The rule (goSpark ADR 0001):

> Go runs the control and service plane; Python/CUDA runs the compute plane.

The peer guard, the overlay anchor, and the Python/CUDA compute worker stay
here. goSpark is a sibling repository, checked out at `gospark/` (its own
`.git`, gitignored and gated in place), that consumes the fabric's contracts
(read-only snapshots of them live in `gospark/spec/sparknet/`) and drives the
node's task dispatch, API gateway and GPU telemetry. The fabric's Python
services and goSpark's Go services coexist in the same node container; they
share the NATS bus, not a process.

---

## 4. The architecture

### 4.1 The layers

```
┌───────────────────────────────────────────────────────────────┐
│  contracts/     the rules both roles agree on (no code)       │
│                 overlay · capabilities · identity · ports ·   │
│                 guard · share · consensus · health ·           │
│                 provenance · proposal                         │
├───────────────────────────────────────────────────────────────┤
│  shared/        the one implementation of those rules         │
│                 sparknet-authz.py · -consensus.py · -election  │
│                 -provenance.py · -proposal.py · -merkle.py …  │
├───────────────────────────────────────────────────────────────┤
│  peer-node/     the peer role: guard, anchor, dispatch bridge, │
│                 share regime, vault provisioner, wiki vault    │
│  master-node/   the master role: signer, ledger, parity,      │
│                 admin console — loads peer services by path    │
├───────────────────────────────────────────────────────────────┤
│  spark.docker + spark.compose.yml      the node image + graph  │
│  goagx/…                              the AGX twin of the same  │
├───────────────────────────────────────────────────────────────┤
│  goSpark (separate repo)   Go control plane: dispatch,       │
│                            routing, gateway, GPU telemetry,    │
│                            NVFP4 KV transfer                  │
└───────────────────────────────────────────────────────────────┘
```

### 4.2 How the roles relate

A **Master is a peer that won an election, not a separate species.** A cluster
is a pair or a trio; every member holds the same capabilities and runs the same
services; one additionally holds the operational key and signs. That is the
entire difference — which is why `master-node/services/sparknet-parity.py`
loads `../peer-node/services/*` **by path** instead of carrying copies. Two
copies of a signature-verifying service would drift silently and then stop
validating each other.

| Concern | Peer | Master |
|---|---|---|
| Signing key custody | never | **exclusive** — never leaves the machine |
| Registry authorship | never | **authoritative** |
| Overlay address | `10.100.0.x/32`, one address | `10.100.0.1` |
| Network egress | restricted to the Master only | **unrestricted** (the peer rule would blackhole the fabric) |
| Own vault, local inference | **authoritative** | authoritative |
| Revoke any node | never | yes, instantly, from its own side |
| Signing new authorisations | **never** | yes |

The egress asymmetry is the cleanest statement of the difference: a peer may
reach only the Master; the Master reaches everyone. A rule that is correct on a
peer is actively harmful on the Master.

### 4.3 The node's control path, end to end

1. The Master's signer signs a **registry entry** (an identity, a capability
   set, an overlay address, validity timestamps) with the operational key.
   Entries are signed **per entry**; the registry document itself is unsigned,
   so a revoked flag lives inside the signature.
2. The signed entries are assembled into a **publication** — the channel
   described by `contracts/registry-publication.json`: the five-field
   publication, a signed projection and its digest, and a **monotonic
   sequence** that only increases.
3. The Master **pushes** the publication to each peer's guard on `9090`, and
   the `sparknet-registry-deliver.timer` retries every 60 s. Re-pushing a
   publication the peer already installed is a **success**
   (`REGISTRY_ALREADY_INSTALLED`, nothing written), so the timer's steady state
   is a green unit; a lower sequence is refused (`stale_publication`), which is
   what stops a revocation from being undone. The overlay anchor address is
   skipped, because it is the Master, not a peer.
4. The peer's **guard** verifies the publication against the pinned Master
   public key. A valid publication plus the `guard-apply` capability plus
   `euid 0` plus a protected target path plus `--apply-enabled` (off by
   default) is what actually turns into a filesystem write.
5. Separately, the Master's **peer-intake listener** on `8090` accepts a
   peer's telemetry report and its RFI (request-for-information) requests,
   attributing both to the WireGuard-authenticated source through the signed
   registry. It carries no authority: it records evidence and queues a
   question, and it never answers.
6. Every step is written to the peer's hash-chained **ledger** and every note to
   the **provenance** chain.

A peer that loses its anchor degrades to standalone: the vault still works, the
guard refuses to bind and refuses to apply. That asymmetry is deliberate — a
node that has lost its Master has lost its authority, and the correct response
is to keep it useful but inert.

---

## 5. The authority model

### 5.1 The capability vocabulary

The vocabulary is **closed**. Anything not in `contracts/capabilities.json` is
rejected by both roles, and adding to it is a contract change that must land
there first.

| Capability | Grants | Sensitive |
|---|---|---|
| `telemetry` | Push metrics and node status to the Master. | no |
| `p2p-sync` | Accept and serve user-space vault sync over the overlay. | no |
| `push-receive` | Accept pushed artefacts from the Master or a sibling peer. | no |
| `guard-apply` | Apply Master-approved changes to protected files: lift `chattr +i`, write, re-pin. | **yes** |
| `cluster-vote` | Cast one signed vote in a master election. | no |
| `cluster-dispatch` | Submit a cluster job: split a prompt into signed subtasks and fan them out. | no |
| `cluster-serve` | Accept and execute dispatched subtasks. | no |
| `admin-supervise` | Supervise a node's admin surface. | **yes** |
| `cross-department-share` | Offer or accept a share with a node whose Master-attested `department` differs from this node's own. Inside a department, the ordinary share rules need no extra grant. | **yes** |

`guard-apply` is the one that matters operationally: without it the guard
verifies and audits but refuses to apply, however valid the signature is.
`cluster-vote` is deliberately weak — a vote is deduplicated by member
identity, so three votes for yourself is still one vote. It confers nothing; it
is a say, not a grant.

`cross-department-share` is the newest and the subtlest. The department it
compares is the one in the **signed registry entry**, never anything a node
says about itself — a self-declared department would let a node claim its way
into whichever department it wanted to read, and in-department sharing is the
*easier* path, so that is exactly the direction an attacker would push. The
boundary binds only when both sides carry an attested department and the two
differ; where the Master has attested none, there is no boundary to cross.

### 5.2 The signed envelope

`shared/sparknet-authz.py` is the **one** implementation of the signed
canonical form, and it is deliberately singular: two copies of signing or
canonicalisation code is a security bug waiting to happen, because they can
drift and then silently stop validating each other. It is never copied into a
role subtree; both roles load it by path through `shared/sparknet_loader.py`.

The envelope covers the fabric's `signed_envelope_fields`: `fingerprint`,
`identity`, sorted `capabilities`, `overlay_ipv4`, `issued_at`, `expires_at`,
`revoked`. The registry document itself is **unsigned** — each *entry* is
signed, so a revoked flag lives inside the signature and only the Master can
set it. A trust anchor is a pinned public key, never a key embedded in the
document you were handed.

`shared/sparknet-authz.py` exposes: `fingerprint`, `generate-keypair`,
`verify`, `sign`, `grant-mint`, `grant-verify`.

### 5.3 The three master keys

A master node forms **three** distinct Ed25519 keys, and the split *is* the
security model rather than a detail:

| Key | Purpose |
|---|---|
| **Cluster key** | participates in the election and the cluster trust root |
| **Operational key** | signs the registry and approvals — the key the fabric's authority derives from |
| **Identity key** | the node's own identity and fingerprint |

The operational key lives in `$SPARKNET_STATE_DIR/keys` at mode `0600`, and the
state directory resolves **outside** the vault. Outside, not merely gitignored:
the admin surface bind-mounts the vault read-only into an LLM container, so a
gitignore would not have helped. `make keys-check` enforces both halves.

The operational key is only ever held by **one** process: `sparknet-signer.py`,
the isolated signer. Everything else in the role is multi-user, LLM-driven, and
reads configuration as input. If that surface could reach the key, a prompt
injection would grant itself the one capability the peer roles withhold.

---

## 6. The contracts

`contracts/` is the single source of truth for everything the Master and its
peers must agree on. Neither role hard-codes these values; both read them from
here. If a value appears in `master-node/` or `peer-node/` as well as here,
that is a bug — `tests/test_contracts.py` fails on it.

Before the split, that agreement was implicit in duplicated constants
scattered across scripts: `10.100.0.1` appeared in six places and nothing
detected a mismatch. Explicit contracts make the agreement checkable — a peer
that drifts fails `make contract-test` instead of failing silently at handshake
time.

| File | Governs |
|---|---|
| `overlay.json` | Addressing, MTU, keepalive, AllowedIPs discipline. |
| `capabilities.json` | The closed capability vocabulary and who may hold each. |
| `identity-schema.json` | Canonical identity, fingerprinting, the signed envelope. |
| `registry-schema.json` | The shape of the node-authorization registry: the document the Master signs and a peer verifies, its entries, and the `signature_b64` field name. |
| `registry-publication.json` | The channel that carries a registry: the five-field publication, the signed projection and digest, the monotonic sequence, the peer's acceptance order and refusal codes, and the re-delivery window. |
| `ports.json` | Every listener and dial target, with `implementation_state` (code) kept separate from `runtime` (observed on one host). |
| `guard-protocol.md` | The Master↔peer approval conversation. |
| `guard-approval.json` | The approval envelope itself: the signed fields, the canonicalisation rule, where the capability comes from, and the transport. |
| `health-protocol.md` | Peer liveness and eviction: probe rhythm, activity-trumps-eviction, the full-dark rule. |
| `telemetry-schema.json` | Peer→Master observability evidence: overlay-attributed, unsigned, `kind`-tagged reports the Master records and acts on nothing. |
| `rfi-schema.json` | The request-for-information channel: the peer's overlay-attributed request, the Master's signed answer, the digest binding its content, and the `01_Inbox/` destination rule. |
| `reflex-schema.json` | The typed decision contract for the reflex layer: a local sensor, never authority; abstain is first-class, and the backend vocabulary has no egress member. |
| `share-protocol.md` | The peer↔peer sharing regime: offers, share types, the four clocks, trust levels, isolation, evidence. |
| `consensus-protocol.md` | How the members agree on who holds the signing key: election, the cluster trust root, re-formation. |
| `provenance-protocol.md` | The narrative behind the tracking schema: the accountability chain, stale-vs-invalid, ledger-only approvals, secret custody. |
| `proposal-protocol.md` | The narrative behind the proposal schema: why a review is a first-class object, the fail-closed transitions, what a verified chain is *not*. |
| `tracking-schema.json` | The numbered vault layout, the per-note tracking block and its signature, the user record, the approval record, the secret index. |
| `proposal-schema.json` | The cross-user proposal workflow: proposal/review/decision records and the draft→submitted→reviewed→decided lifecycle. |
| `manifest.json` | **Generated.** The machine-readable inventory: each JSON contract by hash, plus the projected capability and port tables. Rendered by `scripts/sparknet-render.py`; never hand-edited. |
| `deployment-runbook.md` | The operational procedure for bringing a real multi-node system up: overlay, election, signer unit, registry, rollback. |
| `admin-federation-runbook.md` | The operational procedure for live cross-node admin federation: addressing, the route-class binding change, the `admin-supervise` grant, the node agent, the console, rollback. |
| `spark-node-runbook.md` | The operational procedure for the node image in both platform variants, and what is provable without a GPU. |

### 6.1 The registry distribution channel

The registry is not a file that is copied around. It is a **publication**:

```
 signed registry entry ──► publication ──► push to each peer's guard :9090
 (per entry, by the        (five fields,     (sparknet-registry-deliver,
  operational key)         signed digest,    retried every 60 s)
                           monotonic
                           sequence)
```

`contracts/registry-schema.json` states the registry's shape;
`contracts/registry-publication.json` states the channel that carries it. The
acceptance rule lives in `shared/sparknet-registry-install.py`, and both the
Master's deliverer and the peer's guard use it, so the two cannot disagree:

| Publication arrives | Answer | Written? |
|---|---|---|
| sequence **lower** than installed | `409 stale_publication` | no — this is what stops a revocation being undone |
| sequence **equal**, same digest | `REGISTRY_ALREADY_INSTALLED` | no — the timer's steady state |
| sequence **equal**, different digest | `409 stale_publication` | no — a fork |
| sequence **higher**, valid signature | accepted | yes |

The Master's deliverer skips the overlay anchor (`10.100.0.1`) because that
address is the Master itself, not a peer, and records the skip explicitly
rather than failing the unit.

### 6.2 Changing a contract

1. Edit the file in `contracts/`.
2. Run `make contract-test` — it tells you which role files now disagree.
3. Update the affected role's files **in the same commit**.
4. Bump `schema_version` in the file you changed.

Never edit a contract to make a test pass without asking whether the *other*
role should change too. That question is the entire value of this directory.

### 6.3 What is deliberately not here

Nothing executable. Contracts state rules; `shared/` binds them to code; each
role wraps that code in its own CLI. Note the layering that keeps signing,
ledger appending and provenance verification honest:
`shared/sparknet-provenance.py` loads authz *by path* and adds no crypto of its
own.

---

## 7. The node image and its services

### 7.1 The two platform variants

The node image surface is a **pair**, selected together by one flag:

| | DGX Spark (`--platform spark`) | AGX Xavier (`--platform agx`) |
|---|---|---|
| GPU / arch | GB10, `sm_121a` | Xavier, `sm_72` (Volta) |
| Memory | 128 GB unified | 64 GB (`agx64`) / 32 GB (`agx32`) |
| Node base | `nvcr.io/nvidia/vllm:26.04-py3` | `nvcr.io/nvidia/l4t-pytorch:r35.2.1-pth2.0-py3` (cu114, Python 3.8) |
| Engine | prebuilt vLLM wheels | **`llama.cpp` `llama-server`** (`sparknet-llm:agx`, base `dustynv/llama_cpp:r35.2.1`) |
| Image files | `spark.docker` | `goagx/sparknet.agx.docker` + `goagx/sparknet-llm.docker` |
| Compose file | `spark.compose.yml` | `goagx/sparknet.agx.compose.yml` |

`--platform` picks the compose file **and** the env-file together, so a node can
never build the AGX image against the Spark compose, and switching platforms
never inherits the other's base/model lines. `spark.compose.cpu.yml` layers
onto either and overrides command/env/device reservations, and on AGX it also
selects the node image's `vllm-stub` (the LLM image has no stub).

The AGX vLLM source build was the blocker: the operator could not satisfy its
Python/PyTorch/xformers dependency stack on either Xavier host. The
resource-first review of `dusty-nv` (recorded in
`references/dusty-nv-jetson-llm-containers-2026-11-13.md`) selected
`jetson-containers` `llama_cpp` as the engine and Ollama as the fallback and
the peer's own AI-stack server. The decision is
`docs/adr/0021-agx-llm-engine.md`; the stable `vllm` service name, port 8000
and OpenAI endpoints remain. The node image keeps goSpark, compute, the aux
engines, the bundle and the stub; the engine image carries `llama-server` and
the precontext proxy.

The active AGX pair is Qwen3-30B-A3B-2507 Q4_K_M on `agx64` (main and
teacher) and Qwen3-4B-2507 Q4_K_M on `agx32` (student), both at 262,144
context with q8 KV. `scripts/sparknet-model-set.py --role master|peer --set
qwen3-2507|qwen3.6 --precontext on|off` selects the engine file; the
`qwen3-4b-candidate` set points at the distilled student copy on `agx64`.
The peer stack also carries Qwen3-Coder-30B (65k), Qwen3-Embedding-0.6B
(RAG/reindex) and Qwen3-VL-4B (Ollama/Open WebUI, 65k).

The previous Qwen3.6/Qwen3-32B bake-off numbers are historical; Step 110
re-runs the measurements with the new pair.

### 7.2 The compose graph

`spark.compose.yml` declares the services below. The AGX compose declares the
same service names, container names, profiles and published ports — parity is
asserted by `tests/test_agx_node.py`.

| Service | Role |
|---|---|
| `nats` | The NATS/JetStream bus everything else talks over. |
| `vllm` | The text engine (OpenAI-compatible; `llama-server` on AGX). |
| `vllm-embed` | The embedding profile. |
| `vllm-rerank` | The rerank profile. |
| `vllm-audio` | The audio profile (whisper.cpp on AGX). |
| `compute` | The Python/CUDA compute worker — the compute plane. |
| `kvrouter` | The RadixAttention KV-residency daemon. |
| `agent` | The node agent: reports health, verifies signed tasks, executes the closed operation whitelist. |
| `memory` | The Go typed-memory store on loopback. |
| `memory-gateway` | The Python authority front door in front of memory. |
| `control` | The control plane — only meaningful with `--role master`. |
| `gpu` | The GPU-telemetry sidecar (NVML + DCGM). |
| `webui` | Open WebUI. |
| `qdrant` | The node-local vector store (`vector` profile). |
| `ingest` | The vault crawler / chunker / embedder driver. |
| `backup` | The signed snapshot / verify / restore daemon. |
| `opencode` | The agent surface inside the node. |

Profiles (`embed`, `rerank`, `audio`, `webui`, `kv`, `control`, `ingest`,
`vector`, `backup`, `opencode`) are how optional services are switched on.

### 7.3 The entrypoint

`spark-entrypoint.sh` is the single dispatcher every service runs, and it is a
**subcommand** interface, not a per-service script:

```
vllm   vllm-stub   compute   kvrouter   agent   control   gpu
nats   ingest      backup    memory     memory-gateway   opencode
llama-embed   llama-rerank   whisper-asr   precontext   shell
```

`vllm-stub` is the CPU-only, GPU-free stand-in that lets a node with no GPU
bring the whole graph up and round-trip through the agent ↔ engine ↔ compute
path. That is the smoke test the CI container leg runs.

`spark-precontext.py` bakes the fabric's MASTERSPIKE text and digest into the
precontext. On Spark the chat template carries it; on AGX the
`sparknet-llm-proxy.py` proxy merges it into the first system message before
`llama-server` sees the request. It is capped
(`SPARKNET_PRECONTEXT_MAX_BYTES`) because an uncapped precontext overflows the
engine's context window — on the AGX the 8 192-token window holds roughly
4 771 prompt tokens.

### 7.4 The two port namespaces

`contracts/ports.json` records two namespaces, and they are not the same thing.

**Fabric namespace** (the overlay; the two roles' listeners):

| Port | Service | Bound by | State | Overlay only |
|---|---|---|---|---|
| 51820/udp | wireguard | both | implemented | no (the Master must be dialed from behind NAT) |
| 4096 | dispatch-bridge | peer | implemented | no |
| 4097 / 4098 / 4100 | agent-engineering / agent-cyber / agent-vault-curator | peer | provisioned | no |
| 4200 | opencode-serve | peer | spec-only | no |
| 4201 / 4202 | share-intake / session-transfer | peer | implemented | yes |
| 4203 | share-ratification | master | implemented | yes |
| 4210 | cluster-election | both | implemented | yes |
| 4211 | liveness-probe | peer | implemented | yes |
| 4220–4223 | git-repo / file-share / nat-gateway / vector-embed | master | implemented | yes |
| 4224 | reflex-broker | master | implemented | yes |
| 8088 | admin-surface | master | provisioned | yes |
| 8090 | master-peer-intake | master | implemented | yes |
| 9090 | guard | peer | implemented | yes |

`4203` and `4220`–`4224` are implemented; `4200` remains spec-only. `8090` is
the **peer-intake** listener (telemetry and RFI requests), not the retired
instant-push stub.

**Node namespace** (the docker host-publishes inside the node; all implemented):

| Port | Service | | Port | Service |
|---|---|---|---|---|
| 3000 | node-webui | | 8081 | node-control-gateway |
| 4200 | node-opencode | | 8899 | node-control-admin |
| 4222 / 8222 | node-nats / monitor | | 9090 | node-compute |
| 8000 | node-vllm | | 9100 | node-kvrouter |
| 8001–8003 | embed / rerank / audio | | 9180 | node-control-metrics |
| 8080 | node-agent-gateway | | | |

A shared *number* is not a collision — the **address** decides. `implementation_state`
in the contract says whether the code exists; `runtime` says what was observed
on one particular host at measurement time, and is explicitly not a contract fact.

### 7.5 Bring-up

```sh
./sparknet-node-setup.sh                       # text node (nats vllm compute agent gpu)
./sparknet-node-setup.sh --role master         # + the control plane
./sparknet-node-setup.sh --profiles embed,webui
./sparknet-node-setup.sh --engine stub         # CPU-only smoke, no GPU, no model
./sparknet-node-setup.sh --platform agx        # the AGX Xavier variant
./sparknet-node-setup.sh --master-pub "$KEY" --registry /path/registry.json up
```

The script is idempotent and writes exactly three things on the host: the node
state under `peer-node/.state` (gitignored, `0600`/`0700`), the staged bundle
tarball, and the compose env-file. **No secret ever enters an image layer.**

Joining a running fabric means handing the node the elected Master's public
key and the Master-signed registry, instead of running open and self-signed.

---

## 8. The knowledge vault

This repository is also a knowledge vault. The fabric root, `peer-node/` and
`master-node/` are **three separate vaults**, each with its own `.env`, its own
category skeleton and its own `AGENTS.md`.

The skills resolve the vault from the **nearest** `.env`. That is what keeps a
role subvault honest: a session started inside `peer-node/` resolves to
`peer-node/`, not to the parent. Run `make wiki-preflight` before using a
skill; if it fails, run `scripts/sparknet-env-init.sh` once. Never work around
the failure — a silent fallback resolves a *different* vault and every page
lands in the wrong place with no error at all.

Each role also has a deterministic `.opencode/skills/.catalog.json`. OpenCode
advertises only the featured set from `contracts/skill-policy.json`;
`scripts/sparknet-skills.py search …` and the read-only `sparknet-skills` MCP
reach the rest. The Open WebUI engine mounts the same catalogs into each
per-user sandbox, so `sparknet-chat`, `sparknet-plan` and `sparknet-build` use
the same access path. See ADR 0020.

The role vaults use a numbered PARA layout (`00_System` … `07_Archives`) with
the legacy category names kept as **symlinks** to their numbered homes, so
both spellings name one file. `make shims-check` proves every legacy name is
still a symlink; `tests/test_shims.py` enforces it.

| Path | Holds |
|---|---|
| `00_System/` | `user.md`, `alpha-agent.md`, `schema.yaml`, `secrets-index.json`, `index.md`, `log.md` |
| `01_Inbox/` | unprocessed intake awaiting dispatch and signature |
| `02_Daily/` | journal entries and session memory (`YYYY-MM-DD.md`) |
| `03_Sources/` | external material and raw captures |
| `04_Evergreen/` | stable evergreen material |
| `05_Knowledge/` | `concepts/`, `entities/`, `skills/`, `synthesis/` |
| `06_projects/` | per-project knowledge |
| `07_Archives/` | superseded material and vault snapshots |

Two protocols govern everything written here:

- **Memory Protocol** — `MEMORY.md` is *standing state only* and is replaced,
  never appended to indefinitely. The full record of a session goes to
  `sessions/YYYY-MM-DD.md`. History is never back-written into `MEMORY.md`.
- **Plan Protocol** — `PLAN.md` is the single source of truth for multi-step
  work. `current:` marks the step being worked. A step is marked complete only
  after its DoD is verified, and the file is written back immediately. Every
  transition appends one line to `log.md`.

---

## 9. Build, run, test

### 9.1 Setup

```sh
make devtools      # optional .venv with cryptography, pytest, ruff
make env-init      # write each vault's .env and category skeleton
make hooks         # point this clone at .githooks/ so commits run keys-check
```

Exactly one third-party package is required at runtime: `cryptography>=42`,
because Ed25519 is not in the standard library. `pytest` and `ruff` are
optional; the suite runs without them.

### 9.2 The suites

```sh
make test-all      # every suite: contract, fabric, peer, master
make test-peer     # the peer suite alone
make test-master   # the master's parity + spec suite
make contract-test # the cross-role check alone: contracts/ vs both roles
make validate      # both roles' charters, plans and manifests
make test-report SCOPE=all   # JUnit XML + .state/reports/summary.json
```

`make test-all` reaches every suite; `tests/test_layout.py` asserts that the
root Makefile actually delegates to both roles, so "all" cannot quietly mean
less.

The fabric suite at `tests/` covers the cross-cutting concerns. The groups
below are the map, and `ls tests/` is the enumeration.

| Group | Files |
|---|---|
| Contracts and authority | `test_contracts.py`, `test_authz_golden.py`, `test_registry_crossverify.py`, `test_consensus.py` |
| Election and trust roots | `test_election.py`, `test_election_simulation.py`, `test_election_container.py` |
| Layout, claims and key hygiene | `test_layout.py`, `test_claims.py`, `test_agents.py`, `test_shims.py`, `test_keys.py`, `test_identity_pages.py` |
| Gate, release and tooling | `test_ci.py`, `test_shell.py`, `test_release.py`, `test_render.py`, `test_role_skills.py`, `test_wiki_skills.py`, `test_nv_search.py`, `test_notify.py`, `test_plugin.py` |
| Node and image | `test_cpu_node_smoke.py`, `test_agx_node.py`, `test_goagx_repo.py`, `test_node_setup_join.py`, `test_service_timeouts.py`, `test_hardening.py` |
| Vault and knowledge | `test_vector.py`, `test_precontext.py`, `test_rag_corpus.py`, `test_vector_corpus.py`, `test_provenance.py`, `test_proposal.py`, `test_oob.py` |
| Evidence, liveness and transport | `test_checkpoints.py`, `test_merkle.py`, `test_checkpoint_anchor.py`, `test_idle_evidence.py`, `test_liveness.py`, `test_liveness_service.py`, `test_telemetry_push.py`, `test_http_transport.py` |
| Reflex layer | `test_reflex_contract.py`, `test_reflex_plan.py`, `test_reflex_rag.py` |
| Telemetry without hardware | `test_gpu_telemetry_hardware_free.py` |

Three of these are worth calling out because they are the ones a newcomer
underestimates: `test_claims.py` enforces that live surfaces state current
truth (counts match disk, and past-true statements stay dead);
`test_layout.py` enforces that the documented layout matches the tree, that
links resolve and that no host path is hard-coded; and
`test_registry_crossverify.py` proves the Python and Go verifiers agree, so
the two implementations cannot drift apart.

### 9.3 The `sparknet` CLI

`scripts/sparknet` is a thin router over `make`, so the Makefile stays the
single source of truth for what every gate does:

```sh
scripts/sparknet help
scripts/sparknet validate | test | contract-test | lint | format-check
scripts/sparknet render | render-check | drift-check
scripts/sparknet sbom | sbom-check | keys-check | shims-check | wiki-verify
scripts/sparknet bundle peer
scripts/sparknet layout | version
SPARKNET_DRY=1 scripts/sparknet test   # print the make invocation, run nothing
```

### 9.4 Bundles

```sh
make bundle ROLE=peer BUNDLE_SIGN_KEY=/path/to/bundle.key
make bundle-verify ROLE=peer BUNDLE_PUBKEY=/path/to/bundle.pub
make bundle ROLE=master BUNDLE_SIGN_KEY=/path/to/bundle.key
make bundle-verify ROLE=master BUNDLE_PUBKEY=/path/to/bundle.pub
```

A bundle carries the role, `contracts/`, `shared/`, `scripts/`, the vendored
wiki suite and `opencode.json`, plus a `SHA256SUMS` manifest. Verification
extracts the archive to a **different path** and runs `env-init`, the wiki
preflight, role validation and that role's test suite from the extracted copy —
which is what makes "self-contained" a checked claim rather than a description.
Verification also needs the detached signature produced by `BUNDLE_SIGN_KEY`
and a pinned `BUNDLE_PUBKEY`; an unsigned build cannot be verified.
`.env` is never bundled: it records machine-local paths, so deployment runs
`scripts/sparknet-env-init.sh` as its first step.

### 9.5 goSpark

The checkout lives at `gospark/` in this fabric (a separate Git repository;
`GOSPARK_DIR` overrides it for the setup script and compose).

```sh
cd gospark
make build        # pure-Go binaries into bin/ (CGO_ENABLED=0)
make build-gpu    # the cgo GPU sidecar (NVML + DCGM)
make test         # all tests
make ci           # fmt-check + vet + golangci-lint + race tests  ← the gate
```

---

## 10. The gate

The **local pre-merge gate is authoritative**. `make ci` runs
`scripts/pre-merge-gate.sh`, which runs every check a merge must pass, in a
fixed order, and reports *every* failure it finds rather than stopping at the
first — a merge blocked on one step that then reveals two more is three review
cycles instead of one.

```sh
make ci                 # the full gate
make ci CI_QUICK=1      # the fast gates only (skips the full suite)
scripts/pre-merge-gate.sh --quick
```

The gate steps, and the file that enforces each rule:

| Step | What it enforces | Enforced by |
|---|---|---|
| `context-check` | Every generated `CONTEXT.md` is current. | `scripts/sparknet-context-pack.py --check` |
| `governance-check` | The five-file shape, budgets and template parity. | `scripts/sparknet-governance-check.py` |
| `phase8-check` | The Phase 8 inventory covers every file and is well formed. | `scripts/sparknet-phase8-inventory.py` |
| `keys-check` | No tracked key material; `.state/keys/` and `.state/secrets/` are `0600` (dirs `0700`). | `scripts/sparknet-keys-check.sh` |
| `shims-check` | Every legacy category name is still a symlink. | `tests/test_shims.py` |
| `lint` | Ruff over the whole fabric: `E,F,I,UP` plus `B,SIM,RUF,S`. | `pyproject.toml` |
| `format-check` | `ruff format --check`, whole tree. | `pyproject.toml` |
| `shellcheck` | Shell scripts, under the pinned binary the target provisions. | `.shellcheckrc` |
| `role-skills-check` | Both role-local catalogs: manifests, licenses and the removal list. | `scripts/sync-role-skills.py` + `.inventory.json` |
| `skills-index` / `skills-check` | The deterministic base/peer/master skill catalog and its drift check. | `scripts/sparknet-skills.py` + `.catalog.json` |
| `validate` | Both roles' charters, plans and manifests. | each role's `Makefile` |
| `contract-test` | The peer still matches `contracts/`. | `tests/test_contracts.py` |
| `render-check` | `contracts/manifest.json` is not stale. | `scripts/sparknet-render.py` |
| `sbom-check` | The SBOM is not stale vs `VERSION`, deps or the skills. | `scripts/sparknet-sbom.py` |
| `test-all` | Every suite. | `tests/` + both roles' `tests/` |

The order above is the script's order: `scripts/pre-merge-gate.sh` is the
canonical definition, and `tests/test_ci.py` pins the step vocabulary. The
GitHub Actions in `.github/workflows/` run the **same script** as a mirror,
SHA-pinned. But a node has no forge and no hosted runner, so a green badge
there is never what authorises a merge — the local gate stays the authority.

Other derived-artifact gates:

```sh
make drift-check        # render-check + sbom-check + wiki-verify + role-skills-check + contract-test + goagx drift
make wiki-sync         # re-vendor .opencode/skills from the pinned upstream
make wiki-verify       # fail if the vendored suite drifted
make wiki-preflight    # prove the vendored skills resolve THIS vault
make role-skills       # rebuild both role-local sellable catalogs
make role-skills-check # verify role manifests, licenses and removal list
make skills-index      # rebuild the deterministic skill catalog for all roles
make skills-check      # verify every catalog against the installed skills
make goagx-drift-check # fail if the published goagx repo drifted from this tree
```

### 10.1 The conventions the gate does not check for you

- **One page per file.** Distilled knowledge goes to its category directory,
  provenance to `references/`. Never scatter copies.
- **Cross-role changes are atomic.** `contracts/` and both roles in **one**
  commit, then `make contract-test`.
- **A script that mutates state fails closed** and says what it refused.
- **Fabric modules load by path** (`shared/sparknet_loader.py`); the kebab-case
  `sparknet-*.py` filenames are frozen.
- **Every script answers `--help`**, and answering it changes nothing.
- **No secret in any tracked file** — not even a plausible-looking placeholder.
  Reference the secret *path* only. A leaked key is rotated, not rewritten
  silently.
- **Conventional commits**: `feat|fix|docs|style|refactor|perf|test|build|ci|chore`,
  one logical change per commit.
- **Claims must be verifiable.** Say "implemented and unit-tested", never
  "verified in production" unless it was. `tests/test_claims.py` enforces
  counts and forbids specific past-true statements.

---

## 11. Where the rest of the system lives

| You want to change… | It lives in | Read first |
|---|---|---|
| The capability vocabulary, the overlay, the ports, the identity schema | `contracts/` | `contracts/README.md` |
| The signing/verification implementation | `shared/sparknet-authz.py` | `shared/README.md` |
| Election and trust roots | `shared/sparknet-consensus.py`, `shared/sparknet-election.py` | `contracts/consensus-protocol.md` |
| The peer role (guard, anchor, bridge, share regime, vault provisioner) | `peer-node/` | `peer-node/AGENTS.md`, `peer-node/USER_MANUAL.md` |
| The master role (signer, ledger, parity, admin console) | `master-node/` | `master-node/AGENTS.md`, `master-node/USER_MANUAL.md` |
| The AGX Xavier image surface | `goagx/` | `goagx/README.md`, `goagx/USER_MANUAL.md` |
| The Go control/service plane (dispatch, routing, gateway, GPU telemetry) | the `gospark/` checkout | `gospark/README.md`, `gospark/docs/architecture.md`, `gospark/USER_MANUAL.md` |
| The node image and compose graph | `spark.docker`, `spark.compose.yml` | `contracts/spark-node-runbook.md` |
| The base wiki skill suite | `.opencode/skills/` | `.opencode/skills/README.md` |
| The role-local sellable catalogs | `<role>/.opencode/skills/` | `<role>/.opencode/skills/README.md` |

**Cross-repository links are written in prose, not as markdown links.** A
relative link from `peer-node/USER_MANUAL.md` to `../contracts/` resolves in
this repository but is broken in the published `sparknet-peer` repository,
which does not contain `contracts/`. Every manual in this set therefore only
links to files that exist in the same published repository.

---

## 12. How to make a change correctly

### 12.1 Adding a capability

1. Add the name and its definition to `contracts/capabilities.json`; bump its
   `schema_version`.
2. `make render` to regenerate `contracts/manifest.json`.
3. `make contract-test` — it names the role files that now disagree.
4. Update **both** roles in the same commit.
5. Extend `tests/test_contracts.py` if the new capability needs a conformance
   assertion.

### 12.2 Adding a port

1. Add it to `contracts/ports.json` with `implementation_state`
   (`implemented` / `provisioned` / `spec-only`) and, if measured, `runtime`.
2. `make render`.
3. Update the role that binds it, and the compose file if it is a node port.
4. `make contract-test`.

`implementation_state` and `runtime` are deliberately separate. The first is a
property of the code and travels with the contract; the second is a property of
one machine and does not.

### 12.3 Adding a service to a role

The rule is **nothing inert**. A service file that no unit or Makefile target
references is a file that looks like functionality and is not — the master role
fails its build when that happens, and the peer role's `units-check` does the
same.

1. Write the service under `services/`.
2. Give it a systemd unit under `systemd/` — units contain no vault path, they
   call generated shims.
3. Add the unit to the role's `UNITS` list in its Makefile, or explicitly
   exclude it with a reason (the master signer unit is deliberately excluded:
   enabling a key-holding process belongs to the election, not to an install).
4. Extend the role's test suite.

### 12.4 Changing a shared module

`shared/` is loaded by path, and the filenames are frozen. If you change a
canonical form, you change it for both roles at once — there is no per-role
copy to update, and that is the point. `tests/test_authz_golden.py` pins
deterministic outputs, so a canonical-form change shows up there first.

### 12.5 Changing the node image or compose

The image build context **is** the repository root, so anything the image
`COPY`s has to live at the root or in an exported subtree. `tests/test_agx_node.py`
asserts that every `COPY` source is in the export manifest, and that every
`ARG` a stage uses is declared in that stage (BuildKit predefined values like
`TARGETARCH` do not inherit from a global `ARG`).

`tests/test_goagx_repo.py` pins the export manifest in both directions: every
entry in the publish script's `SUBTREES`/`ROOT_FILES` must be in the test's
lists, and vice versa. Change one, change the other, in the same commit.

### 12.6 Writing documentation

- One page per file, in its category directory.
- Frontmatter `title` + `updated`; provenance pages add `source`/`license`/`type`.
- Cite sources. A distilled page without provenance is a guess — mark it as one.
- Do not claim live verification of something that was not verified. Check the
  spec/impl boundary before making a claim.
- Use the `[[wikilink]]` form inside a vault; use ordinary relative markdown
  links between files in the same repository.

---

## 13. Configuration reference

| Thing | Where it lives | Notes |
|---|---|---|
| Fabric version | `VERSION` | SemVer; `pyproject.toml` follows it and a test enforces the agreement. |
| Vault env | `<vault>/.env`, from `.env.example` | Every template exposes the same key set — a test asserts it. |
| Node identity | `peer-node/manifests/`, `master-node/manifests/` | Templates, never live key material. |
| Registry | `peer-node/manifests/node-authorizations.json` | Entries signed per entry; the document itself is unsigned. |
| Critical paths | `peer-node/manifests/critical-manifest.json` | The paths the guard protects, with their provenance. |
| Cluster trust root | `master-node/manifests/cluster-trust-root.json` | Formed by a unanimous election. |
| WireGuard templates | `peer-node/configs/wireguard/`, `master-node/configs/wireguard/` | Rendered at `0600`; `APPLY=1` to write, dry-run by default. |
| Node compose env | `peer-node/.state/spark.env` (or `spark-agx.env`) | Written by the setup script; gitignored. |
| goSpark config | `gospark/configs/*.example.yaml` | Copy and edit; never commit the copy. YAML with `GOSPARK_*` environment overrides. |
| goSpark pin | `goagx/GOSPARK_PIN` | One goSpark revision this distribution builds against. |
| Role-local skills | `peer-node/.opencode/skills/`, `master-node/.opencode/skills/` | Generated catalogs with `.inventory.json` provenance and a sorted `.catalog.json`; re-generated by `scripts/sync-role-skills.py`, checked by `make role-skills-check` and `make skills-check`. |
| Skill access | `scripts/sparknet-skills.py`, `shared/sparknet-skills-mcp.py` | Search/load over the catalog; OpenCode advertises only the featured set from `contracts/skill-policy.json`, the rest is read on demand. |

**Secrets** live under `.state/` — directory `0700`, files `0600`, gitignored —
and are referenced by path only. For the master role the state directory
resolves *outside* the vault (`$XDG_STATE_HOME/sparknet/master-node`, else
`~/.local/state/...`).

**`/etc` configuration is derived from the vault, never the other way round.**
`make install-config` prints the diff and cannot write it — applying a
malformed netplan on a remote node can drop your SSH session, so that stays a
human decision. `make install-units` is a dry-run report unless you pass
`APPLY=1`.

---

## 14. Troubleshooting

| Symptom | Likely cause | Where to look |
|---|---|---|
| `make contract-test` names a role file | A contract changed and the role was not updated in the same commit. | The named file; `contracts/README.md` §"Changing a contract". |
| `make render-check` fails | `contracts/manifest.json` is stale after a contract edit. | `make render`. |
| `make sbom-check` fails | `VERSION`, dependencies or the skill suite changed. | `make sbom`. |
| `make shims-check` fails | A legacy category name is a real directory, not a symlink. | `scripts/sparknet-env-init.sh` recreates the shims. |
| `make wiki-preflight` fails | The nearest `.env` is missing, so the skills would resolve a *different* vault. | Run `scripts/sparknet-env-init.sh` once in that vault. Never work around it. |
| `make keys-check` fails | Tracked key material, or a state-dir key with the wrong mode. | `scripts/sparknet-keys-check.sh`; rotate anything that was committed. |
| `make lint` fails on a new file | Ruff is configured with `E,F,I,UP` plus `B,SIM,RUF,S`; new code must satisfy the whole set on the first try. | `pyproject.toml`; documented exemptions only. |
| `make shellcheck` fails | The script needs `set -euo pipefail`, bash 3.2 compatibility, and quoted expansions. | `.shellcheckrc`; `tests/test_shell.py` covers what shellcheck cannot. |
| `make goagx-drift-check` fails | The published `goagx` repository is behind this tree. | `make goagx-publish`. It self-skips with a notice when the private remote cannot be fetched. |
| The node comes up but the guard will not bind | No overlay, or the registry is empty. | The shipped registry is **empty on purpose**; the guard refuses to bind without authority. Check `make guard-status`. |
| `chattr +i` does not hold | The filesystem does not support the immutable bit. | `make container-preflight` proves it before anything relies on it. |
| The guard verifies but refuses to apply | The peer lacks `guard-apply`, or `--apply-enabled` is off (it is off by default), or the target path is not protected. | `contracts/guard-protocol.md`; the peer `Makefile`'s `guard-status` target. |
| The overlay does not come up after a reboot | The kernel module is absent on this platform (`CONFIG_WIREGUARD=n` on the tegra hosts). | Both roles bring the overlay up through the peer's `scripts/sparknet-wg-bringup.sh` (userspace `wireguard-go`), driven by an enabled anchor unit. |
| `goSpark` refuses to start an admin surface | It refuses any non-loopback admin bind. | Bind `127.0.0.1:8899` and reach it over an SSH tunnel. |
| The 32 GB AGX peer dies with an OOM during generation | The student GGUF, the context/KV and the aux profiles exceed unified memory. | Lower `VLLM_MAX_MODEL_LEN`/`SPARKNET_LLM_CTX`; stop the aux profiles for the text battery. |

---

## 15. Spec vs implemented

This distinction is load-bearing in this codebase. `contracts/ports.json` makes
it machine-readable (`implementation_state` vs `runtime`), and the roles'
charters repeat it because describing a specified-only surface as working sends
the next reader out with a false model of the system.

Broadly:

- **Implemented and exercised** — the signed authorization scheme, the
  election and trust-root machinery, the isolated signer, the peer's guard,
  the overlay anchor (userspace `wireguard-go` on the AGX hosts), the dispatch
  bridge, the share regime, the proposal exchange, the provenance chain, the
  registry publication and delivery channel, the 8090 peer intake (telemetry
  and RFI requests), the reflex broker and its schema, evidence capture, the
  review agents, the WireGuard observer, peer telemetry push, liveness, the
  checkpoint anchor and the merkle primitive, the vault curator, the node
  image and its compose graph, the bundles, and the gates.
- **Built but not fully exercised in the field** — the cluster KillSwitch: the
  implementation and its fake-runner tests are complete (iptables, dry-run by
  default, root-gated), but the destructive run on a real Master is
  `DoD: confirm: user`. The nocturnal scheduler's state machine (`plan` /
  `arm` / `status` / `abort`) is built; it dispatches nothing until its next
  increment.
- **Contracted and scaffolding** — the agent domain ports `4097`, `4098` and
  `4100` and the admin surface (`8088`, configuration exists but nothing binds
  in the shipped tree) remain provisioned. The master-side ports `4220`–`4223`
  (git, file-share, NAT gateway, vector embed) are implemented in the contract.
  `4200` `opencode-serve` remains spec-only.
- **Deliberately parked** — the destructive legs of the deployment runbook
  (rollback; replace-Master re-formation) are documented and deliberately left
  unexecuted by operator decision. The reflex layer's enforce stage is
  deferred; shadow and assist are what run.

The honest test: if you cannot point at a command that exercises it, it is
specified. `contracts/ports.json` is the machine-readable version of this
paragraph, and `tests/test_claims.py` keeps the live surfaces from claiming
more.

---

## 16. Glossary

| Term | Meaning |
|---|---|
| **Fabric** | The two-role system: a Master, its peers, and the contract they share. |
| **Role** | Peer or Master. The Master is a peer that won an election. |
| **Overlay** | The WireGuard network the roles talk over, `10.100.0.0/24`. |
| **Contract** | A rule both roles must agree on, held in `contracts/`. |
| **Capability** | One entry of the closed vocabulary in `contracts/capabilities.json`. |
| **Registry** | The Master-signed statement of which node may hold which capability. |
| **Publication** | The signed, sequenced artifact that carries a registry to a peer (`contracts/registry-publication.json`). |
| **Envelope** | A signed bundle of identity, capabilities and validity timestamps. |
| **Guard** | The peer's daemon that verifies Master-signed approvals and applies them to protected paths. |
| **Anchor** | The overlay bring-up unit; it owns the `wg0` interface and pins its config. |
| **Trust root** | The document recording the cluster's unanimous decision on who holds the signing key. |
| **Signer** | The one process that holds the operational key. |
| **Ledger** | The hash-chained record of approvals and decisions. |
| **Bundle** | A self-contained tarball carrying a role plus the contract and shared code it needs. |
| **Precontext** | The vault content baked into a template and prepended to a chat request. |
| **Spec-only** | Designed and contracted, no code, by deliberate role boundary. |
