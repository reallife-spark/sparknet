# 0006 — Stage the provenance split along lifecycle seams

## Status

Superseded by [0007](0007-complete-the-provenance-lifecycle-split.md). Stage 1 was accepted 2026-11-09.

## Context

`shared/sparknet-provenance.py` is the one implementation of the accountability
chain: notes and the user record, the ledger and checkpoints, grant-scoped
writes, and secret scanning. It is 2,848 lines with 90 top-level definitions and
70 names reached through the facade by role code and tests. The section comments
already name the lifecycle seams, but every change loads the whole module and
tests cannot choose a narrower surface.

The architecture review marked the full split **Speculative**: the seams are
real, but the canonical note message, ledger block bytes and grant verification
order must not move during a release, and `ProvenanceError` identity is
load-bearing for every handler. A full move in one change would mix a
security-critical refactor with the open 91H/goagx release work.

Two pieces are independent enough to move first:

- the loader, YAML re-exports, canonical form, crypto loaders, contract reader,
  time/key-path helpers and shared key-shaped patterns;
- the secret scanner, whose only dependency is the shared state-dir helper and
  the patterns.

## Decision

Stage 1 extracts two modules behind the unchanged facade:

- `shared/sparknet-provenance-base.py` — primitives only: loader shim,
  `ProvenanceError`/`FrontmatterError` re-exports, canonical JSON and hashes,
  authz/merkle/abac loaders, `contract()`, time and key-path helpers, and
  `_PATTERNS`.
- `shared/sparknet-provenance-scan.py` — secret-index constants,
  `_SCAN_EXEMPT`, tracked-file/ref helpers and `scan()`. It loads only `base`.
- `shared/sparknet-provenance.py` — keeps the same path, CLI and every
  caller-visible name. It loads the two modules under stable names and
  re-exports their explicit interfaces. Note, ledger and grant remain here
  until Stage 2.

`build_inbox_acceptance` and vault-wide verification are intended for the
ledger module when Stage 2 happens; they are not moved in Stage 1.

## Consequences

- The scanner and the canonical/crypto primitives now have one home each; the
  facade cannot drift from them because it re-exports the same objects.
- Callers and role repositories do not change; there are no submodule pins.
- `ProvenanceError` remains the single class from `sparknet-yaml.py`.
- The facade is still wide (the 70-name compatibility surface) and still holds
  the note/ledger/grant implementation. Stage 1 proves the loader, error and
  facade pattern; it does not realize the full locality win.
- The secret scanner must exempt the primitives and scanner sources, because
  the pattern definitions otherwise match their own source.
- Stage 2 — note, then ledger, then grant — needs its own decision and test
  migration. It must not move canonical bytes or the grant verification order.

## Supersession

A later ADR may complete Stage 2 and mark this one superseded; do not rewrite
this record.
