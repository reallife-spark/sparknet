#!/usr/bin/env python3
"""Verify, sign and upload a returned external-trainer GGUF.

The external GPU host never gets the peer key. This script runs on agx32 after
the operator returns `student-q4_k_m.gguf` (and optionally `export.json`),
verifies the SHA-256, and delegates the signed upload to the normal 8091
student-artifact path.

Usage::

    scripts/sparknet-distill-import.py \
      --artifact /mnt/ai/distill/incoming/student-q4_k_m.gguf \
      --export-json /mnt/ai/distill/incoming/export.json \
      --run run-...
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUSH = ROOT / "scripts" / "sparknet-uplift-push.py"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected(path: Path | None) -> str:
    if path is None:
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    value = data.get("sha256") if isinstance(data, dict) else None
    return str(value or "")


def import_artifact(
    artifact: Path,
    *,
    export_json: Path | None,
    expected_sha256: str,
    run: str,
    model: str,
    base: str,
) -> dict:
    if not artifact.is_file():
        raise SystemExit(f"distill-import: artifact missing: {artifact}")
    if artifact.stat().st_size < 10 * 1024 * 1024:
        raise SystemExit("distill-import: artifact is implausibly small")
    digest = _sha256(artifact)
    expected = expected_sha256 or _expected(export_json)
    if expected and expected != digest:
        raise SystemExit(f"distill-import: sha256 mismatch: expected {expected}, got {digest}")
    command = [
        sys.executable,
        str(PUSH),
        "student",
        "--file",
        str(artifact),
        "--model",
        model,
        "--base",
        base,
        "--run",
        run,
    ]
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        raise SystemExit(f"distill-import: signed upload failed ({completed.returncode})")
    return {
        "schema": "sparknet-distill-import/1",
        "artifact": str(artifact),
        "sha256": digest,
        "size": artifact.stat().st_size,
        "run": run,
        "model": model,
        "uploaded": True,
        "note": "run sparknet-student-sync.py as root to refresh the agx64 4B copy",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="verify and upload a returned external-trainer GGUF")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument(
        "--export-json", type=Path, help="export.json from the external host; supplies the expected SHA-256"
    )
    parser.add_argument("--sha256", default="", help="expected SHA-256 (overrides export.json)")
    parser.add_argument("--run", required=True)
    parser.add_argument("--model", default="qwen3-4b-2507")
    parser.add_argument("--base", default="Qwen/Qwen3-4B-Instruct-2507")
    args = parser.parse_args(argv)
    result = import_artifact(
        args.artifact,
        export_json=args.export_json,
        expected_sha256=args.sha256,
        run=args.run,
        model=args.model,
        base=args.base,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
