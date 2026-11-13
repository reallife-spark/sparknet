#!/usr/bin/env python3
"""sparknet-llm-entrypoint — serve a GGUF through llama-server.

The AGX text engine is a `jetson-containers` llama.cpp image, not a vLLM
Python stack. This dispatcher keeps the node's stable contract:

  * the container still answers on port 8000 with the OpenAI-compatible
    `/v1/models`, `/v1/chat/completions` and `/health` surface;
  * `VLLM_MODEL` remains the served alias, `VLLM_PORT` the port,
    `VLLM_MAX_MODEL_LEN` the context size and `VLLM_EXTRA_ARGS` the escape
    hatch, while `SPARKNET_LLM_MODEL_FILE` names the actual GGUF;
  * the fabric precontext is injected by the tiny OpenAI proxy beside
    `llama-server`, because this llama.cpp build has no
    `--system-prompt-file` flag. The proxy prepends the MASTERSPIKE text and
    the generated fabric digest as a system message, merging an existing one
    exactly like the vLLM-era chat-template wrapper did.

The model file is the only model input. It is mounted read-only from the
node's root model directory; this container never mounts a vault, a key or the
node state directory.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import NoReturn

CONTEXT_DIR = Path(os.environ.get("SPARKNET_CONTEXT_DIR") or "/opt/sparknet/context")
NODE_DIR = Path(os.environ.get("SPARKNET_NODE_DIR") or "/srv/sparknet/peer-node")
DEFAULT_PORT = "8000"
DEFAULT_UPSTREAM_PORT = "8004"
DEFAULT_CTX = "8192"
DEFAULT_NGL = "99"
ALL_INTERFACES = "0.0.0.0"  # noqa: S104 - the proxy binds the published interface

USAGE = """sparknet-llm-entrypoint — llama.cpp text engine for the AGX node

Usage: sparknet-llm-entrypoint <subcommand> [args...]

Subcommands:
  vllm        serve SPARKNET_LLM_MODEL_FILE through llama-server and the
              precontext proxy (OpenAI /v1/chat/completions, /v1/models,
              /health on VLLM_PORT, default 8000)
  vllm-stub   not in this image; use the node image's vllm-stub
  help        this text

Key environment (all optional; defaults shown):
  SPARKNET_LLM_MODEL_FILE   the GGUF path (required for vllm)
  SPARKNET_LLM_MODEL_ALIAS  VLLM_MODEL, else the model file stem
  VLLM_MODEL                served alias (historical name)
  VLLM_PORT                 8000
  SPARKNET_LLM_UPSTREAM_PORT 8004 (llama-server loopback port)
  SPARKNET_LLM_CTX          VLLM_MAX_MODEL_LEN, else 8192
  SPARKNET_LLM_NGL          99
  SPARKNET_LLM_PARALLEL     1
  SPARKNET_LLM_THREADS      llama.cpp default
  VLLM_EXTRA_ARGS           extra llama-server flags
  SPARKNET_LLM_EXTRA_ARGS   extra llama-server flags (same split)
  SPARKNET_PRECONTEXT       1 = inject the fabric precontext
  SPARKNET_PRECONTEXT_MAX_BYTES  cap the injected text; 0 = no cap
"""


def log(message: str) -> None:
    print(f"[sparknet-llm] {message}", file=sys.stderr, flush=True)


def die(message: str) -> NoReturn:
    print(f"[sparknet-llm] ERROR: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def _exec(command: str, args: list[str], *, env: dict[str, str] | None = None) -> NoReturn:
    try:
        os.execvpe(command, [command, *args], env if env is not None else os.environ)  # noqa: S606 - fixed argv
    except FileNotFoundError:
        print(f"sparknet-llm-entrypoint: {command}: not found", file=sys.stderr, flush=True)
        raise SystemExit(127) from None


def _help_text(binary: str) -> str:
    try:
        completed = subprocess.run(
            [binary, "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return completed.stdout or ""


def _supports(help_text: str, *flags: str) -> bool:
    return any(flag in help_text for flag in flags)


def build_precontext() -> str:
    """Write the MASTERSPIKE text + fabric digest to a proxy-readable file."""
    if os.environ.get("SPARKNET_PRECONTEXT", "1") != "1":
        return ""
    parts: list[str] = []
    for candidate in (
        NODE_DIR / "CONTEXT.md",
        CONTEXT_DIR / "masterspike-system-prompt.md",
        CONTEXT_DIR / "fabric-digest.md",
    ):
        try:
            if candidate.is_file() and candidate.stat().st_size:
                parts.append(candidate.read_text(encoding="utf-8").strip())
        except OSError:
            continue
    if not parts:
        return ""
    text = "\n\n---\n\n".join(part for part in parts if part)
    cap = os.environ.get("SPARKNET_PRECONTEXT_MAX_BYTES") or ""
    if cap.isdigit() and int(cap) > 0:
        text = text.encode("utf-8")[: int(cap)].decode("utf-8", "ignore")
    default = Path(tempfile.gettempdir()) / "sparknet-precontext.md"
    out = Path(os.environ.get("SPARKNET_LLM_PRECONTEXT_FILE") or default)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    out.chmod(0o600)
    return str(out)


def _model_file() -> str:
    explicit = os.environ.get("SPARKNET_LLM_MODEL_FILE") or ""
    if explicit:
        return explicit
    candidate = os.environ.get("VLLM_MODEL") or ""
    if candidate and Path(candidate).is_file():
        return candidate
    return ""


def _alias(model_file: str) -> str:
    explicit = os.environ.get("SPARKNET_LLM_MODEL_ALIAS") or ""
    if explicit:
        return explicit
    historical = os.environ.get("VLLM_MODEL") or ""
    if historical and not Path(historical).is_file():
        return historical
    return Path(model_file).stem


def _llama_args(help_text: str, model_file: str) -> list[str]:
    alias = _alias(model_file)
    port = os.environ.get("SPARKNET_LLM_UPSTREAM_PORT") or DEFAULT_UPSTREAM_PORT
    ctx = os.environ.get("SPARKNET_LLM_CTX") or os.environ.get("VLLM_MAX_MODEL_LEN") or DEFAULT_CTX
    ngl = os.environ.get("SPARKNET_LLM_NGL") or DEFAULT_NGL
    args = [
        "--model",
        model_file,
        "--host",
        "127.0.0.1",
        "--port",
        port,
        "--alias",
        alias,
        "--ctx-size",
        ctx,
        "--n-gpu-layers",
        ngl,
    ]
    if _supports(help_text, "--parallel"):
        args.extend(["--parallel", os.environ.get("SPARKNET_LLM_PARALLEL") or "1"])
    if _supports(help_text, "--cont-batching") and os.environ.get("SPARKNET_LLM_CONT_BATCHING", "1") != "0":
        args.append("--cont-batching")
    if _supports(help_text, "--jinja") and os.environ.get("SPARKNET_LLM_JINJA", "1") != "0":
        args.append("--jinja")
    if _supports(help_text, "--metrics") and os.environ.get("SPARKNET_LLM_METRICS", "0") == "1":
        args.append("--metrics")
    if _supports(help_text, "--flash-attn") and os.environ.get("SPARKNET_LLM_FLASH_ATTN", "0") == "1":
        args.append("--flash-attn")
    threads = os.environ.get("SPARKNET_LLM_THREADS") or ""
    if threads.isdigit() and _supports(help_text, "--threads"):
        args.extend(["--threads", threads])
    extra = " ".join(
        value for value in (os.environ.get("VLLM_EXTRA_ARGS"), os.environ.get("SPARKNET_LLM_EXTRA_ARGS")) if value
    )
    if extra:
        args.extend(shlex.split(extra))
    return args


def _supervise(commands: list[tuple[list[str], dict[str, str] | None]]) -> int:
    children = [subprocess.Popen(command, env=env) for command, env in commands]
    stopped = {"value": False}

    def _stop(_signum: int, _frame: object) -> None:
        stopped["value"] = True

    previous = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(OSError, ValueError):
            previous[sig] = signal.signal(sig, _stop)
    try:
        while True:
            for child in children:
                if child.poll() is not None:
                    return child.returncode
            if stopped["value"]:
                return 0
            time.sleep(0.2)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def cmd_vllm(_args: list[str]) -> int:
    binary = shutil.which("llama-server")
    if binary is None:
        die("llama-server not found in this image")
    model_file = _model_file()
    if not model_file:
        die(
            "SPARKNET_LLM_MODEL_FILE is not set (or VLLM_MODEL is not a file); "
            "mount the GGUF on the root model directory"
        )
    if not Path(model_file).is_file() or not Path(model_file).stat().st_size:
        die(f"model file missing or empty: {model_file}")
    help_text = _help_text(binary)
    if not help_text:
        die("llama-server --help produced no output; refusing to guess the flag surface")
    precontext = build_precontext()
    if precontext:
        log(f"precontext: {precontext} ({Path(precontext).stat().st_size} bytes)")
    else:
        log("WARN: precontext unavailable; serving without the fabric system prompt")
    port = os.environ.get("VLLM_PORT") or os.environ.get("SPARKNET_LLM_PORT") or DEFAULT_PORT
    upstream_port = os.environ.get("SPARKNET_LLM_UPSTREAM_PORT") or DEFAULT_UPSTREAM_PORT
    llama = [binary, *_llama_args(help_text, model_file)]
    proxy = [
        sys.executable,
        "-m",
        "uvicorn",
        "sparknet_llm_proxy:app",
        "--app-dir",
        "/opt/sparknet",
        "--host",
        ALL_INTERFACES,
        "--port",
        port,
        "--log-level",
        "warning",
    ]
    proxy_env = {
        **os.environ,
        "SPARKNET_LLM_UPSTREAM": os.environ.get("SPARKNET_LLM_UPSTREAM") or f"http://127.0.0.1:{upstream_port}",
        "SPARKNET_LLM_PRECONTEXT_FILE": precontext,
    }
    log(f"llama-server {model_file} on 127.0.0.1:{upstream_port}; proxy on 0.0.0.0:{port}")
    log(f"llama-server {' '.join(llama[1:])}")
    return _supervise([(llama, None), (proxy, proxy_env)])


def cmd_vllm_stub(_args: list[str]) -> NoReturn:
    die("vllm-stub is not in sparknet-llm; run --engine stub so compose uses the node image")


COMMANDS = {
    "vllm": cmd_vllm,
    "vllm-stub": cmd_vllm_stub,
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "help"
    if command in ("--help", "-h", "help", ""):
        print(USAGE, end="")
        return 0
    handler = COMMANDS.get(command)
    if handler is None:
        print(f"sparknet-llm-entrypoint: unknown subcommand: {command}", file=sys.stderr)
        print(USAGE, end="", file=sys.stderr)
        return 2
    return handler(args[1:])


if __name__ == "__main__":
    raise SystemExit(main())
