#!/usr/bin/env python3
"""Switch the agx32 peer between the text, coding and vision modes.

The peer has 30 GB of unified memory. The 4B 262k text engine, the 30B coder
and the VL 4B cannot all be resident. This operator tool stops the previous
large surface, unloads the Ollama models that do not belong to the target mode,
and starts the text engine when needed.

Usage::

    scripts/sparknet-peer-mode.py --mode text
    scripts/sparknet-peer-mode.py --mode coding
    scripts/sparknet-peer-mode.py --mode vision --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "goagx" / "sparknet.agx.compose.yml"
ENV = ROOT / "peer-node" / ".state" / "spark-agx.env"
OLLAMA = "http://127.0.0.1:11434"
BASE_KEEP = {"qwen3-embedding-0.6b:latest"}
MODELS = {
    "text": {"keep": set(BASE_KEEP)},
    "coding": {"keep": {"qwen3-coder-30b-65k:latest", *BASE_KEEP}},
    "vision": {"keep": {"qwen3-vl-4b-65k:latest", *BASE_KEEP}},
}


def _run(command: list[str], dry_run: bool) -> int:
    print("+", " ".join(command))
    if dry_run:
        return 0
    return subprocess.run(command, check=False).returncode


def _ollama(path: str, body: dict | None = None, timeout: float = 30.0) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        OLLAMA + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _unload(models: list[str], dry_run: bool) -> None:
    for model in models:
        print(f"+ ollama unload {model}")
        if dry_run:
            continue
        try:
            _ollama("/api/generate", {"model": model, "keep_alive": 0}, timeout=10)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            print(f"  warn: {model}: {exc}", file=sys.stderr)


def _running_ollama() -> list[str]:
    try:
        data = _ollama("/api/ps")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return []
    return [str(row.get("name")) for row in data.get("models", []) if isinstance(row, dict)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="switch the peer text/coding/vision mode")
    parser.add_argument("--mode", choices=sorted(MODELS), required=True)
    parser.add_argument("--compose-file", type=Path, default=COMPOSE)
    parser.add_argument("--env-file", type=Path, default=ENV)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    keep = MODELS[args.mode]["keep"]
    running = [] if args.dry_run else _running_ollama()
    unload = [model for model in running if model not in keep]
    if args.mode in ("coding", "vision"):
        _run(
            [
                "docker",
                "compose",
                "-f",
                str(args.compose_file),
                "--env-file",
                str(args.env_file),
                "stop",
                "vllm",
            ],
            args.dry_run,
        )
    _unload(unload, args.dry_run)
    if args.mode == "text":
        _run(
            [
                "docker",
                "compose",
                "-f",
                str(args.compose_file),
                "--env-file",
                str(args.env_file),
                "up",
                "-d",
                "vllm",
            ],
            args.dry_run,
        )
        if not args.dry_run:
            deadline = time.monotonic() + 600
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen(OLLAMA.replace("11434", "8000") + "/health", timeout=2) as response:
                        if response.status == 200:
                            break
                except (urllib.error.URLError, TimeoutError, OSError):
                    time.sleep(2)
    print(json.dumps({"mode": args.mode, "kept_ollama": sorted(keep), "unloaded": unload}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
