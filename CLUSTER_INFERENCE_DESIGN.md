# Cluster inference design — the `sparknet-cluster` prompt

Status: **design proposal, plus three adopted increments.** The two capability
names `cluster-dispatch` and `cluster-serve` are reserved in the closed
vocabulary; the typed `sign-cluster-job` signer operation is built; and the
node's own AI stack is declared as committed config (all three see
*Adopted* below). Everything else here — the envelopes beyond the job projection,
the services, the ports, the Open WebUI interface and the role behaviour — is a
**proposal** until it is adopted in its own commit with `make contract-test`
green and both roles edited together. Nothing in the proposal half binds
`contracts/`.

This is the fabric-root sibling of `COMPUTE_CAPABILITY_DESIGN.md` (Step 24).
Where that note designed the narrowest possible delegated task — a closed
whitelist of two pure operations — this one designs what happens when the
delegated work is **an LLM prompt answered by another node**, and when many
nodes answer parts of one problem together.

## What was asked, in the fabric's terms

An operator wants, on top of the existing peer/master fabric:

1. Every node runs its own model server (Ollama, in Docker) and hosts its own
   Open WebUI; the Master node is a node like the others for its own prompts.
2. A prompt can be **sent to a chosen node** and fulfilled there.
3. A prompt can be sent to the **whole cluster** — a "sparknet-cluster" option —
   so the connected nodes each take part and contribute to one answer.
4. Node-local prompts retrieve from that node's own vault; **cluster jobs
   retrieve from the Master's shared vector database**.
5. Every cluster job is recorded in the **initiator's** sessions and the
   **Master's** sessions.

The fabric already has most of the authority primitives this needs. What it does
not have is a *job*: a signed envelope that says "this prompt, divided this way,
answered by these nodes, merged like this". That is what this note specifies.

## The invariants this has to respect

Four rules the rest of the fabric is built on, and how a cluster prompt lives
with each:

| Invariant | Where it lives | Consequence here |
|---|---|---|
| **Authority is key possession, not remote command.** A node cannot be made to authorise a change to itself. | `contracts/capabilities.json` `master_capabilities`; `master-node/.opencode/agents/cluster-admin.md` | Cluster jobs are dispatched work, never remote mutation. At three or more members the Master **ratifies** the job; it does not run the peer's model or touch the peer's files. |
| **Broadcast is rejected; shares are one-to-one.** | `MCP_A2A_DESIGN.md`; `contracts/share-protocol.md` | Fan-out is **N separate signed one-to-one requests**, never one multicast datagram. There is no "cluster bus". |
| **A signed act is typed, never "sign these bytes".** | `master-node/services/sparknet-signer.py` | The Master's ratification is a new **typed** signer operation over a canonical job, in the shape of `_sign_guard_approval`. |
| **Silence is a refusal; everything fails closed.** | `contracts/capabilities.json` `share_clocks.silence_is_an_answer`; `guard-protocol.md` | An unreachable Master means no ratification, so no subtask is served. Nothing queues waiting for a decision. |

## Adopted in this commit

Three things: the capability **names** are reserved so no future work has to widen
the closed set in passing, the **typed signer operation** that will ratify a
job is built with its refusals tested, and the node's **own AI stack** is
declared as committed config so the "every node runs its own model server" rule
survives a redeploy instead of living in a human's memory.

- `contracts/capabilities.json` — `known_capabilities` and `definitions` gain
  `cluster-dispatch` and `cluster-serve`.
- `shared/sparknet-authz.py` — the hard-coded `KNOWN_CAPABILITIES` frozenset
  gains both. `tests/test_contracts.py` asserts the two sets are equal and that
  `definitions` names exactly `known_capabilities`, so a one-sided edit fails
  the build rather than half-working.
- `shared/sparknet-authz.py` — gains the job projection: `CLUSTER_JOB_MODES`,
  `CLUSTER_JOB_FIELDS`, `cluster_job_message()` and `is_expired()`. This is the
  *single* canonicalisation of a job, so the signer and the future verifier
  cannot drift the way `sign-guard-approval` and the guard did — the lesson
  recorded in this role's ledger.
- `master-node/services/sparknet-signer.py` — `sign-cluster-job`, a typed
  operation over the projection above, modelled on `_sign_guard_approval`.
  `master-node/tests/test_signer_isolation.py` refuses a job that is missing a
  required field, carries an empty partition, names an unknown mode, has expired
  or unparseable expiry, and proves the signature covers `subtasks`.

- `peer-node/configs/ai-stack/docker-compose.yml` (read by
  `peer-node/tests/test_node_ai_stack.py`) — the node's own inference slice of
  adoption item 3: exactly `ollama` (`:11434`, OpenAI-compatible at `/v1`) and
  `open-webui` (`:8080`, pointed at `http://ollama:11434` via compose service
  name, `RAG_INGESTION_ENABLED=false`, `WEBUI_AUTH=true`, signup disabled), both
  bound to `127.0.0.1` only, no GPU declared (GPU is a host-deployer device
  reservation, never part of the committed file), `peer-node/manifests/ai-stack.json`
  declaring the claims and the wiring tests asserting them read off the files.
  **Declared, not deployed**: no image is pulled and nothing binds 11434/8080;
  the running healthcheck is `DoD: confirm: user`. Task ingress is deliberately
  absent here and lands with adoption item 5 (the cluster client + reducer), so
  nothing in this file can yet be a vector for delegated inference.

Reserving a name grants nothing and the signer operation authorises nothing on
its own. A capability is inert until the Master signs a registry entry that
carries it, and `sign-cluster-job` is not called by any service in the tree
today. It is the instrument the later steps (cluster client, reducer) will use;
it deliberately has no caller yet.

| Capability | Side | Sensitive | Why |
|---|---|---|---|
| `cluster-dispatch` | initiate a job | **no** | Launching a job makes no peer act by itself — ratification (n≥3) or the initiator's own signature (n=2) is the gate. |
| `cluster-serve` | accept a subtask | **yes** | The second sensitive capability after `guard-apply`, and in the **confidentiality** direction: the holder lets delegated inference read its local knowledge and returns the result to the cluster. It generalises `compute-serve` from a closed op whitelist to a signed prompt. |

A node running its **own** prompts needs neither capability. The gate is on
*delegated* work only, exactly as `COMPUTE_CAPABILITY_DESIGN.md` draws the line
for `compute-serve`.

## The job envelope

What a cluster job *is*. One initiator builds it; where governance requires, the
Master ratifies it; each participant receives only its own subtask.

```
sparknet.cluster-job.v1 {
  job_id, conversation_id, initiator_node_id, created_at, expires_at,
  mode:         "decompose" | "shard" | "best_of_n" | "mixture",
  prompt,                       # the original request
  running_summary,              # compact digest of prior turns, never full history
  context:      { source: "master_vector_db", query, top_k },
  budget:       { max_nodes, max_rounds, tokens_per_node },
  subtasks:     [ { node_id, subtask_id, instruction, context_refs } ],
  signature_b64,                # initiator's node identity key
  ratification_b64?             # Master's operational key, when governance requires it
}
```

Rules that keep it honest:

- **The whole subtask plan is inside the signature.** Signing only a job id would
  let anyone replay it against different instructions or different recipients.
- **`context_refs`, not bulk context, except where a shard is the content.** The
  prompt names what to retrieve from the Master's vector DB; only a `shard` job
  ships the actual chunk text to the node that must read it.
- **`budget` is bounded and signed.** `max_nodes`, `max_rounds` and
  `tokens_per_node` are part of the authorisation, so a job cannot fan out
  without limit or recurse forever.
- **`expires_at` is absolute.** A job that misses its window is refused, not
  retried (`silence_is_an_answer`).

A participant receives a **subtask view**: its own `subtask_id`, `instruction`,
`context_refs`, and the job's `expires_at` and `mode` — never the other nodes'
instructions, and never another node's answer.

## The result envelope

```
sparknet.cluster-result.v1 {
  job_id, subtask_id, node_id, fingerprint,
  answer,                       # bounded text
  citations: [ { page, node_id } ],
  confidence, model, tokens, completed_at,
  result_digest,                # sha256 of the full answer when only a digest is returned
  signature_b64                 # executor's NODE IDENTITY key
}
```

The signature asymmetry is the same one `consensus-protocol.md` draws between a
vote and a grant: the Master's **operational** key (or the initiator's identity
signature, at n=2) *authorises* the work; the executor's **node identity** key
*attests* who produced the answer. A result signature proves provenance, never
permission.

## Dividing the work

Each node is an independent model server with a bounded context window, so
cluster work is **map → reduce over model calls**, not tensor parallelism across
machines. Four modes; the initiator picks one from the prompt shape and the
retrieved-context volume, and the Open WebUI cluster toggle can force one:

| Mode | Use when | How the problem is divided |
|---|---|---|
| `decompose` | multi-part reasoning | The initiator's model emits a small DAG of independent sub-questions; leaves are assigned to nodes round-robin, weighted by reported capability and load. |
| `shard` | a large corpus ("analyse this") | The Master's vector DB returns the top-K set; it is cut into **disjoint shards**, one per node, and each node reads only its own shard. |
| `best_of_n` | short but hard | Every node answers the whole prompt with a different model, temperature or seed; the reducer selects and merges. |
| `mixture` | genuinely hard | Bounded rounds: draft, cross-critique, synthesise. `max_rounds` caps it. |

Division is the initiator's job; **assignment is deterministic given the
subtask list**, so the same job re-dispatched produces the same partition. The
non-determinism lives only in the model output, never in who was asked to do what.

## Re-forming the answer

The initiator **reduces**: its own model runs a synthesis pass over the signed
partials.

- Merge partials in subtask order; deduplicate citations by `(page, node_id)`.
- Emit **contradiction callouts** where nodes disagree, rather than silently
  picking one.
- Produce a **contribution map** — which node answered which part — so the answer
  is attributable, not anonymous.
- If the reducer judges coverage incomplete, it may emit **one more bounded
  round**; `max_rounds` is the hard stop. That bounded iteration is what makes
  the conversation "evolve" without turning into an unbounded loop.

The final object returned to Open WebUI is the merged answer plus the
contribution map and merged provenance. The partials and the map are what get
recorded (see *Recording*), so the cluster's reasoning is auditable.

## Authority and topology

```
Open WebUI (node X)  ── sparknet plugin ──▶  cluster client
   target:  Local  |  Node Y  |  sparknet-cluster
        │
        ├─ Local   ──▶ node X's own model ──▶ node X vault (grant-checked tools)
        └─ Cluster ──▶ initiator builds the job
                          │  sign with node X's IDENTITY key (cluster-dispatch)
                          │  n>=3: Master ratifies (typed signer op)
                          │  n=2 : initiator signature is sufficient
                          ▼
                   N x separate 1:1 signed subtasks   (never one multicast)
                          │  context: Master vector DB, top-K per job
                          ▼
                   each node's own model answers its subtask  (cluster-serve)
                          ▼
                   reduce on the initiator ──▶ answer + contribution map
                   canonical conversation on the Master; per-node session copies
```

- **Initiator.** Any node holding `cluster-dispatch`. It builds, signs and
  reduces. It is also a worker for its own share.
- **Master.** At `master_governed` (three or more members, per
  `overlay.json → governance_mode`) it **ratifies** every job before any
  `cluster-serve` node accepts a subtask. At `peer_pair` (exactly two members)
  no ratification is available or required — the initiator's signature stands,
  consistent with the symmetric pair rule. At `solo` there is no cluster to fan
  out to.
- **Participants.** Any node holding `cluster-serve`. A participant accepts only
  a well-formed, unexpired, un-ratified-without-ratification subtask for itself.

The mode is recomputed from the signed registry on every job, never cached and
never chosen by the node being asked — a third node joining changes the mode for
*new* jobs, it does not retroactively ratify an old one.

## Knowledge: local vault vs shared cluster vector DB

The split you asked for is the correct one and it maps onto existing surfaces:

- **Node-local prompt** → the node's own vault, through the same grant-checked
  retrieval the node already uses for its own inference. No cluster call, no
  `cluster-serve`, no Master involvement.
- **Cluster job** → the **Master's shared vector database**. The Master
  *serves* top-K queries over the overlay; it does **not** replicate the index
  to every node. This is the recommended option from the design review: it keeps
  one authoritative index, avoids corpus sprawl, and makes the retrieval path a
  single thing to bound and audit. The index itself is port `4223`
  (`vector-embed`), currently `spec-only` in `contracts/ports.json`; this design
  is one of the reasons to build it.

Only a `shard` job ships chunk text to a node; `decompose`, `best_of_n` and
`mixture` pass references and let the node query the Master's index.

## The Open WebUI interface

The Open WebUI work is the operator's; sparknet exposes a small **cluster
endpoint** the plugin calls. The plugin is not required to know about
signatures, envelopes or the overlay — it hands the cluster client a prompt and
a target, and streams status back.

```
submit(target, conversation_id, prompt)   -> job_id
status(job_id)                            -> { phase, nodes_answered, total }
result(job_id)                            -> { answer, contribution_map, citations, conflicts }
```

- `target: local` is a passthrough to the node's own model.
- `target: node/<id>` dispatches a one-node cluster job (a job with one
  subtask) — the "send a prompt to a specific node" case.
- `target: cluster` selects the mode automatically and fans out.

The "suggest cluster when the problem is big" behaviour lives entirely in the
Open WebUI prompt layer; it only needs to call `submit(target="cluster", …)`.
A size heuristic is advisory — the operator can always force the target.

## Recording

Every cluster job that actually ran is recorded on both sides you named:

- **Initiator** writes a job record — job id, mode, subtasks, partials,
  contribution map, final answer — to its own `sessions/<date>.md`.
- **Master** writes the same job record, plus the ratification (or the reason
  none was required at n=2), to its own `sessions/<date>.md`.
- Each **participant** records its own subtask and answer locally.

The record is the job envelope plus the result set, so the audit trail shows what
was asked, who authorised it, who answered what, and what was merged. In
`master_governed` the Master's copy is the canonical cluster conversation; in
`peer_pair` the pair's two copies are the record.

## Security boundaries

- **Auto-execute means the inference, not the actions.** A validly signed subtask
  is answered with no human prompt on the serving node. But any tool, file or
  network action the *answer* triggers still passes that node's own guard and
  Plan-Permission-Execute gate. Without this line, a poisoned chunk in the
  shared vector DB becomes remote execution on every node at once; with it, the
  blast radius of a bad corpus is bad *text*, not bad *state*.
- **The shared index is hostile input.** Retrieved cluster content is data, never
  instructions. The serving node's prompt assembly must label it as data and its
  guard must not treat text from the index as a command.
- **Ratification is typed.** The Master signs a canonical job, never arbitrary
  bytes, through the same refusal discipline as `_sign_guard_approval` (unknown
  fields, blank fields, an already-expired job are refused). Built as
  `sign-cluster-job` over `authz.cluster_job_message`, which projects the job to
  the fixed `CLUSTER_JOB_FIELDS` so metadata added later cannot silently join the
  signature.
- **A participant's data leaves.** That is exactly why `cluster-serve` is
  `sensitive: true` and granted per node: enabling it is an operator decision
  about *that node's* knowledge leaving *that node*.

## Docker packaging

The node's AI stack ships as containers, built on the peer's Step 2 container
step. **The Step 2 base is now built (2026-10-10)**: `peer-node/container/` +
`configs/container/` provide the multi-arch CPU opencode image and the long-lived
anchor sidecar; the stack's compose joins that base when it lands. Currently:

- `ollama` with GPU passthrough, serving on the loopback/local overlay address
  the node chooses.
- `open-webui`, pointed at that node's own `ollama`, with its built-in RAG store
  **off** — the vault (local) and the Master's index (cluster) are the only
  knowledge sources, consistent with the Master admin surface's
  `RAG_INGESTION_ENABLED: "false"`.
- the **task ingress** that accepts signed subtasks, and the **cluster client**
  the Open WebUI plugin calls.

A node's own prompts never leave the node's containers. Only a served subtask
crosses the overlay, and only the signed result comes back.

## Where this lands

This is cross-role work, so it belongs at the fabric level, in its own commits,
with `make contract-test` between them. The capability names are already
reserved; the rest is proposed:

1. **This commit** — reserve `cluster-dispatch` / `cluster-serve` in both
   places; this note at the fabric root; and build the typed `sign-cluster-job`
   operation plus its projection in `shared/sparknet-authz.py`. (Done: the note,
   the reservation, and the signer op with refusal tests.)
2. **Typed signer operation** — `sign-cluster-job`, modelled on
   `_sign_guard_approval`, with refusal tests (unknown field, blank field,
   expired job, non-canonical mode). Master-side. (**Done** with this commit;
   now consumed by step 5.)
3. **Node AI stack** — containerise `ollama` + `open-webui` + task ingress;
   node-local retrieval through the vault. Peer-side. (**Slice A done**: the
   own-inference compose + manifest + wiring tests are adopted and declared, not
   deployed — see *Adopted* above. Task ingress rides with item 5.)
4. **Master vector DB** — implement port `4223` (`vector-embed`), index the
   cluster corpus, serve overlay-only top-K. Master-side.
5. **Cluster client + reducer** — build and sign a job, fan out N one-to-one
   subtasks, verify signed results, merge. Peer-side, with the Master
   ratifying at `master_governed`.
6. **Open WebUI target selector** — `local` / `node/<id>` / `cluster`; the
   plugin calls the interface above.
7. **Recording** — the job record on initiator, Master and participants.
8. **Gates + live deploy** — `make test-all`, `lint`, `contract-test`,
   `validate`, `keys-check`, `shims-check` green; live deploy is
   `DoD: confirm: user`.

## Options considered and rejected

| Option | Verdict | Reason |
|---|---|---|
| One multicast "cluster bus" | **rejected** | Breaks the one-to-one share rule and gives every node an authority-plane peer edge. Fan-out is N signed one-to-one requests instead. |
| Master runs every node's model | **rejected** | Turns the Master into a remote-execution controller, the exact thing the authority model forbids. The Master ratifies; each node runs its own model. |
| Shard the model itself (tensor parallelism) | **rejected for v1** | Ollama is a single-node server. True model sharding needs a different serving stack (for example a vLLM/Ray cluster) and pooled memory; that is a much larger, separate design. Map→reduce over independent nodes is the honest fit. |
| Replicate the shared vector DB to each node | **rejected** | Every node then holds the whole cluster corpus and must sync it. Serving top-K from the Master keeps one index and one audit path. |
| Auto-execute with no action guard | **rejected** | Makes a poisoned corpus into remote execution. Inference auto-executes; actions stay guarded. |
| One node holds the canonical conversation | **adopted** | The Master holds it in `master_governed`; nodes keep their own session copies, so a node's participation survives independently. |

## Provenance and consistency

- Grounded in `contracts/capabilities.json` (closed vocabulary, `guard-apply` and
  `cluster-serve` sensitive notes, `governance_mode` counts,
  `silence_is_an_answer`), `contracts/overlay.json` (`governance_mode` =
  `solo`/`peer_pair`/`master_governed`, authority-plane invariant),
  `contracts/identity-schema.json` (canonicalisation, the permission/provenance
  signature split), `contracts/share-protocol.md` (one-to-one shares, evidence),
  `contracts/consensus-protocol.md` (vote vs grant asymmetry),
  `contracts/ports.json` (`4223 vector-embed` spec-only; `8080` admin surface),
  `COMPUTE_CAPABILITY_DESIGN.md` (the `compute-serve` predecessor this
  generalises), and `MCP_A2A_DESIGN.md` (A2A over the signed transport,
  broadcast rejected).
- The adopted increments are the two capability names, the typed
  `sign-cluster-job` operation (with its canonical projection in `shared/`), and
  the node's own AI stack as committed config (peer-side, declared not
  deployed). Every other statement here is a proposal about where the existing
  primitives could reach, and it is adopted only by its own commit with both
  roles edited together and `make contract-test` green.
