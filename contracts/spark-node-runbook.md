# Spark node runbook — the DGX Spark image, and everything verifiable without a GPU

The node image (`spark.docker`) and its orchestration (`spark.compose.yml`) are
part of the fabric, not of either role: one artifact, many services, each a
`spark-entrypoint.sh` subcommand. This runbook is the operator's companion to
those three files plus `sparknet-node-setup.sh`. It is deliberately split into
**what can be proven on a machine with no NVIDIA hardware** and **what only the
Spark can confirm** — the same honesty the peer and master runbooks apply to the
real hosts.

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
  The image consumes `bin/` through the BuildKit named context `gospark`; it is
  **not** vendored into the fabric.
- ~35 GB free disk for the image plus the vLLM base layers.
- The host has **no working network/DNS inside the BuildKit sandbox**: build with
  `--network=host`. The setup script already does; the manual path below shows it.

## 3. Build the image

```sh
# in the goSpark checkout:
make build build-gpu

# in the fabric root (the image build context IS the root):
docker buildx build --network=host \
  -f spark.docker \
  --build-context gospark=<path-to-goSpark> \
  -t sparknet-spark-node:dev --load .
```

`sparknet-node-setup.sh build` does the same, plus the bundle staging and the
env-file, and is the supported path. The image is ~20 GB: 17 layers, the vLLM
base, the baked fabric context used for precontext, and the pinned tooling.

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

## 6. Simulated GPU telemetry (control / placement / metrics, no GPU)

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

## 7. Containerised election rehearsal

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

## 8. The residual `confirm: user` list (physics)

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

## 9. Troubleshooting

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
