# 0017 — Defer live vLLM KV capture until a pinned connector exists

## Status

Accepted (2026-11-12).

## Context

`scripts/sparknet-kv-export.py --from-vllm` deliberately refuses today. No
version-pinned vLLM connector has been exercised on the live engine, and a
KV export that does not reproduce the engine's actual cache layout would be a
fake artifact. The file-based `--from-file` path accepts a real engine export
and remains useful for archival.

The design also separates the signals: teacher traces and logprobs are the
distillation input; raw KV artifacts are backup/architecture-compatibility
evidence, not a substitute for traces.

## Decision

Keep `--from-vllm` refused. Do not implement a guessed connector.

Live KV capture is a backlog item with these preconditions:

- a named vLLM version and connector API that can be pinned;
- a bounded, reproducible export with a manifest and digest;
- a test that proves the capture fails closed when the engine/version does not
  match;
- a live target-host observation on `agx64`.

The existing `--from-file` path stays the supported way to package a real
engine export.

## Consequences

- The CLI tells the truth: no live capture is claimed and no fake artifact can
  enter uplift.
- Distillation continues on traces; KV capture is deferred rather than
  half-built.
- Supersede this ADR when a pinned connector has been exercised and the
  manifest format is fixed.
