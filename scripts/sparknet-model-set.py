#!/usr/bin/env python3
"""Switch the AGX text engine between the two teacher/student sets.

The engine image is fixed; the model is a read-only bind mount selected by the
compose environment. This helper writes a small ``model-set.env`` and recreates
only the ``vllm`` service, leaving the main env file, secrets and the rest of
the node untouched.

Usage::

    scripts/sparknet-model-set.py --role master --set qwen3.6 --precontext off
    scripts/sparknet-model-set.py --role peer --set qwen3 --precontext on

The two sets are:

  qwen3.6  Qwen3.6-35B-A3B Q4_K_M (agx64) + Qwen3.6-27B Q4_K_M (agx32)
  qwen3    Qwen3-32B Q4_K_M        (agx64) + Qwen3-0.6B Q8_0      (agx32)

This is an operator tool. It never pulls a model, never trains and never signs.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_COMPOSE = ROOT / "goagx" / "sparknet.agx.compose.yml"
DEFAULT_ENV = ROOT / "peer-node" / ".state" / "spark-agx.env"
DEFAULT_STATE = ROOT / "peer-node" / ".state" / "model-set.env"
HEALTH_URL = "http://127.0.0.1:8000/health"

SETS = {
    "qwen3.6": {
        "master": ("/opt/sparknet/models/qwen3.6-35b-a3b-q4_k_m.gguf", "qwen3.6-35b"),
        "peer": ("/opt/sparknet/models/qwen3.6-27b-q4_k_m.gguf", "qwen3.6-27b"),
    },
    "qwen3": {
        "master": ("/opt/sparknet/models/qwen3-32b-q4_k_m.gguf", "qwen3-32b"),
        "peer": ("/opt/sparknet/models/qwen3-0.6b-q8_0.gguf", "qwen3-0.6b"),
    },
}


def _health(timeout: float) -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def wait_health(timeout: float) -> float:
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        if _health(2.0):
            return round(time.monotonic() - started, 1)
        time.sleep(2.0)
    raise SystemExit(f"model-set: engine did not become healthy within {timeout:.0f}s")


def write_state(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = "".join(f"{key}={value}\n" for key, value in sorted(values.items()))
    path.write_text(payload, encoding="utf-8")
    path.chmod(0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="switch the AGX text-engine model set")
    parser.add_argument("--role", choices=("master", "peer"), required=True)
    parser.add_argument("--set", dest="model_set", choices=sorted(SETS), required=True)
    parser.add_argument("--precontext", choices=("on", "off"), default="on")
    parser.add_argument("--compose-file", type=Path, default=DEFAULT_COMPOSE)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--extra-args", default="--no-mmap --fit off")
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--no-restart", action="store_true")
    args = parser.parse_args(argv)

    model_file, alias = SETS[args.model_set][args.role]
    values = {
        "SPARKNET_LLM_MODEL_FILE": model_file,
        "VLLM_MODEL": alias,
        "SPARKNET_LLM_CTX": os.environ.get("SPARKNET_LLM_CTX") or "8192",
        "SPARKNET_PRECONTEXT": "1" if args.precontext == "on" else "0",
        "SPARKNET_PRECONTEXT_MAX_BYTES": "16000" if args.precontext == "on" else "",
        "VLLM_EXTRA_ARGS": args.extra_args,
    }
    write_state(args.state_file, values)
    started = time.monotonic()
    if not args.no_restart:
        command = [
            "docker",
            "compose",
            "-f",
            str(args.compose_file),
            "--env-file",
            str(args.env_file),
            "--env-file",
            str(args.state_file),
            "up",
            "-d",
            "--force-recreate",
            "vllm",
        ]
        completed = subprocess.run(command, check=False)
        if completed.returncode != 0:
            return completed.returncode
        elapsed = wait_health(args.timeout)
    else:
        elapsed = 0.0
    result = {
        "role": args.role,
        "set": args.model_set,
        "model_file": model_file,
        "alias": alias,
        "precontext": args.precontext,
        "engine_start_s": elapsed if not args.no_restart else None,
        "wall_s": round(time.monotonic() - started, 1),
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
