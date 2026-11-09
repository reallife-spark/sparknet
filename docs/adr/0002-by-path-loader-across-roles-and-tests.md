# 0002 — One by-path loader across roles and tests

## Status

Accepted (2026-11-09).

## Context

The fabric's shared modules are hyphenated files loaded by path, so a role
cannot quietly import a private copy. That rule protected exactly one authz,
one transport and one consensus implementation, but it stopped at `shared/`:
role services, root scripts and tests each carried their own
`spec_from_file_location` resolve-and-cache loop. The copies drifted — one
checked a required sibling, one returned `None`, one used a different search
order — and a fix to the loader did not reach them.

A normal import package would remove the by-path loader, but it would also
remove the structural proof that there is one implementation: a role could
then import a copy from its own environment. The package rename is a larger
decision with bundle and goagx consequences, and it is not needed to fix the
drift.

## Decision

Keep `shared/sparknet_loader.py` as the one loader and adopt it everywhere:

- production modules use a pinned path shim to import the loader, then call
  `load_shared` (shared files) or `load_by_path` (role files);
- tests put `shared/` on `sys.path` once in their conftest and call the loader;
- `load_shared` gains `required` (a sibling dependency must exist) and
  `missing_ok` (an optional surface may be absent) so callers do not
  reimplement those decisions;
- a guardrail test fails on any new `spec_from_file_location` outside
  `shared/sparknet_loader.py` and on an embedded loader in a shell snippet.

The hyphenated filenames and the one-implementation rule stay unchanged. A
future package layout is a superseding ADR, not a silent switch.

## Consequences

- The repeated code is a two-line path shim, not a loader implementation.
- A missing shared file refuses at one seam, with the caller's error type.
- The guardrail keeps the convention from eroding again.
- Tests share the same loader interface as production; they no longer prove
  the loader by copying it.
