---
title: sparknet WebUI surface
role: both
updated: 2026-11-05
---

# WebUI surface

The fabric has two Open WebUI surfaces, not one:

| Surface | Host | Menus | Scope |
|---|---|---|---|
| Peer — **Sparknet Node** | `agx64`, 64 GB | Mesh, Vectors, Learning (read-only Master snapshot), Memory, Projects | The owner, the owner's node, the owner's Qdrant, per-vault memory and the Master's sanitized Learning status |
| Master — **Sparknet Master** | `agx32`, 32 GB | Mesh, Vectors, Learning, Memory, Projects | All registered nodes, users, departments, vectors, distillation runs and memory metadata |

Open WebUI remains the chat, account and model surface. The Sparknet pages are
a separate console served by `scripts/sparknet-console.py` and reached through
the same origin as Open WebUI. The console is read-only in this step: it shows
state and evidence. It never signs, grants, revokes, trains or writes a registry.

## User policy

- **Peer** is the only user surface: every human account lives there; signup is
  enabled with `DEFAULT_USER_ROLE=pending` and a new account reaches nothing
  until approved.
- **Master** is admin-only: the human administrator is the only WebUI account.
  Users are supervised through the peer's own signed `admin-supervise` channel,
  never by a second account or a shared password.
- The old cluster2 Master WebUI (a second user database on `8181`) was retired
  on 2026-11-05 after its one user chat was migrated to the peer.

## OpenCode engine

Open WebUI's agent execution path is the loopback **Sparknet OpenCode engine**
(`127.0.0.1:4204`), an OpenAI-compatible adapter in front of OpenCode 2.2.5.
The live sandbox is 2.2.5 on agx64/agx32 (rebuilt 2026-11-06).
The engine maps the WebUI-forwarded user id and chat id to a private per-user
sandbox:

- the sandbox mounts only `/srv/sparknet/knowledge/peer-<user_id>`;
- it joins an internal Docker network whose only peer is the host model proxy;
- it runs with a read-only root filesystem, dropped capabilities and no key,
  state, ledger, registry or other user's vault mount;
- `sparknet-chat` and `sparknet-plan` are read-only; `sparknet-build` may edit
  files and run shell commands **inside that sandbox only**.

The engine holds no signing capability. It is not a knowledge channel: it reads
the signed-in user's own vault and returns an answer to that user. The old
dispatch-bridge `/v1/chat/completions` ack surface is not a model; the bridge
remains the grant-checked vault/authority tool surface.

## Workspace baseline

- **Prompts:** 16 bilingual (EN/DE) public-read slash commands for help, plan,
  build, capture, RFI, citations, memory and health.
- **Tools:** `sparknet_vault`, `sparknet_memory`, `sparknet_rfi`,
  `sparknet_status`; all user-scoped through the loopback memory gateway.
- **Functions:** the `sparknet_memory` filter and the `sparknet_capture` action,
  both active and global.
- **Models:** each approved user gets a private `peer-<user_id>` model based on
  `sparknet-chat`, with their personal KB and the structure-only KB attached.
- **RAG:** structure-only corpus, Qdrant-backed. The existing CPU MiniLM index
  is kept because the node's Qwen3/Nomic Ollama embeddings measured ~20 s per
  request on `agx64`; upgrade when a dedicated embed engine is resident.

## Identity and authority

- A WebUI login is **not** fabric authority. The console displays what the
  signed registry, telemetry, ledger and peer APIs already recorded.
- The peer console is owner-only. The Master console is read-only for
  authenticated `user` and `admin`; Learning is sanitized and read-only.
- The console validates the caller's Open WebUI session token against this
  role: both roles accept `user`/`admin` for the read-only console. The SPA
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

Master: local read-only view. Peer: the same view, fetched on demand from the
Master's sanitized snapshot over signed `4221` (`p2p-sync`); the peer never
stores a mirror and never sees weights, datasets, traces, prompts or raw distill
state.

- teacher/student profile and the live benchmark winner;
- distillation runs: dataset, metrics, artifact digest, signer state, model card;
- automation posture: off / plan-only / queue-for-approval / signed auto-run;
- teacher/student runtime availability and the Qdrant map collections.

The Learning screen is read-only on both roles. A control action requires the
distillation service and the isolated signer; it is not a button that writes a
file or starts training from the browser. The peer link is a signed `4221` file
fetch, not a second authority or knowledge channel.

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
