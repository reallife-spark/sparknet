# 0011 — Understand core: schema, production, algebra, facade

## Status

Accepted (fabric Step 92D; implemented 93D).

## Context

`shared/sparknet_understand/core.py` is 826 lines. It mixes contract
vocabulary, IDs and constructors, scan policy, project metadata and graph
algebra. `build.py` is already a small orchestration seam, and `__init__.py`
already re-exports package-level entries.

ADR-0018 settled that Python is the sole graph producer and Go is the graph
consumer. This decision is internal locality: narrow the producer's wide core
without changing its external interface.

Three module maps were compared:

- A minimal map with a schema module and one broad graph module.
- A flexible map splitting scan, project metadata, algebra, graph kinds and
  output.
- A common-caller map with schema, production, algebra and a facade.

The minimal map mixed scan policy with graph algebra. The flexible map created
`kinds` and `io` seams with one adapter each, which is a hypothetical seam. The
common-caller map kept the real seams and the existing facade.

## Decision

- **Four modules:**
  - `schema.py` — contract loading, vocabulary, canonicalization, IDs and
    `make_node`/`make_edge`.
  - `production.py` — scan policy, `FileRecord`/`ScanResult`, project metadata
    and framework detection.
  - `algebra.py` — normalize, merge, validate, diff, layers, tour and graph
    output helpers.
  - `core.py` — path-stable facade re-exporting the existing public symbols.
- **`build.py` remains the orchestration seam.** It imports production and
  algebra; it does not absorb scan or merge logic.
- **Internal callers import the narrow module they need.** Extractors use
  `schema`; domain uses `production`; CLI uses `production` and `algebra`.
  External callers and tests keep the `core`/package facade.
- **`core.py` holds no new logic.** It keeps path stability; the implementation
  lives behind the three modules.
- **No `kinds` or `io` module now.** One graph-kind adapter and one output
  helper do not justify a seam until a second real variation appears.
- **Tests:** keep `tests/test_understand.py` as the integration/golden proof; add
  focused schema, production and algebra tests using one shared fixture.

## Consequences

- The producer's interface narrows for maintainers while the path-stable facade
  keeps callers stable.
- Scan policy and graph algebra stop sharing a file and a revision history.
- Future graph kinds or output formats need a second real adapter before a new
  seam is introduced.
- The Python producer decision in ADR-0018 is unchanged; this is how that
  producer is organised internally.
- A future move to a separate `production` package for another runtime is a new
  decision, not a quiet extension of this split.
