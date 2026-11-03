---
title: sparknet vector store — Qdrant substrate, uplift and distillation
role: both
updated: 2026-11-01
---

# Vector store

Qdrant replaces ChromaDB as the fabric's vector store. This contract is the
single source of truth for the store's shape; the implementation is
`scripts/sparknet-vector.py` (loaded by path by `master-node/services/sparknet-vector-serve.py`)
and the node AI stack.

## Topology

- One Qdrant server per node, image pinned to `qdrant/qdrant:v1.20.0` unless a
  step records a deliberate upgrade.
- The server binds node loopback only: `127.0.0.1:6333` (HTTP) and
  `127.0.0.1:6334` (gRPC). It is never published on the LAN or the overlay.
- The only fabric-facing vector surface is the Master's signed `4223`
  listener. A peer does not expose Qdrant to another node.
- Persistent storage is the node's state directory, mode `0700`, never a vault
  and never a bundle. Snapshots are derived state; the vault is the source of
  truth for vault scopes.
- The API key is generated at deploy, stored `0600` under the node state
  directory, and passed to Open WebUI and the local CLI by environment only.

## Collections

| Collection | Writer | Served by 4223 | Content |
|---|---|---|---|
| `sparknet-peer` | peer | no | that node's own vault, its own business |
| `sparknet-master` | master | no | the Master's own vault |
| `sparknet-fabric` | master | yes | the structural allow-list from `scripts/sparknet-rag-corpus.py` |
| `sparknet-shared` | master | yes | only `01_Inbox/share-*` markdown payloads |
| `sparknet-meta` | both | no | the per-scope stamp |
| `sparknet-memory` | both | no | optional per-vault memory vectors; payload filters carry `vault_id`, user/project scope and memory type |
| `sparknet-inventory` | both | no | users, models and usage counters |
| `sparknet-traces` | both | no | local teacher-trace metadata; full text lives in a content-addressed blob |
| `sparknet-kv` | both | no | raw-KV artifact manifests; tensors live in the artifact store |
| `uplift-*` | master | no | the Master's mirror of consented uplift data |

`4223` serves exactly `sparknet-fabric` and `sparknet-shared`. A query naming
any other collection is refused with `400 unknown-collection`. Uplift,
inventory, trace and KV collections are training/backup data, never an answer
corpus (`contracts/knowledge-flow.md` invariant 10).

## Embedding and the stamp

- Default embedder: `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions,
  through Qdrant's FastEmbed extra. The same model must be used at index and
  query time.
- `SPARKNET_EMBED_URL` selects an HTTP OpenAI-compatible embeddings endpoint
  instead; `SPARKNET_EMBED_BACKEND=hash` is a deterministic offline test
  backend and is named in the stamp so it cannot be mistaken for a semantic
  index.
- The stamp is a point in `sparknet-meta` keyed by scope. It records:
  `embedding_model`, `embedding_sha256`, `embedding_backend`, `embedding_dim`,
  `corpus_digest`, `qdrant_version`.
- `embedding_model`, `embedding_sha256`, `embedding_dim` and `corpus_digest`
  are refusals. A mismatch refuses with exit 3 in the CLI and 503 on `4223`;
  it never returns an empty result set. `embedding_backend` and
  `qdrant_version` are reported, not enforced.
- An index is made *equal* to the corpus: points whose `doc_id` is no longer
  in the plan are deleted. Re-running `index` is idempotent.

## Scores

Qdrant returns cosine similarity (higher is better). The substrate converts it
to the fabric's distance convention (`distance = 1 - score`) before the reflex
reranker or `4223` sees it, so a caller's ordering contract does not change.

## Parity with the retired Chroma implementation

| Chroma function | Qdrant replacement | Test |
|---|---|---|
| lazy optional import; `inspect` without a store | lazy `qdrant_client`; pure plan | `tests/test_vector.py` |
| scopes `peer/master/fabric/shared` | same scope resolution, collection names | `tests/test_vector.py` |
| deterministic chunking and stable ids | same chunker; UUIDv5 point ids | `tests/test_vector.py` |
| idempotent upsert and stale removal | upsert then delete absent `doc_id` | `tests/test_vector.py` |
| stamp and stale refusal | `sparknet-meta`; exit 3 / 503 | `tests/test_vector.py`, `master-node/tests/test_vector_serve.py` |
| text query and distance order | FastEmbed + `query_points`; score→distance | `tests/test_vector.py` |
| `/doc/{id}` | payload `doc_id` and retrieve | `master-node/tests/test_vector_serve.py` |
| reflex shadow/assist | unchanged pure reranker | `tests/test_reflex_rag.py` |
| shared scope from `01_Inbox/share-*` | same policy function | `tests/test_vector_corpus.py` |
| fabric allow-list | same `sparknet-rag-corpus.py` policy | `tests/test_vector_corpus.py` |
| Open WebUI structure/per-user RAG | Qdrant server + admin reindex | live migration `DoD: confirm: user` |

`make vector-parity` runs the local suites. The live Chroma→Qdrant migration is
a dated node observation, not a development-host claim.

## Uplift and distillation

- Full vectors, inventory, teacher traces and raw-KV artifacts move to the
  Master only with the peer-held `model-uplift` capability and explicit consent.
- The Master stores them under its uplift store, indexes metadata in
  `uplift-*` collections, and never serves those collections on `4223`.
- Distillation uses teacher traces and logprobs. Raw KV artifacts are archived
  and used only where the student architecture is compatible; they are not a
  substitute for traces.
- Retention: snapshots/traces 30 days, KV 7 days unless pinned to a run,
  datasets 180 days. A user deletion request purges within 30 days. Retired
  Chroma volumes are retained for 14 days after Qdrant verification.

## Failure semantics

Master unreachable, Qdrant unreachable, missing collection, stamp mismatch or
an empty index: refuse. `4223` returns 503 and the CLI exits 3. Silence is not
an empty answer.
