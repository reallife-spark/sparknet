#!/usr/bin/env python3
"""Stage a catalog model file between the cold store and the root serving copy.

The AGX bake-off keeps the winner on the root NVMe and the other set in the
cold store under ``/mnt/ai/models/<model-id>/``. This helper moves or copies
one file between the two, verifies its SHA-256 and prints the digest.

Usage::

    scripts/sparknet-model-stage.py --model-id qwen3-32b-q4-k-m --to-root
    scripts/sparknet-model-stage.py --model-id qwen3.6-27b-q4-k-m --to-cold --move

It is an operator tool. It never pulls, serves, signs or writes a vault.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

MODELS = {
    "qwen3.6-35b-a3b-q4-k-m": ("qwen3.6-35b-a3b-q4_k_m.gguf", "agx64"),
    "qwen3.6-27b-q4-k-m": ("qwen3.6-27b-q4_k_m.gguf", "agx32"),
    "qwen3-32b-q4-k-m": ("qwen3-32b-q4_k_m.gguf", "agx64"),
    "qwen3-0.6b-q8": ("qwen3-0.6b-q8_0.gguf", "agx32"),
}
DEFAULT_STORE = Path("/mnt/ai/models")
DEFAULT_ROOT = Path("/opt/sparknet/models")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="stage a model between cold store and root")
    parser.add_argument("--model-id", choices=sorted(MODELS), required=True)
    direction = parser.add_mutually_exclusive_group(required=True)
    direction.add_argument("--to-root", action="store_true")
    direction.add_argument("--to-cold", action="store_true")
    parser.add_argument("--move", action="store_true", help="remove the source after the copy")
    parser.add_argument("--force", action="store_true", help="overwrite the destination")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--sha256", default="", help="expected SHA-256 (optional)")
    args = parser.parse_args(argv)

    filename, _node = MODELS[args.model_id]
    cold = args.store / args.model_id / filename
    root = args.root / filename
    source, destination = (cold, root) if args.to_root else (root, cold)
    if not source.is_file():
        raise SystemExit(f"model-stage: source missing: {source}")
    if destination.exists() and not args.force:
        raise SystemExit(f"model-stage: destination exists (use --force): {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if args.move:
        shutil.move(str(source), str(destination))
    else:
        shutil.copy2(source, destination)
    actual = _sha256(destination)
    if args.sha256 and actual != args.sha256:
        raise SystemExit(f"model-stage: SHA-256 mismatch: expected {args.sha256}, got {actual}")
    print(f"model-stage: {args.model_id} {'root' if args.to_root else 'cold'} {destination} sha256={actual}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
