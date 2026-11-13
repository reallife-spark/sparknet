# Spark node runbook — the DGX Spark image, and everything verifiable without a GPU

The node image (`spark.docker`) and its orchestration (`spark.compose.yml`) are
part of the fabric, not of either role: one artifact, many services, each a
`spark-entrypoint.sh` subcommand. This runbook is the operator's companion to
those three files plus `sparknet-node-setup.sh`. It is deliberately split into
**what can be proven on a machine with no NVIDIA hardware** and **what only the
Spark can confirm** — the same honesty the peer and master runbooks apply to
the real hosts.

One flag widens it: `--platform agx` selects the Jetson AGX Xavier twin of the
same surface (`goagx/` — its own dockerfile, compose file and audio shim, same
services/ports/profiles). Everything below is written for the Spark and applies
to the AGX variant wherever a step does not name the image; the differences are
gathered in the AGX subsection of §5 and in `goagx/README.md`.

Behavioural contracts still win over this page: the overlay, ports, capabilities
and identity live in `overlay.json`, `ports.json`, `capabilities.json` and
`identity-schema.json`. Where this runbook and those disagree, the contract is
right.

## 1. What is provable here, and what is not

| Proven on any host (no GPU) | `DoD: confirm: user` — Spark only |
|---|---|
| The image builds, bakes the bundle/context/venv/binaries, and every service starts | real `vllm serve` on Blackwell (sm_121a) returns tokens |
| The **agent ↔ vLLM ↔ compute** path works end to end, through the CPU stub engine | multimodal engines (embed / rerank / audio) load real models |
| The **election arc** runs inside the image: 3 identities, trust root, signer, registry sign + verify, three refusals | the signer systemd unit survives a reboot; exactly one process holds the operational key |
| GPU **telemetry plumbing** (sidecar → bus → control → placement → metrics) with a synthetic fixture | NVML/DCGM report real numbers (`available=true` from a driver, not a file) |
| Degraded telemetry is honest: no driver ⇒ `available=false` **with a reason** | WireGuard overlay on real NICs; deployed containment |

The containerised election rehearsal and the CPU smoke are *packaging* proofs.
They say the artifact is sound; they never say the deployment is.

## 2. Preflight

- Docker with the `compose` v2+ plugin (`docker compose version`).
- goSpark checkout with binaries built: `make build build-gpu` in that checkout.
  The local default is `gospark/` in the fabric root (`GOSPARK_DIR` overrides).
  The image consumes `bin/` through the BuildKit named context `gospark`; it is
  **not** vendored into the fabric.
- ~35 GB free disk for the image plus the vLLM base layers.
- The host has **no working network/DNS inside the BuildKit sandbox**: build with
  `--network=host`. The setup script already does; the manual path below shows it.

## 3. Build the image

```sh
# in the goSpark checkout (gospark/ by default):
make build build-gpu

# in the fabric root (the image build context IS the root):
docker buildx build --network=host \
  -f spark.docker \
  --build-context gospark=gospark \
  -t sparknet-spark-node:dev --load .
```

`sparknet-node-setup.sh build` does the same, plus the bundle staging and the
env-file, and is the supported path. The image is ~20 GB: 17 layers, the vLLM
base, the baked fabric context used for precontext, and the pinned tooling.

`--platform agx build` builds `goagx/sparknet.agx.docker` as
`sparknet-agx-node:dev` instead — same flags, same named context, see
`goagx/README.md` for the resource-first verdict and the build budget.

## 4. CPU-only smoke — no GPU, no model

`--engine stub` layers `spark.compose.cpu.yml` on top of the base file, which
(a) drops the NVIDIA device reservations — without this the `vllm` and `gpu`
services fail to start on a driverless host — and (b) runs the CPU-only
OpenAI-compatible stub as the `vllm` service, and feeds the `gpu` sidecar a
synthetic telemetry fixture.

```sh
./sparknet-node-setup.sh --engine stub --profiles control up
```

What is running, and what to check:

```sh
# the bus:
curl -fsS http://127.0.0.1:8222/healthz

# the stub engine answers like an OpenAI server (deterministic echo, no model):
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8000/v1/models
curl -fsS http://127.0.0.1:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"stub","messages":[{"role":"user","content":"ping"}]}'

# the node's own gateway in front of it (this is the agent ↔ vLLM path):
curl -fsS http://127.0.0.1:8080/v1/models
curl -fsS http://127.0.0.1:8080/healthz

# the compute plane:
curl -fsS http://127.0.0.1:9090/v1/health

# with --profiles control, the control admin surface:
curl -fsS http://127.0.0.1:8899/admin/gpu    # telemetry, from the fixture
```

The fixture the `gpu` sidecar reads is written to
`<state-dir>/gpu-sim.json` by the setup script; regenerate it with
`scripts/make-gpu-fixture.py` (add `-n 2` for two synthetic GPUs, `--unavailable`
to exercise the degraded path). The sidecar reports `available=true` and a
`GB10-SIM` device — **telemetry only**: it grants nothing and places nothing by
itself.

Never use `--engine stub` (or the CPU overlay) on a host with, or due to get, a
real GPU. The fixture is theatre; a real driver reading is the only honest
answer.

## 5. GPU bring-up on the Spark

The default engine is the real one; no overlay, no stub.

```sh
./sparknet-node-setup.sh up                       # text node: vllm compute agent gpu
./sparknet-node-setup.sh --role master up         # + control plane (this node signs)
```

Profiles add load on demand — a first bring-up should not download four models
before it can answer:

```sh
./sparknet-node-setup.sh --profiles embed up      # embeddings, for the RAG corpus
./sparknet-node-setup.sh --profiles rerank up     # cross-encoder reranker
./sparknet-node-setup.sh --profiles audio up      # speech/audio model
./sparknet-node-setup.sh --profiles webui up      # Open WebUI on :3000
./sparknet-node-setup.sh --profiles embed,rerank,audio,webui up   # all at once
```

Three profiles are not model servers — they are the node's knowledge services,
the goSpark binaries run in-stack:

```sh
./sparknet-node-setup.sh --profiles ingest up     # one-shot: refresh the RAG index
./sparknet-node-setup.sh --profiles backup up     # signed vault snapshots, on a timer
./sparknet-node-setup.sh --profiles opencode up   # the node's opencode server on :4200
```

- **ingest** crawls the node vault, chunks it and embeds through the compute
  plane (`sparknet-ingest`), writing the index to `.state/rag/index.json`. It is
  a one-shot: enabling the profile refreshes the index once at `up`, then the
  service exits. Re-run on demand without touching the rest of the stack:

  ```sh
  docker compose -f spark.compose.yml --profile ingest run --rm ingest
  ```

  Point it at the dedicated embeddings server by also enabling `embed` (it
  honours `SPARKNET_EMBED_ENDPOINT`); with no embedder it indexes chunks only.

- **backup** runs `sparknet-backup run`: it hashes the vault, copies it under the
  backup target and writes a **node-signed** manifest every
  `GOSPARK_BACKUP_INTERVAL` (default `6h`), so `sparknet-backup verify` can tell
  a faithful snapshot from a tampered one. The target is a host bind mount
  (`.state/backups`) and is deliberately **outside** the source — a target inside
  the source would be walked and included in its own snapshot — and `.state` is
  skipped so the signing key is never inside the tree it signs.

- **opencode** serves the node's vault as an opencode project on `127.0.0.1:4200`
  (loopback by default: it carries the whole node's session authority, so it is
  never a fabric edge). Sessions and caches live under `.state/opencode/` so they
  survive a container recreation. An **MCP server is a stdio tool here, not a
  listener** — it is not a port and is not wired as a service.

The `--profiles` names are checked against `spark.compose.yml` by
`tests/test_contracts.py::test_setup_script_advertises_only_profiles_compose_defines`,
so the setup script can never advertise a profile that does nothing.

The text engine serves the **fabric precontext**: `spark-precontext.py` merges
the MASTERSPIKE system prompt with the `contracts/`-derived digest and prepends
it as a wrapper chat template at container start. Verify it once, out of band:

```sh
docker run --rm --entrypoint spark-entrypoint sparknet-spark-node:dev \
  precontext digest | head
```

**`confirm: user`**: that `vllm serve` on this node loads the model and returns
tokens, and that the multimodal engines load their real models. No suite on a
non-GPU host can see those.

### Port map

The node's ports are contracted in `contracts/ports.json` under `node_ports` — a
namespace beside the fabric's `ports`, because the node publishes to the docker
host namespace while the fabric listens in the overlay. What the bring-up
exposes:

| Port | Service | Bind default | Reaches |
|---|---|---|---|
| 8000 | `vllm` | `SPARKNET_BIND_API` (0.0.0.0) | the OpenAI-compatible text engine (vLLM on Spark, llama-server on AGX, or the stub) |
| 8080 | `agent` gateway | `SPARKNET_BIND_API` | the node's fabric-facing edge |
| 8081 | `control` gateway | `SPARKNET_BIND_API` | `--role master` only |
| 8899 | `control` admin | `SPARKNET_BIND_LOCAL` (127.0.0.1) | `--role master` admin |
| 3000 | Open WebUI | `SPARKNET_BIND_API` | `--profiles webui` |
| 4222 | NATS bus | `SPARKNET_BIND_LOCAL` | JetStream, persisted under `.state/nats` |
| 8222 | NATS monitor | `SPARKNET_BIND_LOCAL` | monitoring endpoint |
| 9090 | `compute` | `SPARKNET_BIND_LOCAL` | `/v1/execute`, forwarding to vLLM |

Not published to the host (docker-network only, dialed by the stack itself):
`9100` kvrouter, `9180` control metrics, and `8001`/`8002`/`8003` for the
`embed`/`rerank`/`audio` profiles.

Two of these numbers — **9090**, **4222** — also appear in the fabric's
`ports` (guard, nat-gateway). A shared number is not a
shared socket: the loopback defaults above are exactly what keeps a node and a
role's listeners apart on one host. (8080 used to be a third — the admin surface
— until it was relocated to 8088, fabric Step 55, so the agent gateway's
wildcard publish no longer fights it.) The fix on a shared host is to move the
node's bind (`SPARKNET_BIND_LOCAL`) rather than re-bind the fabric side.

### The AGX Xavier variant (`--platform agx`)

`--platform agx` selects `goagx/sparknet.agx.compose.yml` and
`spark-agx.env` together (the default stays `spark`). The service graph,
container names, profiles, ports and core env keys are the same by test
(`tests/test_agx_node.py`), so §5 and §6 read unchanged; manual
`docker compose -f …` commands substitute the AGX file. Two images share the
surface: `sparknet-agx-node:dev` (goSpark, compute, aux engines, bundle,
stub) and `sparknet-llm:agx` (the text engine). What genuinely differs, all
documented in `goagx/README.md`:

- **role-specific GGUF on the root model dir** — teacher Qwen3.6-35B Q4_K_M
  on `agx64` (64 GB), student Qwen3.6-0.6B Q8_0 on `agx32` (32 GB);
  `VLLM_MAX_MODEL_LEN=8192` default, each overridable; the compose mounts
  `/opt/sparknet/models` read-only and never mounts a vault or the state dir;
- **the text engine is `sparknet-llm:agx`** — `llama-server` from dusty-nv's
  `jetson-containers` `llama_cpp` package (L4T r35 / `sm_72`) plus the
  precontext proxy; the node image no longer builds vLLM;
- **the precontext is a proxy-injected system message** (MASTERSPIKE text +
  fabric digest); `SPARKNET_PRECONTEXT_MAX_BYTES` caps it;
- **audio runs through the shim**: whisper.cpp has no OpenAI transcription
  route, so `sparknet-audio-shim.py` exposes `/v1/audio/transcriptions` on
  the audio profile's port and forwards to `127.0.0.1:8004`;
- **embed/rerank are llama.cpp**, serving `/v1/embeddings` and
  `/v1/rerank` (+ `/v1/reranking`).

The CPU smoke works identically: `--engine stub` layers
`spark.compose.cpu.yml` (command/env/device reservations, plus the node image
and `vllm-stub`) onto whichever base file the platform selected. The LLM image
has no stub, so the overlay switches `vllm` to the node image.

## 6. Join a running fabric (adopt the elected Master)

By default the node runs **open and self-signed**: `spark-entrypoint` mints its
own keys and the goSpark agent authorises anything the local control key signs.
That is correct for a standalone inference appliance and wrong the moment the
node is meant to be one more member of the elected fabric. Joining replaces the
self-minted trust with the two artefacts the election produced: the elected
cluster trust root's **operational public key** and a **Master-signed
registry entry** for this node's identity.

The two implementations of that signature are one, proven on both legs by
`tests/test_registry_crossverify.py` (Python `shared/sparknet-authz.py` signs →
goSpark `internal/authz` verifies, and the reverse, with refusals each way). Only
*public* keys cross the boundary: the Master signs with the fabric's 32-byte
seed, the node verifies against its base64 public half, and the node's own key
stays goSpark-format.

**Preconditions:** the election has run (`deployment-runbook.md`, Step 13) and
the Master operator can sign; this node is running as `--role peer` (a `--role
master` node runs the control plane, which is itself the registry authority —
the setup script refuses `--registry` with `--role master`).

```sh
# 1. On the node: mint the node key (or let the first boot mint it) and project
#    it into the fabric's identity record — the five identity-schema fields, with
#    the node's Ed25519 public key in the wireguard_public_key_b64 slot:
python3 - <<'PY' > node.identity.json
import json
k = json.load(open(".state/node.key"))     # or peer-node/.state/node.key on the host
print(json.dumps({
    "node_id": k["node_id"], "role": k["role"],
    "wireguard_public_key_b64": k["public_key_b64"],
    "overlay_ipv4": k["overlay_ipv4"],
    "requested_capabilities": sorted(k["requested_capabilities"]),
}, indent=2))
PY

# 2. On the Master: sign that identity into the registry with the elected
#    operational key — the same document peer manifests/node-authorizations.json
#    carries, entries signed per entry over signed_envelope_fields:
python3 shared/sparknet-authz.py sign node.identity.json \
  --master-key "$STATE_DIR/keys/master-operational.key" \
  --capabilities cluster-serve,telemetry --out entry.json
# (entry.json then joins the fabric's node-authorizations.json authorizations[]
#  — exactly the document the live pair already distributes.)

# 3. Back on the node: stage both artefacts and (re)up. The key may be given as
#    the base64 string or as a file holding it; with --registry and no key, the
#    key is read from the registry's own master_public_key_b64 (logged — pinning
#    it out of band is the stronger form):
./sparknet-node-setup.sh \
  --master-pub "$MASTER_PUB" \
  --registry /path/to/node-authorizations.json up

# 4. Verify the adoption (inside the running image):
docker exec sparknet-agent sparknetctl registry verify \
  -registry /srv/sparknet/peer-node/.state/node-authorizations.json \
  -master-pub "$MASTER_PUB"
```

Fail-closed behaviour on the join path, all tested:

- a registry staged **without** a reachable `SPARKNET_MASTER_PUB` makes
  `spark-entrypoint` refuse to start the agent rather than fall back to a
  self-minted key that the Master-signed entries do not cover;
- a tampered entry (widened capabilities, flipped `revoked`) fails verification
  in *both* implementations, not just the one that signed it;
- leaving the flags off returns the node to open mode exactly as before — the
  join is opt-in, never a default.

## 7. Simulated GPU telemetry (control / placement / metrics, no GPU)

The opt-in synthetic backend is for exercising the *plumbing* that the real GPU
feeds — the sidecar, the bus, `/admin/gpu`, placement gates and graphs:

```sh
scripts/make-gpu-fixture.py -o /tmp/gpu.json
sparknet-gpu -sim-fixture /tmp/gpu.json -node-id spark-01 \
  -bus-url nats://127.0.0.1:4222 -overlay 10.100.0.2 -watch -interval 30s
```

or the same via the environment, which is how the containerised CPU smoke feeds
it: `SPARKNET_GPU_FIXTURE=<path>`. With nothing set, the sidecar degrades to
`available=false` with a reason string — the default a driverless host must
always keep, and a test in `tests/test_gpu_telemetry_hardware_free.py` holds it
there.

## 8. Containerised election rehearsal

The election arc was proven live on real hosts (Step 13, 2026-10-07). What was
missing was proof that the **packaged artifact** — image toolchain, baked
Python, the ceremony scripts as shipped — can run the same arc. That is what this
does; it is opt-in and minutes long:

```sh
./scripts/sparknet-election-rehearsal-container.sh
# or through the test, which also asserts zero failed checks:
make container-test
```

It drives the *existing* `scripts/sparknet-rehearsal.sh` inside
`sparknet-spark-node:dev` (the script's interpreter, ceremony paths and bundle
are handed to it by the wrapper), so the logic is not forked. It builds a master
bundle, stands up three identities, holds the election, forms a 3-cosignature
root, starts the isolated signer, signs a registry entry the elected key
publishes, and refuses the three escalation attempts. The dated transcript is
left on the host; node trees are removed on success.

It runs in a container network namespace, so it proves the runtime and the ports,
**not** the overlay: WireGuard on a real NIC, reboot survival and containment
remain `confirm: user` (see `deployment-runbook.md` Phase 6–9).

## 9. The residual `confirm: user` list (physics)

Answer these — on the Spark, by someone who can see it — before calling the node
deployed:

1. **Real inference.** `vllm serve` loads the Spark model and returns tokens on
   GB10 (sm_121a); the multimodal engines load their real models.
2. **Real telemetry.** The sidecar reports NVML/DCGM numbers with
   `available=true` from the driver and libdcgm — not from `gpu-sim.json`.
3. **Overlay.** WireGuard is up on the real NICs and both directions reach the
   election port (`ports.json` 4210, `overlay_only`).
4. **Signer containment.** The selected node's `sparknet-master-signer.service`
   survives a reboot and exactly one process holds the operational key.
5. **Deployed refusals.** The loser-key / wrong-node / tampered-root refusals
   hold against the deployed unit, not just the rehearsal.
6. **Phase 9 legs.** Rollback and replace-Master re-formation stay deliberately
   unexecuted; a revoke has still to be shown inert at the guard on a real host.

On an AGX Xavier node (`--platform agx`) this whole list applies with the
GB10 specifics swapped for Xavier's — `sm_72` inside a 64 GB (teacher) or
32 GB (student) budget, the `llama.cpp` engine loading the GGUF and answering
the OpenAI endpoints, the precontext present in the request, the sidecar
reading the Jetson driver — plus the audio-shim behaviours; `goagx/README.md`
keeps that extra list.

## 10. Troubleshooting

- **Build fails resolving packages / no DNS.** Build with `--network=host` (the
  sandbox has no network). The same applies to `docker run` on this host.
- **`libdcgm.so.4 not found`.** Expected: DCGM install into the image is
  best-effort (`INSTALL_DCGM=0` by default) and its absence is a *reason*, not a
  crash. Set `INSTALL_DCGM=1` only if the base image's apt can serve it.
- **`the 'cryptography' package is required`.** Run the ceremony with an
  interpreter that has it. The image's venv ships `cryptography>=42`; on a host,
  use the repo `.venv` (`make devtools`) or install the pin from
  `requirements.txt`.
- **`vllm`/`gpu` services fail to start with "could not select device driver".**
  That is the GPU reservation doing its job on a host without the NVIDIA
  container runtime — use `--engine stub`, or install the toolkit on the Spark.
- **`stub-vllm` not found in the image.** Rebuild after `make build` in goSpark;
  the binary is built by `make build` and copied from `bin/` into the image.
