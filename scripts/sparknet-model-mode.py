#!/usr/bin/env python3
"""Switch the peer between its text, coding and vision GPU modes.

The 30B text engine, the 30B coder and the VL model cannot all be resident on
one AGX GPU. Text is the default; coding and vision stop the 30B, and text
returns after an operator (or an agent) requests it. Embedding stays on the
separate CPU endpoint and is not affected.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request

OLLAMA = "http://127.0.0.1:11434"
VLLM = "sparknet-vllm"
MODES = {
    "text": {"unload": ("qwen3-coder-30b-65k:latest", "qwen3-vl-4b-65k:latest"), "stop": True},
    "coding": {"unload": ("qwen3-vl-4b-65k:latest",), "stop": False},
    "vision": {"unload": ("qwen3-coder-30b-65k:latest",), "stop": False},
}


def _run(command: list[str], dry_run: bool) -> int:
    print("+", " ".join(command))
    return 0 if dry_run else subprocess.run(command, check=False).returncode


def _ollama_unload(model: str, dry_run: bool, base: str = OLLAMA) -> None:
    print(f"+ ollama unload {model}")
    if dry_run:
        return
    body = json.dumps({"model": model, "keep_alive": 0}).encode()
    request = urllib.request.Request(
        base.rstrip("/") + "/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10):
            pass
    except (urllib.error.URLError, TimeoutError, OSError):
        pass


def _health(url: str, timeout: float) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="switch peer text/coding/vision mode")
    parser.add_argument("--mode", choices=sorted(MODES), required=True)
    parser.add_argument("--vllm-container", default=VLLM)
    parser.add_argument("--ollama", default=OLLAMA)
    parser.add_argument("--wait", type=float, default=180.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    policy = MODES[args.mode]
    for model in policy["unload"]:
        _ollama_unload(model, args.dry_run, args.ollama)

    if args.mode == "text":
        _run(["docker", "start", args.vllm_container], args.dry_run)
        if not args.dry_run:
            deadline = time.monotonic() + args.wait
            while time.monotonic() < deadline:
                if _health("http://127.0.0.1:8000/health", 3):
                    break
                time.sleep(2)
            else:
                return 1
    else:
        _run(["docker", "stop", args.vllm_container], args.dry_run)

    print(json.dumps({"mode": args.mode, "vllm_running": args.mode == "text"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
