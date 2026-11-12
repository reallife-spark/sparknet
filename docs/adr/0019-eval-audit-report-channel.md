# 0019 — Peer eval records reach the Master as a signed audit report

## Status

Accepted (2026-11-12). Implementation is a separate change; this ADR records
the channel decision only.

## Context

The Master's `/api/evals` reads skill-eval records from its own delegate runs.
A peer's records stay in the peer's Go delegate store. The Master cannot see
them, and mirroring them into a vault, KB, corpus or RFI answer would turn audit
evidence into knowledge.

The existing 8090 peer intake already carries signed, overlay-attributed
evidence (telemetry, RFI requests, issues). The issue report is the closest
pattern: a signed peer→Master work item stored append-only and read by a
read-only surface.

## Decision

Use a **signed peer→Master audit report on the existing 8090 intake**, stored in
a Master audit sink and read by `/api/evals`.

- Authentication: the peer node key signs the raw report body; the Master
  verifies it, attributes the overlay source through the signed registry and
  requires the peer-held `telemetry` capability.
- Payload: a bounded set of valid `sparknet-skill-eval/1` records, each
  digest-checked with `shared/sparknet-skill-eval.py`. Invalid records stay
  visible/counted as invalid; they are never promoted.
- Store: append-only Master audit evidence (for example
  `/mnt/log/sparknet-evals.jsonl`), no vault write, no Qdrant answer collection.
- Console: the Master's `/api/evals` reads the sink in addition to its own
  delegate runs. A peer record is labelled by node and never becomes a local
  verdict.
- No new knowledge-flow row: this is audit evidence, not knowledge and not
  authority. The channel is named in `contracts/knowledge-flow.md` only if the
  implementation adds a distinct route; otherwise it stays a telemetry-family
  audit route.

## Consequences

- A peer eval is tamper-evident and auditable without giving the Master a vault
  read or a memory mirror.
- A failed or tampered record is visible as invalid, never silently dropped and
  never treated as a pass.
- The implementation needs a route, a bounded store, a pusher and tests; it is
  tracked by `peer-eval-audit-transport`.
- This ADR does not grant, widen or approve anything.

## Alternatives

- **Unsigned telemetry section:** simpler, but loses the tamper evidence the
  audit use case needs.
- **Signed read-through of the peer delegate store:** gives the Master a live
  read path and a second query surface; rejected as a larger authority-shaped
  change.
