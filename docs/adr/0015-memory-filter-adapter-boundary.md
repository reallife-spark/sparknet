# 0015 — The memory filter is a WebUI adapter, not fabric runtime

## Status

Accepted (2026-11-11). Decision record; no behavior change.

## Context

`shared/sparknet-memory-filter.py` is an Open WebUI Filter Function: it adds
scoped recall in `inlet` and captures the turn in `outlet` through the loopback
memory gateway. It imports `httpx` and `pydantic` at module scope because it
executes inside the WebUI process, where both are guaranteed.

The fabric's runtime allow-list is the standard library plus `cryptography`
(`pyproject.toml`, `tests/test_services.py`), so the filter looks like a
violation unless its boundary is stated. `webui/functions/sparknet_memory_filter.py`
is already a symlink to the shared file, so there is one physical
implementation and no copy to drift.

Two other imports sit near the same boundary. `cryptography` is the declared
runtime dependency and may be loaded at module scope or function-locally. The
optional Understand extractor imports `tree_sitter_language_pack` inside a
function; it is the opt-in `[understand]` extra and is never required to import
the graph core.

## Decision

- The memory filter is an **adapter**, not a shared runtime module. An installer
  may read and post its bytes; no role service and no other shared module may
  import or name it.
- `httpx` and `pydantic` stay off the runtime allow-list. The boundary guard
  permits them at module scope only in `shared/sparknet-memory-filter.py`.
- `webui/functions/sparknet_memory_filter.py` stays a symlink to the shared
  file. A byte-identical copy is forbidden: the last one was already a symlink,
  and a copy would be the first step toward drift.
- Optional extras (`tree_sitter_language_pack`) may be imported only
  function-locally and only inside `shared/sparknet_understand/`.
- The guard is `tests/test_dependency_boundary.py`; the unit tier and the
  pre-merge gate run it.

## Consequences

- A node without Open WebUI never needs `httpx` or `pydantic`; a WebUI node
  supplies them in-process.
- A new third-party import under `shared/` fails a named test unless this
  decision is amended in the same change.
- The physical file stays under `shared/` because role bundles ship `shared/`,
  not `webui/`; the WebUI-facing name is a link, not a second source.
