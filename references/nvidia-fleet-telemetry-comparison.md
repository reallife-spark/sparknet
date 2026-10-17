---
title: fleet-intelligence-agent vs goSpark telemetry — comparison and one adopted mechanism
updated: 2026-10-17
tags: [reference, telemetry, gpu, nvidia, adoption]
source: dsx-ai-factory/fleet-intelligence-agent @ 6eace17c3c19adf1524ba71c9cbd0450266a61f1 (Apache-2.0)
---

# fleet-intelligence-agent vs goSpark telemetry

Step 51(b) of `PLAN.md`: compare NVIDIA's fleet telemetry agent against
goSpark's `internal/gputel` + `internal/metrics` surfaces, and adopt exactly
one mechanism — with the reason written down. Read-only study; no code copied.

## What the reference actually does

`fleet-intelligence-agent` is a Go agent that collects host/GPU health and
emits it through a **fleet-intel OTel Collector** built with the OpenTelemetry
Collector Builder (`otelcol/otelcol-builder.yaml`):

- One receiver (`otlp`), two processors (`memorylimiter`, `batch`), one
  exporter (`otlp_http/backend`); a local `sakauth` extension provides
  attested auth. The gateway config is the standard
  `otlp → memory_limiter → batch → otlp_http/backend` fan-in.
- Collection is component-scoped: a `components.Registry` of `Component`s each
  exposing `Name()` and a health verdict; the DCGM component carries the large
  `dcgm_fi_*` counter vocabulary (ECC, remapped rows, clocks, power, temps).
- `internal/exporter/converter/otlp.go` maps a `HealthData` struct to OTLP
  metrics. The shape that matters here is the **info-metric convention**:

  - `fleetint_agent_up` — a gauge that says *the collector itself ran*.
  - `fleetint_agent_collection_summary{metrics_count=…}` — an operational
    gauge summarising the scrape.
  - `fleetint_node_software_info{driver=…,cuda=…,kernel=…} = 1`,
    `fleetint_gpu_firmware_info{uuid=…,serial=…,vbios=…} = 1` — identity and
    version facts carried as labels on a **constant `1` gauge**, name suffixed
    `_info`.

## What goSpark already has

`internal/gputel` is the node-side collector: a dependency-free
`Collector` interface over a `Snapshot{Source, Available, Reason, DriverVersion,
GPUs[], Health[], CollectedAtUnix}`, with `Null`/`Multi` fallbacks and NVML/DCGM
cgo backends registered by subpackage `init`. `Snapshot.Wire()` projects onto
`apiv1.GpuTelemetry` in one place. `internal/metrics` renders a hand-rolled
Prometheus 0.0.4 surface (`gospark_*`), including an info metric
(`gospark_build_info`), an availability gauge (`gospark_node_gpu_available`),
and per-device numeric gauges whose labels already carry `node`/`gpu`/`name`.

## The comparison

| Axis | fleet-intelligence-agent | goSpark today | Verdict |
|---|---|---|---|
| Transport | OTLP via an otelcol gateway | hand-rolled Prometheus text + JSON wire | keep ours; no gateway needed at this scale |
| Availability | `fleetint_agent_up` gauge | `gospark_draining` + `gospark_node_gpu_available` | **equivalent — nothing to adopt** |
| Absent ≠ zero | absent metric omitted | `omitempty` + `> 0` guards + `Available`/`Reason` | **already stricter than the reference** |
| Unit discipline | OTLP `Unit` (UCUM) | name suffixes `_bytes`/`_celsius`/`_watts`/`_percent` | equivalent |
| Identity/version data | `_info` gauge = 1, labels | `gospark_build_info`; GPU `name` sits on the numeric gauges | **gap: one adopted mechanism** |
| Collection summary | `fleetint_agent_collection_summary` | none | optional, skip |
| DCGM vocabulary | full `dcgm_fi_*` set | `Health{Status,Watches}` only | out of scope (no DCGM here) |

## The one adopted mechanism

**The `_info` info-metric convention**: static identity/version facts are
published as a gauge with the constant value `1` and the facts as labels, never
as numeric gauges with identity baked into their labels.

*Why this one and not the others.* Availability, absent-vs-zero and unit
discipline are already at parity or better in goSpark, so adopting them would
be churn. The info-metric convention is the one real asymmetry: today a GPU's
`name` repeats on every numeric sample and a driver/CUDA/kernel version has no
home at all outside the JSON wire. Splitting identity out means numeric gauges
change only when a *measurement* changes, and inventory facts become one
constant series each — which is exactly what makes them joinable and cheap to
scrape.

*Shape if landed (purely additive — no existing series renamed).*

- `gospark_gpu_info{node,gpu,name,uuid} 1`
- `gospark_node_software_info{driver=…} 1` (from `Snapshot.DriverVersion`)

**Decision: adopt the `_info` convention.** It is additive (no renumbering of
the existing `/metrics` contract), it fills the one genuine gap the comparison
found, and it needs a small plumbing change (`DriverVersion`/`UUID` into the
`metrics.Node`/`Device` snapshot). Landing it is a **follow-up**, not part of
this arc — Step 51's DoD accepts a written comparison plus the adopted
mechanism for leg (b), and the metric-surface change is better made once, with
its own test update, than bolted onto the adoption sweep. The decision and the
exact metric names are recorded here so the follow-up is mechanical.

## Related

- `nvidia-dsx-standard-practice.md` — the inventory this page's verdict feeds.
- `nvidia-telemetry-observation-model.md` — leg (c), the model-level design.
- `../PLAN.md` — Step 51(b).
