# Cluster job realization design — one envelope, one index, N signed subtasks

Status: **design proposal, nothing adopted.** This note creates no port, grants
no capability, changes no contract and adds no daemon. It does not touch
`contracts/capabilities.json`, `contracts/ports.json`,
`shared/sparknet-authz.py` or `contracts/manifest.json` — the "nothing adopted"
property of a design step is exactly the point, and `git status` proves it.
Everything here is adopted only by its own commit, with both roles edited
together and `make contract-test` green.

This is the fabric-root sibling of `CLUSTER_INFERENCE_DESIGN.md` (Step 17) and
`COMPUTE_CAPABILITY_DESIGN.md` (Step 24). It **realizes** the first of those: the
parent note specified *what a cluster job is* — the envelopes, the four modes,
the reduce semantics, the security boundaries. It deliberately left the *how*
open. This note closes that, and in doing so records four defects that any
builder would otherwise have hit blind.

## Why a second note

The parent design is sound. Its invariants — fan-out is N signed one-to-one
requests, never a multicast; the Master ratifies and never runs anyone's model;
silence is a refusal; a poisoned corpus becomes bad *text*, not bad *state* —
are all still the rules. What the parent note does not answer, because it did
not have to, is the set of questions a builder meets on the first day:

1. **Which encoding of the job envelope is authoritative?** Two already exist and
   they do not agree. Neither is provably correct, because nothing pins the
   canonical bytes.
2. **How does a reducer fetch a chunk named by a `context_refs` id?** The parent
   says the Master "serves top-K queries". A reference is not a query.
3. **What corpus does the shared index hold, and who decides?** The tree holds
   two contradictory policy documents.
4. **What is the Master's vector DB actually backed by?** Nothing in the tree
   binds port `4223`.

Those are seams, not details. Each one is a place where two halves of the system
would have been written independently and then failed to interoperate. This note
names each seam, picks a side, and says why the other side lost.

## The four defects

Every one of these was found by reading the tree, not by reasoning about it. Each
cites the file and line it was found on.

### D1 — the envelope has two divergent encodings, and neither is pinned

| | Fabric (`shared/`) | goSpark (`proto/`, `internal/apiv1/`) |
|---|---|---|
| Timestamps | `created_at` / `expires_at`, ISO-8601 (`shared/sparknet-authz.py:468-469`) | `created_at_unix` / `expires_at_unix`, `int64` (`goSpark/proto/sparknet/v1/cluster.proto:41-42`, `internal/apiv1/types.go:183-184`) |
| Optional fields | always projected, as null (`shared/sparknet-authz.py:565`) | `omitempty` — dropped entirely when empty (`internal/apiv1/types.go:178-189`) |
| Expiry check | `is_expired()` parses ISO-8601 (`shared/sparknet-authz.py:493`) | `int64` compare, no parser |

The fabric side is also *shape*-looser than it looks: `cluster_job_message`
(`shared/sparknet-authz.py:544`) validates the required fields, the mode and that
`subtasks` is a non-empty list — and nothing else. It does not check that a
subtask carries `node_id`/`subtask_id`/`instruction`, so a job whose subtasks are
`{"x": 1}` canonicalises cleanly and gets signed.

Worse, the **signer's own test fixture does not match either encoding**.
`master-node/tests/test_signer_isolation.py:226-233` builds:

```python
"context": {"index": "master-local"},
"budget": {"max_tokens": 2048, "deadline_s": 60},
"subtasks": [{"node_id": "beta", "role": "gather", "prompt": "collect logs"}, …]
```

while the parent design and the proto both say `context` is
`{source, query, top_k}`, `budget` is `{max_nodes, max_rounds, tokens_per_node}`,
and a subtask is `{node_id, subtask_id, instruction, context_refs}`. The signer
passes its tests because it never inspects those shapes. A real job built to the
proto would be signed over bytes that mean something else.

**The gap that would have shipped:** `tests/test_authz_golden.py` pins
`authorization_message` and `admin_request_message` with shared golden vectors.
It does **not** pin `cluster_job_message`. So the one projection the whole cluster
arc depends on — the thing the parent design explicitly built to avoid the
`sign-guard-approval`/guard divergence — has no cross-language proof.

### D2 — peer↔peer fan-out is unreachable on the authority plane

`contracts/overlay.json` fixes a peer's `AllowedIPs` at exactly
`10.100.0.1/32`: the Master, and nothing else. A peer's nftables egress rule
matches. So a peer can send a subtask to the Master, and the Master to any peer,
but **peer A cannot reach peer B**. The parent design's fan-out diagram
(`CLUSTER_INFERENCE_DESIGN.md:224`) shows `N × separate 1:1 signed subtasks`
emitted by the initiator — which, when the initiator is a peer and N ≥ 3, is
physically impossible today.

This is not an oversight to fix in passing. A peer's egress being pinned to the
Master is one of the two rules that make revocation meaningful
(`master-node/AGENTS.md`, Boundaries vs a peer). Widening it to a permanent
`10.100.0.0/24` would hand every peer a permanent authority-plane edge to every
other peer, which is precisely what `MCP_A2A_DESIGN.md`'s broadcast rejection
exists to prevent.

**Resolution in this note:** v1 fan-out at `peer_pair` (n = 2) works today and is
the only topology the design claims. At `master_governed` (n ≥ 3) fan-out
degenerates honestly: **the Master is the dispatcher**, not the initiator — it
receives the initiator's signed job, and *it* emits the N subtasks, which is
exactly the topology its egress already allows. A peer-initiated, peer-to-peer
fan-out across three or more nodes requires a time-boxed, job-scoped data-plane
stanza and is a **named, deferred increment** (see *Adoption increments*, item
7). The alternative — pretending n ≥ 3 works today — is the failure mode this
fabric has spent five steps closing.

### D3 — the corpus policy is a deny-list where the charter requires an allow-list

`scripts/sparknet-chroma.py:58` defines `EXCLUDE_PARTS`, a deny-list: everything
not excluded is indexed. `scripts/sparknet-rag-corpus.py` is an allow-list, and
its stated rule is that an exclusion always wins. The peer charter's own RAG rule
is allow-list (`peer-node/configs/ai-stack/README.md`, rule 2: "the corpus is
the shape of the fabric — contracts, charters, taxonomy, design docs — never the
vault's personal pages"). A new page therefore reaches the node's RAG index only
if it is allow-listed, but reaches the `fabric` Chroma scope unless someone
remembers to add it to a deny-list.

For a *cluster* corpus this is worse than inconsistent, it is the wrong default:
a private page that lands in the shared index is served to every
`cluster-serve` node in the fabric.

### D4 — the parent design's vector-store prose no longer matches the committed config

`CLUSTER_INFERENCE_DESIGN.md:77` describes the node's own ChromaDB as
"`chromadb:8000` on the shared node network". The committed config says
something different and says it deliberately:
`peer-node/configs/ai-stack/docker-compose.yml:7` — Open WebUI points at
`http://127.0.0.1:18000`, the node's **out-of-repo `~/infra` compose stack**, and
the file header states that the ai-stack slice "never declares a second model
server or a second vector store". Nothing in this repository binds `11434` or
`18000`; both are host-level infra provisioned out of band. The parent design's
prose predates that 2026-10-11 operator decision and has not been realigned.

Recorded here rather than fixed here, because correcting the parent note is an
edit to an adopted document and belongs in its own commit.

## Seam A — one envelope, one encoding

**Decision: the fabric encoding is authoritative. goSpark and the proto come to
it.**

The reason is not aesthetic. The fabric side is the only one with a canonical
projection function, a fail-closed expiry parser and a passing refusal suite; the
goSpark side has a struct tag and no equivalent. And `shared/sparknet-authz.py` is
by charter the *single* implementation of the signed-authorization scheme — the
peer and the Master both import it, and the parent design's whole anti-drift
argument (`CLUSTER_INFERENCE_DESIGN.md:64-67`) rests on it. Adding a second
canonicalisation in Go would re-create the exact defect that
`sign-guard-approval` and the guard already paid for.

Concretely:

| Field | Canonical form | Rationale |
|---|---|---|
| `created_at`, `expires_at` | ISO-8601 UTC, same parser as registry expiry | `is_expired()` (`shared/sparknet-authz.py:493`) is already the shared parser; a second time format means two notions of "expired" |
| `conversation_id`, `running_summary`, `context`, `budget` | **always projected**, as `null` when empty | `omitempty` removes a field from the signed bytes; a verifier that re-serialises without it produces different bytes and the signature fails. A projected `null` is stable |
| `subtasks[].context_refs` | always projected, `[]` when empty | same |
| `context` | `{source, query, top_k}` | as the parent design specifies; `source` is a closed set, `master_vector_db` first |
| `budget` | `{max_nodes, max_rounds, tokens_per_node}` | as the parent design specifies |
| a subtask | `{node_id, subtask_id, instruction, context_refs}` | as the proto already has it |

**What `cluster_job_message` must additionally gain** (increment 1, not this
commit): shape validation, so a subtask missing `node_id`/`subtask_id`/
`instruction` is refused rather than signed. Today it only checks that
`subtasks` is a non-empty list.

**The proof that closes D1** is a shared golden vector, in the same shape as the
existing `authorization_message` vectors: a fixed job document, its expected
canonical bytes, and its expected sha256, committed under `tests/`. The Python
side (`cluster_job_message`) and the Go side (the proto's `Canonicalise`) must
both reproduce those bytes. A divergence in either direction then fails the
build in the language that drifted, instead of failing as a mystery at dispatch
time.

The signer's `_job()` fixture (`master-node/tests/test_signer_isolation.py:226`)
is rewritten to the canonical shape in the same commit. That is a test-only
change and it is the one thing in increment 1 that touches the Master role.

## Seam B — building the job

Nothing multi-subtask exists. `goSpark/internal/router/router.go` splits a
prompt (`splitPrompt:151`) and picks **one** node
(`internal/server/placement.go` `PlaceAndDispatch`). What is missing is the
construction step between "here is a prompt" and "here are N signed subtasks".

Seam B is the function that takes a prompt, a mode, the retrieved context and a
node roster, and produces the `subtasks` list. Its properties, all inherited from
the parent design:

- **Deterministic given its inputs.** The parent design's rule is that "assignment
  is deterministic given the subtask list, so the same job re-dispatched produces
  the same partition. The non-determinism lives only in the model output, never
  in who was asked to do what." Construction therefore takes the roster in a
  fixed order (node id, ascending) and assigns round-robin from a fixed offset,
  never by arrival order or measured load.
- **Bounded by the signed `budget`.** `max_nodes` caps the partition before any
  dispatch. A construction that would exceed it truncates and records the
  truncation in `running_summary`, rather than silently producing a job it cannot
  dispatch.
- **Shard-only ships text.** For `decompose`, `best_of_n` and `mixture`,
  construction resolves `context_refs` to ids and lets each participant fetch its
  own chunks (Seam F, `GET /v1/doc/{id}`). Only `shard` embeds chunk text,
  because for `shard` the text *is* the work.

## Seam C — placement and fan-out

Two shapes, chosen by `governance_mode` (recomputed from the signed registry on
every job, never cached, never chosen by the node being asked — parent design
rule):

| Mode | Topology | Emitter | Reachability |
|---|---|---|---|
| `peer_pair` (n = 2) | initiator → the one other node | the initiator | **works today, in either direction.** In a two-member cluster one member holds the Master role and the other is a peer, so the pair's edges are exactly `peer → 10.100.0.1` and `10.100.0.1 → peer` — the two `AllowedIPs` the contract already grants. Whichever member initiates, the other is the one it can already reach. No contract change, no relay. |
| `master_governed` (n ≥ 3) | initiator → Master → N participants | the **Master** | the Master's egress is unrestricted and every peer's AllowedIPs include `10.100.0.1`, so this topology is fully reachable with zero contract change |
| `solo` | — | — | no cluster; the job is refused |

The asymmetry is the point. It costs nothing, changes no contract, and is the
only shape the existing overlay admits. A peer-initiated cross-peer fan-out at
n ≥ 3 is deferred as a named increment because it needs a **time-boxed,
job-scoped data-plane stanza** on each target peer — a peer's egress rule grows a
second, short-lived, job-scoped allowance that exists only for the duration of
one job and is torn down when the job closes. That is a real change to
`contracts/overlay.json` and to both roles' nftables, and it is deliberately not
smuggled in as a detail.

Placement itself is the goSpark `internal/placement` package, unchanged in shape.
What it gains is the roster order rule from Seam B, so placement is a pure
function of (subtask list, roster).

## Seam D — reduce

The parent design already specifies reduce semantics; nothing here changes them
(merge in subtask order, deduplicate citations by `(page, node_id)`,
contradiction callouts rather than silent selection, a contribution map, and at
most one more bounded round under `max_rounds`). Seam D adds the two things a
builder needs that the parent note does not state:

1. **Result verification before merge.** Each partial carries the executor's
   **node identity** signature over the canonical result. The reducer verifies
   every signature *before* the synthesis pass, and drops unsigned or
   badly-signed partials with a recorded reason — a partial is provenance, and an
   unverifiable partial is not partial evidence, it is noise.
2. **Coverage is a first-class failure.** If the number of verified partials is
   less than the number of dispatched subtasks at the `max_rounds` stop, the
   reducer returns the merged answer **plus an explicit incompleteness marker
   naming which subtasks never answered**. It never pads. A cluster answer that
   silently omits a third of its partitions is indistinguishable from a complete
   one to the reader, which is the same class of failure as D3's silent
   inclusion.

## Seam E — task ingress

A participant must be able to accept a signed subtask. This is adoption item 5
of the parent design, and it is deliberately absent from
`peer-node/configs/ai-stack/docker-compose.yml` — the file header says so, and
`peer-node/tests/test_node_ai_stack.py` asserts the boundary.

The seam has three parts, none of which this note builds:

- **The loopback routes.** `submit` / `status` / `result` as the parent design
  specifies, served over `shared/sparknet-http.py`'s `serve()` with the peer
  personality, on the existing loopback-only dispatch bridge (`127.0.0.1:4096`,
  `peer-node/services/sparknet-dispatch-bridge.py`) — which already does exactly
  this shape of work for `feed` and `/admin/*`.
- **The acceptance checks.** Same order discipline as Seam F: source, signature,
  registry, capability (`cluster-serve`), expiry, shape — cheapest decisive
  first, fail-closed at every step. `--execute-enabled` is off by default,
  mirroring the guard's `--apply-enabled` and `COMPUTE_CAPABILITY_DESIGN.md`'s
  rule that arming a node to do delegated work is an operator decision.
- **The boundary that makes it safe.** A validly signed subtask auto-executes the
  *inference* with no human prompt. Any action the answer triggers still passes
  that node's guard. This is the parent design's line, restated because it is the
  one that keeps a poisoned corpus from becoming remote execution.

## Seam F — the Master's shared vector database (port 4223)

This is the seam the operator marked load-bearing, and the one the tree is
furthest from. `contracts/ports.json` lists `4223 vector-embed` as
`implementation_state: spec-only`, `runtime: not-listing`, bound to
`10.100.0.1`, `overlay_only: true`, with a status string pointing at
`master-node/plans/MASTER_ADMIN_PLAN.md` — a 59-line spec that scopes the four
infrastructure-administration services and builds none of them.

### F0 — the three industry patterns, weighed against this fleet

Sharing a vector store across AI workers has three established shapes. All three
were considered against the measured facts of this fabric:

| Pattern | Verdict | The number that decides it |
|---|---|---|
| **Native distributed VDB** (Milvus / Qdrant, compute–storage separation: stateless query nodes, sharded index nodes, shared object-store persistence) | **Rejected for v1. Designated upgrade path, with a numeric trigger.** | The allow-listed `fabric` corpus is **28 markdown files, 381 KiB, 242 chunks** at `scripts/sparknet-chroma.py`'s 2000-char default (measured 2026-10-22; `make chroma-inspect CHROMA_SCOPE=fabric` prints the count and the corpus digest). A query-node pool, a sharded HNSW index and a MinIO tier is roughly a hundred times more infrastructure than there is data. The trigger that re-opens the question is in F2. |
| **HA clustered deployment** (hash or vector-space sharding + 2–3× replication + etcd/Raft consensus) | **Rejected outright** | The live fleet is **two Jetson AGX Xavier hosts, 16 GB each, on a 1 Gbit cable**. A replication factor of two across two hosts tolerates no failure at all — the second replica is on the box that is down. And the fabric already runs a consensus domain for *authority* (`shared/sparknet-consensus.py`); a second one for vectors would create two membership truths, which is the defect the whole authority model exists to avoid. |
| **PostgreSQL + pgvector** (primary/replica streaming, or Citus for horizontal scale; one transaction boundary for relational metadata and vectors) | **Rejected** | Its real value is that you already run postgres. This tree runs no postgres, so it buys a new daemon, a new backup story, and strands the `chroma` extra and the substrate script that already exists. |

**The pattern this fabric actually needs is the inverse of all three.** Every one
of them assumes the vector store is a *primary system of record* that must be
distributed to stay available. Here it is **derived state**.
`plan_index()` and `chunk_text()` in `scripts/sparknet-chroma.py` are pure
functions and `upsert` is idempotent, so the index is a deterministic function of
signed vault content. That inverts the availability question: you do not
replicate an index you can rebuild from source. You cannot corrupt it, only lag
it.

The design therefore is:

| Property | The choice | Which industry concept it takes |
|---|---|---|
| Write | **single writer** — the Master, the host that administers infrastructure (`ports.json` already pins `bound_by: master`) | compute–storage separation, at 1/1000 scale |
| Read | **stateless readers** — every node queries over the overlay; the service holds no in-memory index and reloads from disk on restart | exactly the stateless query-node half of pattern 1 |
| Store | local disk under `.state/chroma/` on the Master; no shared backend, no object tier | the shared persistence layer, made unnecessary by the corpus size |
| Distribution | **the WireGuard overlay**, which is already the encrypted mesh | the network-topology item, satisfied by existing infrastructure |
| Consistency | **rebuild from source, not replicate.** A stamp mismatch refuses rather than serving | the strongest guarantee of the three, at zero cost |

### F1 — what 4223 is

A Master-hosted HTTP service over the **`fabric`-scope** Chroma store that
`scripts/sparknet-chroma.py` already declares itself the substrate for (its
module docstring says so). It serves exactly **one collection,
`sparknet-fabric`**. The node-local RAG on `127.0.0.1:18000` (provisioned out of
band in the node's `~/infra` stack, per `peer-node/configs/ai-stack/docker-
compose.yml:7`) and goSpark's separate `.state/rag/index.json` path are named
here as **not this**, and are not changed by anything in this note.

### F2 — the backing store

Chroma `PersistentClient` at `$SPARKNET_STATE_DIR/chroma` — the embedded,
on-disk client, **not** a `chromadb` HTTP server. 4223 is our own thin listener
on `10.100.0.1:4223`, built on `shared/sparknet-http.py`, which already provides
everything this needs: `serve()`, `source_kind()` (which decides overlay vs local
personality from the *connection*, never from a claim), `check_source_policy()`,
and `loopback_only_routes` for the admin face.

Rejected: binding the `chromadb` server directly on 4223. It has no registry
check and no capability gate, and its authentication model is a static API key —
the wrong shape entirely for a fabric whose authority comes from key possession
and a signed registry.

**The upgrade trigger, numeric and checkable.** Milvus or Qdrant is re-opened
when *any* of these holds, and not before:

| Trigger | Value | Why that number |
|---|---|---|
| corpus size | **> 100,000 chunks** | 238 today. At 384 dimensions a float32 vector is 1.5 KB, so 100k chunks is ~150 MB of vectors — the point where a single-node HNSW index stops being "tens of MB of RAM" and starts being the thing that decides the node's memory budget. |
| query latency | **p95 > 200 ms** over 1,000 queries | below the model's own generation latency, so a slower store is invisible next to the answer it feeds. |
| fleet | **a third host joins the fabric** | two hosts is a failover story; three is a cluster, and a cluster needs a clustered store. |

Until one of them is true, the embedded client *is* the store — no daemon, no
port, no second membership truth.

**What the store costs the node.** Measured for 242 chunks on the development
host: the index is **8 MB on NVMe** under `.state/chroma/` (6.6 MB of it the
sqlite metadata) and a query process peaks at **115 MB RSS** — most of which is
the interpreter and chromadb itself, not the vectors (242 × 384 floats is
372 KB). It is not free, but it is not a service either: nothing to supervise,
nothing to authenticate, nothing to back up beyond the source files — the index
is derived state and is rebuildable.

**One ARM64 caveat, measured.** chromadb's `chroma-hnswlib` has no aarch64
wheel, so `pip` builds it from source on the node (several minutes, and the
build must run with bounded parallelism — an unbounded native build pins every
core, and the node's failure mode for that is a thermal reset with no kernel
trace). The fork also provides the `hnswlib` import name that chromadb expects
and carries `Index.file_handle_count`; the plain PyPI `hnswlib` must never be
installed alongside it.

### F3 — embedding, and the model-consistency rule

Query embedding is **server-side only**: the caller sends query text, the service
embeds it and queries. This is what `cmd_query` already does
(`collection.query(query_texts=[query], …)`). It is the only sound shape, because
a caller-supplied vector is indistinguishable from garbage unless the caller used
exactly the same model — and "exactly the same model" is not something the wire
can check.

**Rule: the index-time and query-time embedder must be the same one. Changing it
requires a full reindex.** The tree currently fails this rule in a way that would
have bitten silently: `pyproject.toml:29` pins `chromadb>=0.5`, **unbounded
above**, and Chroma's default embedding function is fetched by that library. A
chromadb upgrade can therefore change the embedding model under a live index and
every distance returned afterwards is meaningless while looking entirely healthy.

Four consequences, all in the design so the builder does not have to find them:

1. The pin becomes bounded (`>=0.5,<1`) and the resolved model name is recorded
   in the docstring of the reindex target.
2. The collection carries **stamp metadata** — `embedding_model`,
   `embedding_sha256`, `chroma_version`, `corpus_digest` — written at index
   time.
3. The serve path **checks the stamp on every query and refuses with 503 on
   mismatch.** A stale index is a loud failure, never a quiet wrong answer.
4. The embedder is **passed explicitly on every open**, never taken from the
   library default.

Point 4 is the one the first three do not cover, and it is the reason the
stamp has a model field at all. Chroma's default embedding function cannot
identify itself: on 0.6.x the object carries no usable name, and on 1.5.x it
reports itself as `default` with an empty configuration. A stamp written from a
name like that is not a stamp. So the substrate names the embedder itself —
`ONNXMiniLM_L6_V2`, i.e. `all-MiniLM-L6-v2`, sha256
`913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3` — and
records *that* name and *that* hash, so a mismatch is decidable rather than
merely detectable. The same explicit embedder is passed on every open, so the
library default can never decide the model behind an existing collection.

**Which differences refuse and which only report.** `embedding_model`,
`embedding_sha256` and `corpus_digest` are refusals: the index was written by a
different model or holds a different corpus, so a distance from it means
nothing and the answer is refused (503 on the wire, exit code 3 in the
substrate script). `chroma_version` is reported, not enforced: the library
version is not what makes a distance meaningful — the model and the corpus
are. Refusing on a version difference would train every operator to ignore the
refusal.

The base runtime allow-list stays `cryptography`. 4223 requires the opt-in
`chroma` extra and must fail closed with a 503 and a `make chroma-dev` hint when
chromadb is absent — never an empty result set, because an empty result set is a
sentence, and this service must not be able to write one by accident.

Upgrade path, named and not built: a GPU-backed embedder behind the existing
`vllm-embed` profile (8001). That is the correct place to spend GPU on retrieval,
and it needs the same rule — full reindex on switch.

### F4 — corpus policy

**The `fabric` scope becomes an allow-list**, matching the peer charter's own RAG
rule and `scripts/sparknet-rag-corpus.py`, whose stated precedence is that an
exclusion always wins. Concretely: the allow-list rules of
`sparknet-rag-corpus.py` are reused for the `fabric` scope, and `EXCLUDE_PARTS`
in `scripts/sparknet-chroma.py` stops being the primary gate and becomes a
belt-and-braces second list.

The rationale is not tidiness. A deny-list requires someone to notice that a new
page is sensitive. An allow-list requires someone to notice that a new page is
safe. For a corpus that is served to every `cluster-serve` node in the fabric,
only the second failure mode is survivable.

A test in the spirit of `tests/test_rag_corpus.py` proves that no excluded path
reaches the 4223 index. That test is part of increment 2, not this commit.

**Implemented (2026-10-22, increment 1).** The allow-list is the policy in
`scripts/sparknet-rag-corpus.py`, written once, with two lists: `NODE_ROOTS`
(what a node ingests into its own Open WebUI) and `FABRIC_ROOTS` (the node's
roots plus the fabric's own design documents — `USER_MANUAL.md`,
`CLUSTER_JOB_REALIZATION_DESIGN.md`, `PER_USER_VAULTS_DESIGN.md`,
`ADMIN_FEDERATION_DESIGN.md`, `STYLE_GUIDE.md`). `FABRIC_ROOTS` is a strict
superset; the exclusion rules, the contract tree and the role charters are
identical for both, so naming the fabric list cannot buy a laxer policy.

The measured difference is the argument for the rule. Under the old whole-tree
deny-list the `fabric` scope served **138 markdown files and 1,699 chunks**, of
which **1,090 chunks (64%) were personal or runtime pages** that no node should
ever have been handed. The allow-listed corpus is **28 markdown files, 381 KiB,
242 chunks**.

`tests/test_vector_corpus.py` proves it against the real repository: only
allowed paths reach the index, and the contract tree, both role charters and
the design documents are all present.

### F5 — the API

| Route | Method | Personality | Returns |
|---|---|---|---|
| `/v1/health` | GET | overlay | liveness, corpus digest, stamp |
| `/v1/query` | POST | overlay | `{id, path, snippet, distance}` per hit |
| `/v1/doc/{id}` | GET | overlay | the full chunk text — this is how `context_refs` resolves on a participant |
| `/admin/reindex` | POST | **loopback-only** | triggers a reindex; only the Master operator can reach it |

Bounds, so the 1 Gbit link is never a surprise: `top_k ≤ 20`, snippet ≤ 300
characters in `/v1/query` responses, and full chunk text only via the
authenticated `/v1/doc/{id}`. A shard job is the one case that ships chunk text,
and it does so through the signed subtask envelope, not through this API.

The id in `/v1/doc/{id}` is validated against the collection's actual ids. It is
never used as a filesystem path — the index stores a `path` in metadata, and
serving it means reading a chunk out of the collection, not opening a file.

### F6 — authentication, cheapest decisive check first

Ordered the way `COMPUTE_CAPABILITY_DESIGN.md` orders its executor's checks,
because the reasoning is the same:

1. **Source address** — in the overlay CIDR. The transport personality already
   establishes this from the connection; the explicit check is defence in depth.
2. **Request signature** — Ed25519 over the canonical request bytes
   (`shared/sparknet-http.py::request_message`), signed by the caller's **node
   identity** key.
3. **Registry** — the signing fingerprint is present in the signed registry, not
   revoked, not expired. Checked *before* signature validity so a tampered
   registry fails closed.
4. **Capability** — the registry entry holds `cluster-dispatch` **or**
   `cluster-serve`. No new capability is added to the closed vocabulary: the
   initiator holds `cluster-dispatch` and needs to resolve `context_refs` to build
   its job; the participant holds `cluster-serve` and needs the same resolution to
   answer. One gate, two legitimate callers, zero vocabulary change.
5. **Shape** — `query` non-empty, `top_k` a positive integer ≤ 20.
6. **Stamp and dependency** — collection stamp matches and chromadb is present,
   else 503.

### F7 — ingestion

v1 ships an **explicit action**, not a timer: `make -C master-node
vector-reindex`, wrapping `sparknet-chroma.py` with `CHROMA_SCOPE=fabric`.
Upsert is idempotent, so re-running is free and a partial run is not a hazard.

**"Idempotent" is only true if the index is made *equal* to the corpus.** An
upsert writes the ids that are in the corpus; it does not remove the ids that
have *left* it. A passage that was shortened or deleted leaves its old chunks
behind, and the corpus digest still matches — it hashes what was written, not
what is stored — so the index would serve text the corpus no longer contains
while claiming to be exactly it. The substrate therefore deletes the stale ids
too, and the count follows the corpus.

**An index this build cannot account for is rebuilt, not served.** The on-disk
format belongs to the chromadb that wrote it, so a library change can leave an
index unreadable (0.6.3 reads a 1.5.9 collection as an unknown segment type,
not as an error message). The version that wrote the index is recorded next to
it, and an index whose marker is missing or names another version is discarded
and written again — before any client opens the directory, because chroma
caches its storage system per path and a cached system hands back the state
that was just deleted.

The systemd timer is a **separate, named increment** — deliberately not bundled
into the first build step, because Master `units-check`
(`master-node/Makefile:141`) loops only `*.service`, so a `.timer` would require
extending that target in the same commit. The peer's
`peer-node/systemd/sparknet-sync.timer` is the precedent when it lands.

Reindex-triggered-by-git (port `4220`) stays deferred and is named as such.

### F8 — failure semantics, and the invariant that changes answers

Master unreachable, chromadb absent, stamp mismatch, index empty: **503, never an
empty result set.** And one step further, which is the invariant worth stating in
the code as well as the doc:

> A cluster job whose `context.source` is `master_vector_db` that cannot obtain
> its context is **refused at dispatch**, not run without context.

Silence is an answer and the fabric's stated rule
(`contracts/capabilities.json` `share_clocks.silence_is_an_answer`). Silently
degrading a grounded answer into an ungrounded one is not an answer — it is a
different question being answered, without telling anyone. Without this line, a
vector-store outage changes what every cluster job in the fabric is grounded on
while every job still reports success.

### F9 — ownership

`master-node/services/sparknet-vector-serve.py` plus
`master-node/systemd/sparknet-master-vector.service`, wired into
`master-node/Makefile`'s `UNITS`. The chunking and id logic is **imported from
`scripts/sparknet-chroma.py`**, never copied — following the pattern
`master-node/services/sparknet-ledger.py:37` already uses to load
`shared/sparknet-authz.py` by path. Two copies of a deterministic chunker would
drift, and a drifted chunker means a `context_refs` id that resolves to the wrong
text on the next index — silent and undetectable from either side.

The service holds no key and cannot reach the signer. That boundary is structural
and identical to the admin surface's
(`master-node/plans/MASTER_ADMIN_PLAN.md`, "No key adjacency").

### F10 — where the build step is filed

`master-node/plans/MASTER_ADMIN_PLAN.md`, as its first numbered step. Two things
in the tree already say so: the `4223` status string in `contracts/ports.json`,
and the responsibility table in
`master-node/docs/master-control-plane.md:61`. `tests/test_contracts.py` accepts
that file as a valid plan pointer for a non-implemented port, so nothing has to
change for the design step itself.

## Adoption increments

Each is its own step and its own commit, with `make contract-test` green between
them. The order is the dependency chain, not the section order above.

1. **Envelope conformance (Seam A).** Shared golden vectors for
   `cluster_job_message`; goSpark's proto and `Canonicalise` brought to the fabric
   encoding (`created_at`/`expires_at` ISO-8601, the four formerly-`omitempty`
   fields always projected); shape validation added to `cluster_job_message`; the
   signer's `_job()` fixture rewritten to the canonical shape. Nothing about this
   increment can be skipped — every later increment builds on bytes whose meaning
   must already be agreed.
2. **The Master vector DB (Seam F).** The 4223 service, the allow-list corpus, the
   stamp check, the `make vector-reindex` target, and the test proving no
   excluded path reaches the index. Build step filed in
   `master-node/plans/MASTER_ADMIN_PLAN.md`; `contracts/ports.json` flips
   `4223` to `provisioned` and `make render` regenerates the manifest in the same
   commit.
   **Substrate half taken (2026-10-22, PLAN Step 63):** the bounded pin, the
   explicit embedder, the stamp and its refusal, the allow-list corpus and the
   proof test are implemented in `scripts/sparknet-chroma.py` and
   `scripts/sparknet-rag-corpus.py`. The 4223 service itself, the registry
   check and the `provisioned` flip are **not** part of that step — `4223`
   stays `spec-only` and no port changes.
3. **Task ingress (Seam E).** The loopback `submit`/`status`/`result` routes on
   the dispatch bridge, the acceptance checks, and `--execute-enabled` off by
   default.
4. **Job construction and placement (Seams B, C).** The deterministic
   construction function, the Master-dispatched topology at `master_governed`, and
   the honest `peer_pair` statement.
5. **Reduce (Seam D).** Signature verification before merge, the contribution
   map, and the explicit incompleteness marker.
6. **Reindex timer.** The `.timer`, with `units-check` extended to cover it.
7. **Peer-to-peer fan-out at n ≥ 3 (D2).** The time-boxed, job-scoped data-plane
   stanza. A real `contracts/overlay.json` change and a matching nftables change
   in both roles — deliberately last, deliberately separate, and deliberately not
   implied by anything above.
8. **Live deploy.** `make test-all`, `lint`, `contract-test`, `validate`,
   `keys-check`, `shims-check` green; deployment is `DoD: confirm: user`.

## Options considered and rejected

| Option | Verdict | Reason |
|---|---|---|
| Milvus or Qdrant as the v1 store | **rejected for v1** | 242 chunks in the allow-listed corpus (1,699 under the old deny-list). The infrastructure dwarfs the data. Designated as the upgrade path with the numeric trigger in F2 rather than dismissed. |
| Sharding + replication + etcd for availability | **rejected** | Two hosts, replication factor two, tolerates no failure. And a second consensus domain alongside `sparknet-consensus.py` creates two membership truths. |
| pgvector | **rejected** | Buys a new daemon and a backup story to save a process the tree does not have. |
| Bind the `chromadb` server on 4223 | **rejected** | No registry check, no capability gate, API-key auth — the wrong authority model for this fabric. |
| Accept caller-supplied query vectors | **rejected** | The wire cannot check which model produced a vector. A mismatched model returns healthy-looking nonsense. |
| Project timestamps as `int64` (the goSpark encoding) | **rejected** | The fabric's `is_expired()` and the registry already share one ISO-8601 parser. Two time formats means two notions of expired. |
| Drop optional fields with `omitempty` | **rejected** | Removing a field from the signed bytes means a verifier that re-serialises produces different bytes and the signature fails. A projected `null` is stable. |
| Widen peer egress to `10.100.0.0/24` permanently | **rejected** | Hands every peer a permanent authority-plane edge to every other peer. Exactly what the broadcast rejection exists to prevent. |
| Relay every subtask through the Master at n = 2 | **rejected** | At `peer_pair` the initiator is already a worker; adding a relay makes the Master a required hop for a two-node job it has no role in. |
| Timer in the same step as the service | **rejected** | Master `units-check` loops only `*.service`; bundling forces an unrelated target change into the build commit. |
| Copy the chunker into `master-node/services/` | **rejected** | A second copy drifts, and a drifted chunker makes `context_refs` resolve to the wrong text with nothing to notice. |
| Run the cluster corpus as a deny-list, matching the script today | **rejected** | A corpus served to every `cluster-serve` node must default to *out*, not default to *in*. |

## Provenance and consistency

Grounded in `CLUSTER_INFERENCE_DESIGN.md` (envelopes, modes, reduce semantics,
security boundaries, the tensor-parallelism rejection at its line 382),
`COMPUTE_CAPABILITY_DESIGN.md` (the verification-order discipline, the
`--execute-enabled` inert-until-armed pattern), `shared/sparknet-authz.py`
(`CLUSTER_JOB_FIELDS`, `CLUSTER_JOB_REQUIRED`, `cluster_job_message`,
`is_expired`), `master-node/services/sparknet-signer.py` (`sign-cluster-job`),
`master-node/tests/test_signer_isolation.py` (the divergent fixture),
`tests/test_authz_golden.py` (the golden-vector precedent this note asks to
extend), `contracts/overlay.json` (the peer `AllowedIPs` single-`/32` rule and
`governance_mode`), `contracts/ports.json` (`4223 vector-embed`, spec-only),
`scripts/sparknet-chroma.py` (the substrate, its pure chunking and its
deny-list), `scripts/sparknet-rag-corpus.py` (the allow-list rule),
`shared/sparknet-http.py` (`serve()`, `source_kind()`, `loopback_only_routes`),
`peer-node/services/sparknet-dispatch-bridge.py` (the loopback route surface),
`peer-node/configs/ai-stack/docker-compose.yml` and its README (the out-of-repo
`~/infra` boundary for `11434`/`18000`),
`master-node/plans/MASTER_ADMIN_PLAN.md` (where `4223` is scoped),
`master-node/docs/master-control-plane.md` (the responsibility table), and
`tests/test_contracts.py` / `tests/test_layout.py` (the invariants a new
fabric-root design document must satisfy).

The measured figures this note leans on were taken on the development host on
2026-10-22: the allow-listed `fabric` corpus is **28 markdown files, 381 KiB,
242 chunks** at the 2000-char default (`make chroma-inspect CHROMA_SCOPE=fabric`
prints the count and the corpus digest); under the pre-2026-10-22 whole-tree
deny-list it was 138 files and 1,699 chunks, 64% of them personal or runtime
pages. No Milvus, Qdrant, pgvector, Kubernetes or k3s appears as a dependency or
a configured service in any tracked Python, YAML, JSON, Markdown or TOML file.

Nothing here binds `contracts/` until an increment above adopts it, in its own
commit, with both roles edited together and `make contract-test` green.
