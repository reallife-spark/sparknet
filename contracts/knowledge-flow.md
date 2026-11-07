# Knowledge flow — how information reaches a peer, and what it may never carry

This page is the map. It does not replace the contracts it names, and it adds no
authority, port or payload. It exists because the fabric has several channels
that are easy to confuse: an authority publication, a signed answer, a share, a
telemetry report and an administrative request all cross the same overlay, and
only one of them is knowledge a user's AI may answer from.

The rule is simple and load-bearing:

> **Authority and knowledge travel on separate channels. No channel both grants
> a capability and carries content an AI may treat as knowledge.**

A peer is useful without a Master because its vault, its model and its user
knowledge bases are local. The Master is useful because it holds the key and the
authoritative fabric corpus. Neither property is allowed to leak into the other.

## The channels

| Channel | Direction | Carrier | Authentication | May carry | Must never carry | State |
|---|---|---|---|---|---|---|
| Registry publication | Master → peer | `POST /api/v1/registry` on the guard, `9090` | Master signature under the cluster trust root | The registry, capabilities, revocation, department | Vault pages, prompts, answers | Implemented; deployed |
| Guard approval | Master → peer | `POST /api/v1/critical-file/patch` on the guard, `9090` | Master signature, bound to one peer and one protected target | One protected-file change | Knowledge, a second target, a capability | Implemented; deployed |
| RFI answer | Master → peer | `POST /api/v1/rfi` on the guard, `9090` | Master signature over a digest-bound, scoped projection | Scoped knowledge into `01_Inbox/` | Authority, unscoped categories, personal pages | Implemented; live pair `DoD: confirm: user` |
| RFI request | peer → Master | `POST /api/v1/rfi-request` on peer intake, `8090` | Authenticated overlay; registry fingerprint match | A question and a scope allow-list | Authority, a capability request, a write | Route implemented; peer client built in the user-node step |
| Telemetry | peer → Master | `POST /api/v1/telemetry` on peer intake, `8090` | Authenticated overlay; registry fingerprint match | Status, metrics, liveness, checkpoints, inbox alerts | Authority, knowledge answers, a write path | Implemented; units staged |
| Vector/inventory uplift | peer → Master | `8091` uplift intake | Overlay + signed peer request + peer-held `model-uplift` | Consented Qdrant snapshots, user/model inventory, teacher traces, raw-KV manifests | Authority, a peer write path, another user's data without consent | Implemented; live pair `DoD: confirm: user` |
| Admin request | Master → peer | `POST /admin/<action>` on the bridge, `4096` | Master signature + `admin-supervise` in the peer's registry | User, role, KB and chat administration | Vault content, knowledge answers, a signature | Implemented; current pair `DoD: confirm: user` |
| Share / proposal | peer ↔ peer | `4201` share intake, `4202` session transfer | Both nodes verify the share grant; Master ratifies at `n ≥ 3` | A bounded read or copy, or a proposal bundle | Authority, a protected-file write, a registry edit | Implemented; live pair 2026-10-31 |
| Shared file share | Master → peer | `4221` file-share | Overlay + signed request + `p2p-sync` | Shared fabric artifacts | Personal pages, keys, live state | Implemented; live pair 2026-10-31 |
| Learning status | Master → peer | `4221` file-share, `learning/status.json` | Overlay + signed request + `p2p-sync` | Sanitized distillation run status: ids, states, metrics, digests, model names | Weights, datasets, traces, prompts, personal pages, authority | Implemented; peer link live 2026-11-04 |
| Shared vector DB | Master → peer | `4223` vector-embed | Overlay + signed request + `cluster-dispatch`/`cluster-serve` | Top-K from the Qdrant `sparknet-fabric` or explicitly shared `sparknet-shared` collections | Personal pages, uplift/training collections, a caller-supplied vector, authority | Implemented; live pair 2026-10-31; Qdrant re-verification `DoD: confirm: user` |
| Local vault / KB | node-local | Filesystem, Open WebUI KB, Qdrant | User key for signed notes; grant for agent writes | The user's own knowledge | Authority, another user's private KB | Implemented; Qdrant migration is the vector-store step |
| Local agent engine | node-local | OpenCode engine (loopback `4204`) → one sandbox per user | WebUI session token + forwarded user id; the engine derives `peer-<user_id>` and mounts only that vault | The user's own vault pages while answering, and tool actions inside that sandbox | Another user's vault, the role vault, keys/ledger/registry, authority, a shared corpus | Implemented; live on agx64/agx32 2026-11-05 |
| Local memory index | node-local | `sparknet-memory` (Go, loopback `4110`) behind the Python gateway (`4093`) | Signed session grant, Open WebUI session, or the `0600` local token; the gateway narrows to one vault | Typed records, summaries, procedural traces and delegate runs derived from sources the node may already read | Authority, a second corpus, another user's vault, or a record the grant's scope excludes | Implemented; live node start `DoD: confirm: user` |
| Control event bus | peer ↔ Master / peer ↔ peer | NATS/JetStream on the overlay (`4225`) | Overlay + pinned node identity; the event signature is provenance | Task, result, health and collab envelopes, plus audit | Authority, a capability grant, a knowledge answer, a vault write | Implemented; live event 2026-11-07 |
| Collaboration room | peer ↔ peer, or peer-local | `POST`/`GET /v1/collab/*` on the memory gateway (`4093`); NATS `sparknet.collab.*` for transport | Participant identity + room ABAC; the room classification is a ceiling | Room and message data for listed participants | A vault page, authority, an automatic shared-corpus write | Implemented; loopback and live write verified 2026-11-07 |
| Execution request | local user ↔ peer | User-only Unix socket; signed JSON-RPC | Request signature + operator OS uid/euid + `--allow-exec` | One argv-only action and its signed result | Knowledge, authority, a shell string, a second user's vault | Daemon implemented; live validate-only 2026-11-07 |
| Package distribution | Master → peer | Signed package index and manifests | Signed package + explicit operator install | Code and skill artifacts, digests and dependencies | Authority, auto-install, a self-executing manifest | CLI implemented; live distribution pending |
| Derived graph / hybrid | node-local | `GET /v1/vault/graph` and `/v1/vault/hybrid` on `4093` | Same session grant or local token; the gateway narrows to one vault | Derived links and two labelled retrieval result sets | Authority, a second vault, an unaccepted page, a merged answer | Implemented; live 2026-11-07 |
| Memory bundle | peer ↔ peer | The existing `session-handoff` / `kb-share` payload on `4201`/`4202`, staged under `01_Inbox/share-<id>/` | Share grant + acceptance; no new share type | Episodic summaries, shared blackboard entries, and project notes the user selected | Short-term/cache, secrets, another user's records, authority | Payload profile implemented; live share `DoD: confirm: user` |
| Master memory inspection | Master → peer | Existing signed `/admin/*` request on the bridge | Master signature + the peer-held `memory-supervise` capability | On-demand, scoped memory content and policy execution | A permanent mirror, a Master answer corpus, authority, or an unscoped bulk read | Implemented code; live pair `DoD: confirm: user` |
| Context pack | build-time, node-local | `CONTEXT.md` in the role bundle, precontext, OpenCode instructions | Repository review + `make context-check` | Role purpose, boundaries, channel map, self-healing rules | Secrets, live status, personal pages | Built with this change |

## The invariants

1. **Scope narrows, never widens.** A request's `scope` is an allow-list; an
   answer may declare a subset, never a superset. A share narrows on receipt.
2. **A signed answer is data, not instructions.** Retrieved or delivered content
   is labelled as data. It cannot turn into a command, a tool call or a guard
   operation because it arrived over the overlay.
3. **Personal pages never enter a shared corpus.** `NODE_ROOTS` and
   `FABRIC_ROOTS` are allow-lists; `00_System`, `02_Daily`, `03_Sources`,
   `sessions`, `_raw`, `_staging`, keys and `MEMORY.md` are excluded. The shared
   4223 service serves the `fabric` allow-list and a `shared` collection built
   only from `01_Inbox/share-*` payloads, never the whole tree.
4. **Knowledge arrival is recorded.** An RFI answer gets an `inbox_acceptance`
   block. A share gets signed transition events. A telemetry report is spooled.
   A local write is signed. An unrecorded arrival is a fault, not a convenience.
5. **A conflict is held, never silently overwritten.** A share reconciliation
   is additions plus conflicts; a conflicting page waits for a human.
6. **The Master is not a query oracle for arbitrary data.** It answers within
   the peer's existing scope. It does not read a peer's vault, and it does not
   push personal material.
7. **Telemetry and admin traffic are not knowledge.** The user's AI must not
   answer from an auth-event feed, a metrics spool or an admin response. A
   `memory-supervise` response is operator evidence; the Master's own AI must not
   ingest it.
8. **Local-first is the default.** With no Master, chat, planning, building,
   vault reads and self-healing keep working. The node loses authority and
   external knowledge, not usefulness.
9. **The context pack is not a knowledge channel.** It carries role rules and
   pointers, not user or fabric content. It is generated, never hand-edited.
10. **Uplift is training data, not an answer corpus.** A consented snapshot,
    trace or KV artifact on the Master feeds the distillation pipeline. It is
    never served by `4223`, never installed into a vault, and never used to
    answer a user's question; a user's AI may not cite it.
11. **Memory is an index, not a channel.** It reads only sources the node may
    already read, keeps their provenance, and never creates a second vault. The
    store is per-vault; a query cannot cross `vault_id`.
12. **One memory plane per vault.** OpenCode, Open WebUI and the console are
    adapters over the same store. A surface-local memory is a second answer to
    "what does this vault remember" and is refused.
13. **The agent engine is an execution surface, not a channel.** The OpenCode
    engine answers the signed-in user from that user's own vault. It cannot read
    another user's vault, the role vault, the ledger or a key, and its output is
    not a fabric answer, a registry entry or an authority grant. A build tool
    executes only inside its per-user sandbox.

## What a user's AI may answer from

Allowed:

- the node's own vault, within the session's grant scope;
- the user's `peer-<user_id>` vault and KB, including the OpenCode engine's
  read-only view of that same vault;
- the structure-only RAG corpus (contracts, charters, design docs, `CONTEXT.md`);
- a Master-signed RFI answer after it is installed and accepted;
- a share the node has accepted, after reconciliation.

Not allowed:

- registry entries, approvals, telemetry, auth events or admin responses;
- an answer whose `scope` did not include the category it cites;
- a page outside the session's `vault_scope`;
- another user's `peer-<id>` vault;
- an unaccepted inbox item;
- anything from `4221`/`4223` before that service is built and its corpus policy
  is enforced;
- an uplift snapshot, trace, inventory or KV manifest, or anything distilled
  from it, until a separately signed model card is deployed and accepted.

## Build-time context

The node image and the role bundle carry `CONTEXT.md`, the MASTERSPIKE format
prompt and a contracts-derived digest. They are baked from the same commit as
the code. This is the only automatic Master→peer knowledge flow: it is a
build-time snapshot of the fabric's shape, not a runtime push and not a source
of authority. A running node re-reads its local vault and KB; it does not treat
the baked context as current state.

## Runtime knowledge

The runtime path for user-needed fabric knowledge is the RFI loop:

```
peer AI / operator
  -> POST /api/v1/rfi-request (8090, overlay-attributed)
  -> Master queues the request
  -> Master responder gathers from the allow-listed fabric corpus
  -> Master signs a scoped answer
  -> POST /api/v1/rfi (peer guard, 9090)
  -> shared/sparknet-rfi-install.py installs into 01_Inbox/
  -> inbox_acceptance is recorded
  -> the vault self-healing pass indexes the accepted page into the user's KB
```

Silence is an answer. An unreachable Master means the request is not answered;
the node keeps serving its local knowledge. A request never grants, revokes,
escalates or widens anything.

## Change rule

This map changes when a channel changes. A new channel that carries content an
AI may answer from must add a row here, name its authentication, state what it
must never carry, and be reflected in `contracts/ports.json` before any role may
claim it. A change that touches both roles is one commit followed by
`make contract-test`.
