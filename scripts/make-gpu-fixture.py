#!/usr/bin/env python3
"""Emit a synthetic GPU telemetry fixture for goSpark's sim backend.

The fixture matches goSpark's gputel.Snapshot JSON (see
goSpark/internal/gputel/gputel.go) and lets sparknet-gpu report
`available=true` on a host with no NVIDIA driver, so the whole
sidecar -> NATS -> control -> placement -> metrics path can be exercised
hardware-free:

    ./scripts/make-gpu-fixture.py -o /tmp/gpu.json
    SPARKNET_GPU_FIXTURE=/tmp/gpu.json sparknet-gpu -watch -node-id host \
        -interval 30s -bus nats://127.0.0.1:4222

This is a *telemetry* fixture only. It never carries authority: the control
plane records it like any other reading, and placement stays subject to its
own health/mem/temperature gates. Nothing here is used unless the operator
opts in by setting SPARKNET_GPU_FIXTURE (or sparknet-gpu's -sim-fixture flag).
"""

from __future__ import annotations

import argparse
import json
import sys
import time

# Defaults roughly shaped like a GB10-class part so placement thresholds
# behave plausibly (no memory pressure, moderate temperature).
DEFAULT_GPU = {
    "name": "GB10-SIM",
    "temp_c": 46,
    "mem_used_bytes": 4 * 1024**3,
    "mem_total_bytes": 100 * 1024**3,
    "util_pct": 7,
    "mem_util_pct": 4,
    "power_milliwatts": 62_000,
    "sm_clock_mhz": 1_400,
    "mem_clock_mhz": 3_200,
}


def build(count: int, *, driver: str, available: bool) -> dict:
    gpus = []
    health = []
    for i in range(count):
        gpu = {"index": i, "uuid": f"SIM-GPU-{i:04d}", **DEFAULT_GPU}
        gpus.append(gpu)
        health.append(
            {
                "index": i,
                "status": "Healthy" if available else "Unknown",
                "watches": ["mem", "temp"],
            }
        )
    return {
        "source": "sim",
        "available": available,
        "reason": "" if available else "sim: available=false requested",
        "driver_version": driver,
        "gpus": gpus,
        "health": health,
        "collected_at_unix": int(time.time()),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("-o", "--output", default="-", help="output file (default stdout)")
    p.add_argument("-n", "--gpus", type=int, default=1, help="number of simulated GPUs")
    p.add_argument(
        "--driver",
        default="sim-550.90.07",
        help="driver_version string to report",
    )
    p.add_argument(
        "--unavailable",
        action="store_true",
        help="emit a degraded (available=false) fixture for testing the fallback path",
    )
    args = p.parse_args(argv)

    if args.gpus < 1:
        print("make-gpu-fixture: --gpus must be >= 1", file=sys.stderr)
        return 2

    doc = build(args.gpus, driver=args.driver, available=not args.unavailable)
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if args.output == "-":
        sys.stdout.write(text)
    else:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"make-gpu-fixture: wrote {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
