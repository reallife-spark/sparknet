#!/usr/bin/env python3
"""Prepare a raw-KV artifact for the Master's uplift intake.

Raw KV tensors are engine-specific and large (roughly 256 KiB per token for a
64-layer/8-KV-head/128-dim model), so this tool does not put them in Qdrant.
It compresses a safetensors-style artifact, records the model/architecture
metadata, and leaves the upload to ``sparknet-uplift-push.py kv``.

``--from-file`` is the supported path: an operator or a future vLLM connector
exports the tensors, and this tool validates the file header and writes a
manifest. ``--from-vllm`` is deliberately refused until a version-pinned
connector is implemented and tested on the live engine; a fake export would be
worse than an honest refusal.

Usage::

    sparknet-kv-export.py --from-file kv.safetensors --model Qwen/Qwen2.5-32B \
        --architecture qwen2 --layers 64 --kv-heads 8 --head-dim 128 --out kv.spool
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _safetensors_header(path: Path) -> dict[str, Any]:
    """Read the JSON header of a safetensors file without loading tensors."""
    with path.open("rb") as handle:
        raw = handle.read(8)
        if len(raw) != 8:
            raise ValueError("not a safetensors file: shorter than the 8-byte header length")
        length = struct.unpack("<Q", raw)[0]
        if length <= 0 or length > 100 * 1024 * 1024:
            raise ValueError(f"implausible safetensors header length: {length}")
        header = handle.read(length)
    payload = json.loads(header.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("safetensors header is not a JSON object")
    return payload


def export(
    *,
    source: Path,
    model: str,
    architecture: str,
    layers: int,
    kv_heads: int,
    head_dim: int,
    dtype: str,
    out: Path,
) -> dict[str, Any]:
    header = _safetensors_header(source)
    tensors = [key for key in header if key != "__metadata__"]
    if not tensors:
        raise ValueError("safetensors file has no tensors")
    digest = hashlib.sha256()
    with source.open("rb") as src:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    digest_hex = digest.hexdigest()
    out.mkdir(parents=True, exist_ok=True, mode=0o700)
    compressed = out / f"{digest_hex[:16]}.safetensors.gz"
    with source.open("rb") as src, gzip.open(compressed, "wb", compresslevel=6) as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)
    manifest = {
        "schema": "sparknet-kv-artifact/1",
        "artifact_id": digest_hex[:16],
        "sha256": digest_hex,
        "source_sha256": digest_hex,
        "size": compressed.stat().st_size,
        "source_size": source.stat().st_size,
        "model_id": model,
        "architecture": architecture,
        "num_layers": layers,
        "num_kv_heads": kv_heads,
        "head_dim": head_dim,
        "dtype": dtype,
        "tensor_count": len(tensors),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "compression": "gzip",
        "file": compressed.name,
    }
    (out / f"{digest_hex[:16]}.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a raw-KV artifact for uplift")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-file", type=Path, help="safetensors export from the engine")
    source.add_argument("--from-vllm", action="store_true", help="request live vLLM capture (refused until pinned)")
    parser.add_argument("--model", required=True)
    parser.add_argument("--architecture", default="")
    parser.add_argument("--layers", type=int, default=0)
    parser.add_argument("--kv-heads", type=int, default=0)
    parser.add_argument("--head-dim", type=int, default=0)
    parser.add_argument("--dtype", default="auto")
    parser.add_argument("--out", type=Path, default=Path("kv-spool"))
    args = parser.parse_args(argv)
    if args.from_vllm:
        print(
            "sparknet-kv-export: live vLLM KV capture is not implemented in this build. "
            "No version-pinned connector has been exercised on the live engine, so the "
            "tool refuses rather than exporting a fake artifact. Use --from-file with an "
            "engine export; the trace path remains the distillation signal.",
            file=sys.stderr,
        )
        return 3
    try:
        manifest = export(
            source=args.from_file,
            model=args.model,
            architecture=args.architecture,
            layers=args.layers,
            kv_heads=args.kv_heads,
            head_dim=args.head_dim,
            dtype=args.dtype,
            out=args.out,
        )
    except (OSError, ValueError) as exc:
        print(f"sparknet-kv-export: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
