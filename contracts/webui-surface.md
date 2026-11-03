---
title: sparknet WebUI surface
role: both
updated: 2026-11-01
---

# WebUI surface

The fabric has two Open WebUI surfaces, not one:

| Surface | Host | Menus | Scope |
|---|---|---|---|
| Peer — **Sparknet Node** | `agx64`, 64 GB | Mesh, Vectors, Memory, Projects | The owner, the owner's node, the owner's Qdrant and per-vault memory |
| Master — **Sparknet Master** | `agx32`, 32 GB | Mesh, Vectors, Learning, Memory, Projects | All registered nodes, users, departments, vectors, distillation runs and memory metadata |

Open WebUI remains the chat, account and model surface. The Sparknet pages are
a separate console served by `scripts/sparknet-console.py` and reached through
the same origin as Open WebUI. The console is read-only in this step: it shows
state and evidence. It never signs, grants, revokes, trains or writes a registry.

## Identity and authority

- A WebUI login is **not** fabric authority. The console displays what the
  signed registry, telemetry, ledger and peer APIs already recorded.
- The peer console is owner-only. The Master console is admin-only.
- The console validates the caller's Open WebUI session token against this
  role: a peer accepts `user`/`admin`, the Master accepts `admin` only. The SPA
  reads the token Open WebUI already stores for the same origin.
- A deploy-time console token at `0600` under
  `$SPARKNET_STATE_DIR/webui/console.token` is the service/automation fallback;
  it is never returned to the browser.
- The Qdrant API key is read server-side and never returned to the browser.
- The console is loopback-only. The published path is the Open WebUI proxy; no
  second overlay-facing port is added. The SPA calls `api/...` relative to its
  same-origin path, and the proxy strips the console prefix.

## Menus

### Mesh

Peer:

- identity, overlay address, trust root, capabilities, department;
- my registry entry and revocation state;
- my node-to-node connections, shares, RFIs and inbox acceptance;
- recent auth events, telemetry/checkpoint files and ledger head.

Master:

- every registry entry, trust level, department and liveness;
- user/KB/chat inventory (from the Master's mirrored inventory);
- share/proposal/ratification queue and RFI queue;
- ledger head, evidence repository and recent auth/admin events.

No menu displays another peer's personal vault page. The Master's fleet view is
metadata and evidence, not knowledge.

### Vectors

Peer: the owner's Qdrant collections, read-only, excluding `sparknet-inventory`,
`sparknet-traces`, `sparknet-kv` and `uplift-*`.

Master: `sparknet-fabric`, `sparknet-shared` and `sparknet-distill-map`, plus
collection metadata. Training/uplift collections are excluded. Per-user vector
inspection requires the separate `vector-inspect` capability and is not part of
this read-only screen.

The pilot 3D view uses a deterministic random projection of sampled Qdrant
vectors. It is labelled **pilot projection**, not UMAP. The renderer is the
Open WebUI panel's canvas, not a second knowledge index. A later step replaces
the projection with the UMAP pipeline and the TensorFlow Projector renderer.

### Memory

Peer: the owner's typed memory over the vault currently selected: episodic,
semantic, procedural, short-term and shared; project and delegate views; capture,
retention, forget/export and "who read my memory" controls.

Master: fleet memory metadata (counts, capture posture, retention, share refs,
delegate runs) and a policy console. Content is read on demand through a signed
`memory-supervise` request, is transient, and is written to the peer's audit log;
the console never stores a mirror.

### Learning

Master only.

- teacher/student profile and the live benchmark winner;
- distillation runs: dataset, metrics, artifact digest, signer state, model card;
- automation posture: off / plan-only / queue-for-approval / signed auto-run;
- teacher/student runtime availability and the Qdrant map collections.

The Learning screen is read-only in this step. A control action requires the
distillation service and the isolated signer; it is not a button that writes a
file or starts training from the browser.

## Boundaries

1. **No secret in the browser.** The console token, Qdrant key, memory gateway
   token and signer socket never leave the server.
2. **No authority action.** The console cannot sign, approve a share, approve a
   user, publish a registry, start training or change a setting.
3. **No second knowledge base.** The console reads Qdrant; it does not create a
   new collection or ingest pages.
4. **No model control.** A model cannot call the console or change its scope.
5. **No live claim from a development host.** The console is tested against
   local fixtures; the live page is a target-node observation.
