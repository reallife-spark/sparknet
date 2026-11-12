# 0018 — Keep a GPU-backed embedder behind the vllm-embed profile

## Status

Accepted (2026-11-12).

## Context

The vector store's index-time and query-time embedder must be the same model.
The current default is `sentence-transformers/all-MiniLM-L6-v2` through
FastEmbed, with an explicit embedding stamp. A GPU-backed embedder is named in
the design as a future upgrade behind the existing `vllm-embed` profile
(port 8001), but no model/version decision or reindex path exists.

Adding a second backend now would create a mixed-model index that returns
plausible but meaningless distances.

## Decision

No new embedder backend in this pass. The only future GPU path is the existing
`vllm-embed` profile; a model switch must:

- pin the model and its digest in the embedding stamp;
- rebuild the collection with the same model at index and query time;
- refuse a stamp mismatch with 503 / exit 3, never an empty result;
- be recorded in a new ADR and a fresh benchmark.

FastEmbed remains the default, and the explicit embedder stays passed on every
open.

## Consequences

- Current indexes remain comparable and refuse a model mismatch.
- GPU embedding is a deliberate future change, not an accidental second path.
- The backlog ticket carries the model choice, benchmark and reindex work.
