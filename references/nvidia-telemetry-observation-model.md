---
title: nv-telemetry observation model — mapped onto goSpark telemetry
updated: 2026-10-17
tags: [reference, telemetry, observation-model, nvidia, adoption]
source: dsx-ai-factory/nv-telemetry @ f947b61892694c4aafa48d0b2a045477dccaa150 (Apache-2.0)
---

# nv-telemetry observation model → goSpark

Step 51(c) of `PLAN.md`: a design doc mapping NVIDIA's telemetry **model**
(`model/`, `schema/proto/nv/telemetry/v1/*.proto`) and its Prometheus/OTLP
exporters onto goSpark's telemetry types (`internal/telemetry`,
`internal/gputel`, `internal/metrics`). Read-only study; no code copied.

## The reference model

`nv-telemetry` is a Rust workspace whose `model/` crate is the interesting part;
`exporters/{prometheus,otlp}` are deliberately thin — their own docs say the
mapping "occurs only at this boundary", so the model is exporter-agnostic.

The invariants worth naming:

1. **Reading vs batch.** `reading.proto` defines a `Reading` (one sample:
   signal reference + value + time) and `Readings` (a batch). The **unit and
   bounds live on the batch's `SignalDescriptor`**, declared once per signal,
   not repeated on every sample.
2. **A union value type.** `model/src/value.rs` models the value as a tagged
   `Value` (`ValueKind`: null/bool/int/uint/double/string/bytes/timestamp/
   list/map) with a `Timestamp{seconds,nanos}`. Anything a source can express
   has a faithful slot.
3. **Finiteness is enforced at construction.** `model/src/finite.rs` wraps f64
   so a `NaN`/`Inf` cannot become a sample; the constructor returns `None`.
4. **Structured validation errors.** `model/src/invalid.rs` carries a `path`
   and a `Violation`, so a rejected batch says *where* and *why*, not just
   "invalid".
5. **No answer is not a zero** (from the source adapters): "a sensor that did
   not answer produces nothing — never a zero."
6. **Sources are adapters, not the model.** `sources/gnmi`, `sources/redfish`
   feed the same `Reading`; `exporters/{prometheus,otlp}` serialize it at the
   edge.

## Mapping onto goSpark

| nv-telemetry concept | goSpark equivalent | Gap |
|---|---|---|
| `Reading` (signal key + value + time) | `apiv1.GpuMetrics` + `CollectedAtUnix` | one timestamp for the whole snapshot, not per signal |
| `Readings` batch + `SignalDescriptor` (units/bounds once) | `gputel.Snapshot` + `metrics.Write` `# HELP`/`# TYPE` header | units are name suffixes (`_bytes`, `_celsius`), declared per series not per batch |
| `Value` union | Go `uint32`/`uint64`/`string` fields, `omitempty` | narrower, but total for our sources |
| `Finite` (reject NaN/Inf) | integer fields + `/1000.0` conversions | no float path today, so not yet reachable |
| `invalid.rs` path+violation | `Snapshot.Reason` (one string) | no structured per-field error |
| "no answer produces nothing" | `Snapshot.Available=false` + `Reason`, `omitempty`, `> 0` guards | **already implemented** |
| `sources/*` adapters | `gputel` NVML/DCGM subpackage `init` registration | equivalent |
| `exporters/*` at the boundary | `Snapshot.Wire()` (wire JSON) + `metrics.Write` (text) | mapping already lives at the two boundaries |

The three nv-telemetry principles that map cleanly and are **already satisfied**
are: absent-not-zero (invariant 5), boundary-only serialization (invariant 6),
and one mapping site per boundary. The two clean ideas goSpark does **not** have
are batch-level descriptors (invariant 1) and structured validation errors
(invariant 4).

## Decision lines

- **Adopt batch-level descriptor discipline as documentation, not code.** The
  Prometheus `# HELP`/`# TYPE` block already declares units and types once per
  scrape, which is the same idea in Prometheus's own idiom. No code change;
  recorded so the resemblance is deliberate rather than accidental.
- **Adopt structured validation errors where goSpark validates untrusted
  input** — specifically config/registration parsing, which today fails with a
  bare error. nv-telemetry's `path` + `Violation` shape is the model to copy.
  This is a **follow-up** (own test), not part of this arc.
- **Do not adopt the `Value` union or a float path.** Every goSpark telemetry
  source is integral (bytes, percent, MHz, mW, Celsius); a union type would add
  surface with no source to fill it. Revisit only if a genuinely scalar source
  (a real-valued counter) is added.

## Related

- `nvidia-fleet-telemetry-comparison.md` — leg (b), the agent-level comparison.
- `../contracts/health-protocol.md` — the fabric's own health-report contract.
- `../PLAN.md` — Step 51(c).
