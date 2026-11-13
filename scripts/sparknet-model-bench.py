#!/usr/bin/env python3
"""Benchmark the teacher/student candidates on their own node.

This measures what is actually served. It does not pull, start, stop or train a
model. A candidate is an Ollama or OpenAI-compatible endpoint already running on
the node; the script records load time, prompt/decode throughput, memory and a
small deterministic quality suite.

Usage::

    scripts/sparknet-model-bench.py --role master --dry-run
    scripts/sparknet-model-bench.py --role master --candidate qwen3.6-35b-a3b-q4-k-m
    scripts/sparknet-model-bench.py --role peer --candidate qwen3.5-9b-q8
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = ROOT / "contracts" / "model-catalog.json"
ROLE_CONFIG = {
    "peer": ROOT / "peer-node" / "configs" / "model-runtime" / "bakeoff.json",
    "master": ROOT / "master-node" / "configs" / "model-runtime" / "bakeoff.json",
}
SCHEMA = "sparknet-model-bakeoff/1"


class BenchError(RuntimeError):
    """A refusal the operator can act on."""


def log(message: str) -> None:
    print(f"[model-bench] {message}", file=sys.stderr, flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchError(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise BenchError(f"{path} is not a JSON object")
    return data


def catalog_by_id(path: Path) -> dict[str, dict[str, Any]]:
    data = load_json(path)
    models = data.get("models")
    if not isinstance(models, list):
        raise BenchError(f"{path} has no models list")
    return {str(model.get("id")): model for model in models if isinstance(model, dict)}


def validate_config(config: dict[str, Any], role: str, catalog: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if config.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if config.get("role") != role:
        errors.append(f"role must be {role}")
    if not str(config.get("node") or ""):
        errors.append("node must be set")
    provider = config.get("provider")
    if not isinstance(provider, dict) or provider.get("kind") not in ("ollama", "openai"):
        errors.append("provider.kind must be ollama or openai")
    elif not str(provider.get("base_url") or "").startswith("http://127.0.0.1:"):
        errors.append("provider.base_url must be loopback")
    options = config.get("options")
    if not isinstance(options, dict):
        errors.append("options must be an object")
        options = {}
    for key in ("runs", "warmup", "num_ctx", "num_predict", "temperature", "seed", "timeout_seconds"):
        if key not in options:
            errors.append(f"options.{key} is required")
    try:
        if int(options.get("runs", 0)) < 1:
            errors.append("options.runs must be at least 1")
        if int(options.get("num_ctx", 0)) < 512:
            errors.append("options.num_ctx must be at least 512")
        if int(options.get("num_predict", 0)) < 1:
            errors.append("options.num_predict must be positive")
        if options.get("rank") not in (None, "quality", "speed"):
            errors.append("options.rank must be quality or speed")
        if float(options.get("quality_floor", 0.0)) < 0 or float(options.get("quality_floor", 0.0)) > 1:
            errors.append("options.quality_floor must be between 0 and 1")
    except (TypeError, ValueError):
        errors.append("options numeric fields must be integers")
    candidates = config.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return [*errors, "candidates must be a non-empty list"]
    seen: set[str] = set()
    for index, candidate in enumerate(candidates):
        label = f"candidates[{index}]"
        if not isinstance(candidate, dict):
            errors.append(f"{label} is not an object")
            continue
        cid = str(candidate.get("id") or "")
        if not cid:
            errors.append(f"{label} has no id")
            continue
        if cid in seen:
            errors.append(f"{cid}: duplicate id")
        seen.add(cid)
        if candidate.get("role") != ("teacher" if role == "master" else "student"):
            errors.append(f"{cid}: role must be {'teacher' if role == 'master' else 'student'}")
        if not str(candidate.get("model") or ""):
            errors.append(f"{cid}: missing model")
        catalog_id = candidate.get("catalog_id")
        if catalog_id:
            model = catalog.get(str(catalog_id))
            if model is None:
                errors.append(f"{cid}: unknown catalog_id {catalog_id!r}")
            elif config.get("node") not in model.get("nodes", []):
                errors.append(f"{cid}: catalog model is not eligible for {config.get('node')}")
    prompts = config.get("prompts")
    if not isinstance(prompts, list) or not prompts:
        return [*errors, "prompts must be a non-empty list"]
    prompt_ids: set[str] = set()
    for index, prompt in enumerate(prompts):
        label = f"prompts[{index}]"
        if not isinstance(prompt, dict):
            errors.append(f"{label} is not an object")
            continue
        pid = str(prompt.get("id") or "")
        if not pid:
            errors.append(f"{label} has no id")
        elif pid in prompt_ids:
            errors.append(f"{pid}: duplicate prompt id")
        prompt_ids.add(pid)
        if not str(prompt.get("prompt") or "").strip():
            errors.append(f"{label}: missing prompt")
        for key in ("must_include", "must_include_any", "must_not_include"):
            value = prompt.get(key, [])
            if not isinstance(value, list):
                errors.append(f"{label}.{key} must be a list")
    return errors


def _post_json(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise BenchError(f"{url}: response is not an object")
    return data


def _get_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise BenchError(f"{url}: response is not an object")
    return data


def ollama_generate(
    base_url: str,
    *,
    model: str,
    prompt: str,
    options: dict[str, Any],
    num_predict: int,
    timeout: float,
    keep_alive: str | int | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": bool(options.get("think", False)),
        "options": {
            "temperature": options.get("temperature", 0),
            "seed": options.get("seed", 42),
            "num_ctx": options.get("num_ctx", 8192),
            "num_predict": num_predict,
        },
    }
    if keep_alive is not None:
        body["keep_alive"] = keep_alive
    result = _post_json(f"{base_url.rstrip('/')}/api/generate", body, timeout)
    if result.get("error"):
        raise BenchError(str(result["error"]))
    return result


def ollama_unload(base_url: str, model: str, timeout: float = 30) -> None:
    try:
        _post_json(
            f"{base_url.rstrip('/')}/api/generate",
            {"model": model, "prompt": "", "stream": False, "keep_alive": 0},
            timeout,
        )
    except Exception as exc:
        log(f"could not unload {model}: {exc}")


def ollama_memory_gb(base_url: str, model: str, timeout: float = 30) -> float | None:
    try:
        data = _get_json(f"{base_url.rstrip('/')}/api/ps", timeout)
    except Exception:
        return None
    for row in data.get("models", []):
        if isinstance(row, dict) and row.get("name") == model:
            size = int(row.get("size") or row.get("size_vram") or 0)
            return round(size / 1024**3, 2) if size else None
    return None


def openai_chat(
    base_url: str,
    *,
    model: str,
    prompt: str,
    options: dict[str, Any],
    num_predict: int,
    timeout: float,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": options.get("temperature", 0),
        "seed": options.get("seed", 42),
        "max_tokens": num_predict,
        "stream": False,
    }
    template_kwargs = options.get("chat_template_kwargs")
    if isinstance(template_kwargs, dict):
        body["chat_template_kwargs"] = template_kwargs
    return _post_json(f"{base_url.rstrip('/')}/v1/chat/completions", body, timeout)


def _meminfo() -> tuple[int, int] | None:
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, rest = line.partition(":")
            if key in ("MemTotal", "MemAvailable"):
                values[key] = int(rest.strip().split()[0])
        return values["MemTotal"], values["MemAvailable"]
    except (OSError, KeyError, ValueError):
        return None


class _MemorySampler:
    """Peak used unified memory while a benchmark runs."""

    def __init__(self, interval: float = 0.5) -> None:
        self.interval = interval
        self.peak_gb = 0.0
        self.baseline_gb: float | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        first = _meminfo()
        if first:
            total, available = first
            self.baseline_gb = round((total - available) / 1024**2, 2)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            sample = _meminfo()
            if not sample:
                continue
            total, available = sample
            self.peak_gb = max(self.peak_gb, round((total - available) / 1024**2, 2))

    def stop(self) -> float | None:
        self._stop.set()
        self._thread.join(timeout=5)
        return self.peak_gb or None


def quality(prompt: dict[str, Any], answer: str) -> tuple[bool, list[str]]:
    text = answer.lower()
    failures = [f"missing {needle!r}" for needle in prompt.get("must_include", []) if str(needle).lower() not in text]
    any_of = [str(needle) for needle in prompt.get("must_include_any", [])]
    if any_of and not any(needle.lower() in text for needle in any_of):
        failures.append(f"missing any of {any_of!r}")
    failures += [f"contains {needle!r}" for needle in prompt.get("must_not_include", []) if str(needle).lower() in text]
    return not failures, failures


def measure(
    *,
    candidate: dict[str, Any],
    provider: dict[str, Any],
    options: dict[str, Any],
    prompts: list[dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    base_url = str(provider["base_url"]).rstrip("/")
    kind = str(provider["kind"])
    model = str(candidate["model"])
    rows: list[dict[str, Any]] = []
    sampler = _MemorySampler() if kind == "openai" else None
    if sampler is not None:
        sampler.start()
    warmup_prompt = str(prompts[0]["prompt"])
    log(f"{candidate['id']}: warming {model}")
    if kind == "ollama":
        ollama_generate(
            base_url,
            model=model,
            prompt=warmup_prompt,
            options=options,
            num_predict=8,
            timeout=timeout,
            keep_alive="5m",
        )
    else:
        openai_chat(
            base_url,
            model=model,
            prompt=warmup_prompt,
            options=options,
            num_predict=8,
            timeout=timeout,
        )

    for run in range(int(options["runs"])):
        for prompt in prompts:
            started = time.perf_counter()
            if kind == "ollama":
                result = ollama_generate(
                    base_url,
                    model=model,
                    prompt=str(prompt["prompt"]),
                    options=options,
                    num_predict=int(prompt.get("max_tokens", options["num_predict"])),
                    timeout=timeout,
                    keep_alive="5m",
                )
                answer = str(result.get("response") or "")
                wall = time.perf_counter() - started
                prompt_count = int(result.get("prompt_eval_count") or 0)
                eval_count = int(result.get("eval_count") or 0)
                prompt_ns = int(result.get("prompt_eval_duration") or 0)
                eval_ns = int(result.get("eval_duration") or 0)
                load_ns = int(result.get("load_duration") or 0)
                row = {
                    "prompt_id": prompt["id"],
                    "run": run,
                    "wall_s": round(wall, 3),
                    "load_s": round(load_ns / 1e9, 3),
                    "prompt_tokens": prompt_count,
                    "completion_tokens": eval_count,
                    "prompt_tok_s": round(prompt_count / (prompt_ns / 1e9), 2) if prompt_ns else None,
                    "decode_tok_s": round(eval_count / (eval_ns / 1e9), 2) if eval_ns else None,
                }
            else:
                result = openai_chat(
                    base_url,
                    model=model,
                    prompt=str(prompt["prompt"]),
                    options=options,
                    num_predict=int(prompt.get("max_tokens", options["num_predict"])),
                    timeout=timeout,
                )
                choices = result.get("choices") if isinstance(result.get("choices"), list) else []
                message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
                answer = str(message.get("content") or "")
                usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
                timings = result.get("timings") if isinstance(result.get("timings"), dict) else {}
                wall = time.perf_counter() - started
                decode = timings.get("predicted_per_second")
                prompt_tps = timings.get("prompt_per_second")
                row = {
                    "prompt_id": prompt["id"],
                    "run": run,
                    "wall_s": round(wall, 3),
                    "load_s": None,
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                    "prompt_tok_s": round(float(prompt_tps), 2) if prompt_tps else None,
                    "decode_tok_s": round(float(decode), 2)
                    if decode
                    else round(int(usage.get("completion_tokens") or 0) / wall, 2)
                    if wall
                    else None,
                }
            passed, failures = quality(prompt, answer)
            row["quality_pass"] = passed
            row["quality_failures"] = failures
            row["answer"] = answer
            row["answer_preview"] = answer[:500]
            rows.append(row)

    baseline_memory = None
    if kind == "ollama":
        memory = ollama_memory_gb(base_url, model)
        if options.get("unload_after", True):
            ollama_unload(base_url, model)
    else:
        memory = sampler.stop() if sampler is not None else None
        baseline_memory = sampler.baseline_gb if sampler is not None else None

    successful = [row for row in rows if row["quality_pass"]]
    decode = [row["decode_tok_s"] for row in rows if row.get("decode_tok_s")]
    wall = [row["wall_s"] for row in rows if row.get("wall_s")]
    load = [row["load_s"] for row in rows if row.get("load_s")]
    summary = {
        "id": candidate["id"],
        "model": model,
        "role": candidate.get("role"),
        "quality_pass_rate": round(len(successful) / len(rows), 3) if rows else 0.0,
        "decode_tok_s_median": round(statistics.median(decode), 2) if decode else None,
        "wall_s_median": round(statistics.median(wall), 3) if wall else None,
        "load_s_median": round(statistics.median(load), 3) if load else None,
        "peak_memory_gb": memory,
        "baseline_memory_gb": baseline_memory,
        "precontext": options.get("precontext"),
        "rows": rows,
    }
    log(
        f"{candidate['id']}: quality {summary['quality_pass_rate']:.0%}, "
        f"decode {summary['decode_tok_s_median']} tok/s, memory {summary['peak_memory_gb']} GiB"
    )
    return summary


def run(
    *,
    config: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
    role: str,
    candidates: list[str],
    out: Path | None,
    dry_run: bool,
) -> dict[str, Any]:
    options = config["options"]
    selected = [c for c in config["candidates"] if not candidates or c["id"] in candidates]
    missing = set(candidates) - {c["id"] for c in selected}
    if missing:
        raise BenchError(f"unknown candidate(s): {', '.join(sorted(missing))}")
    rank = str(options.get("rank") or "quality")
    quality_floor = float(options.get("quality_floor") or 0.0)
    result = {
        "schema": "sparknet-model-bakeoff-result/1",
        "role": role,
        "node": config.get("node"),
        "generated_at": now_iso(),
        "options": options,
        "rank": rank,
        "quality_floor": quality_floor,
        "candidates": [],
    }
    if dry_run:
        for candidate in selected:
            print(f"{candidate['id']}\t{candidate['model']}\t{candidate.get('role')}")
        result["dry_run"] = True
        return result

    for candidate in selected:
        try:
            measured = measure(
                candidate=candidate,
                provider=config["provider"],
                options=options,
                prompts=config["prompts"],
                timeout=float(options["timeout_seconds"]),
            )
            measured["eligible"] = measured["quality_pass_rate"] >= quality_floor
            result["candidates"].append(measured)
        except Exception as exc:
            log(f"{candidate['id']}: FAILED: {exc}")
            result["candidates"].append({"id": candidate["id"], "model": candidate["model"], "error": str(exc)})

    def _rank_key(row: dict[str, Any]) -> tuple[Any, ...]:
        eligible = bool(row.get("eligible"))
        quality = row.get("quality_pass_rate") or 0.0
        decode = row.get("decode_tok_s_median") or 0.0
        memory = row.get("peak_memory_gb") or 0.0
        if rank == "speed":
            return (eligible, decode, quality, -memory)
        return (eligible, quality, decode, -memory)

    ranked = sorted(
        [row for row in result["candidates"] if "error" not in row],
        key=_rank_key,
        reverse=True,
    )
    result["leaderboard"] = [
        {
            "id": row["id"],
            "model": row["model"],
            "eligible": row.get("eligible"),
            "quality_pass_rate": row["quality_pass_rate"],
            "decode_tok_s_median": row.get("decode_tok_s_median"),
            "wall_s_median": row.get("wall_s_median"),
            "peak_memory_gb": row.get("peak_memory_gb"),
            "precontext": row.get("precontext"),
        }
        for row in ranked
    ]
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = json.dumps(result, indent=2, sort_keys=True) + "\n"
        fd, temp_name = tempfile.mkstemp(prefix=f".{out.name}.", suffix=".tmp", dir=out.parent)
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, out)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        log(f"wrote {out}")
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark sparknet teacher/student candidates")
    parser.add_argument("--role", choices=("peer", "master"), default=os.environ.get("SPARKNET_ROLE", "peer"))
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--candidate", action="append", default=[])
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--rank", choices=("quality", "speed"), default=None)
    parser.add_argument("--precontext", choices=("off", "on"), default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = args.config or ROLE_CONFIG[args.role]
    try:
        config = load_json(config_path)
        if args.rank:
            config.setdefault("options", {})["rank"] = args.rank
        if args.precontext:
            config.setdefault("options", {})["precontext"] = args.precontext
        catalog = catalog_by_id(args.catalog)
        errors = validate_config(config, args.role, catalog)
        if errors:
            for error in errors:
                print(f"model-bench: {error}", file=sys.stderr)
            return 1
        out = args.out
        if out is None and not args.dry_run:
            state = Path(os.environ.get("SPARKNET_STATE_DIR", str(ROOT / ".state")))
            out = state / "model-bakeoff" / f"{args.role}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        result = run(
            config=config,
            catalog=catalog,
            role=args.role,
            candidates=args.candidate,
            out=out,
            dry_run=args.dry_run,
        )
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        elif not args.dry_run:
            print(json.dumps(result.get("leaderboard", []), indent=2, sort_keys=True))
        failed = any("error" in row for row in result.get("candidates", []))
        return 1 if failed else 0
    except BenchError as exc:
        print(f"model-bench: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
