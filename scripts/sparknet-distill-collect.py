#!/usr/bin/env python3
"""Collect consented teacher traces for a distillation run.

The teacher is the resident Qwen3-30B-A3B-2507 on agx64. The prompts are a
curated operator set, never a vault page or a personal document. Each response
is written as a consented trace row that ``sparknet-distill.py`` can redact and
split into train/val/test.

Usage::

    scripts/sparknet-distill-collect.py \
      --prompts master-node/configs/distill-prompts.jsonl \
      --endpoint http://127.0.0.1:8000/v1/chat/completions \
      --model qwen3-30b \
      --out /mnt/ai/distill/traces

The output is training data, not knowledge. It never enters a vault, 4223 or
an answer corpus.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _post(url: str, body: dict[str, Any], timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("teacher response is not a JSON object")
    return data


def _answer(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else {}
    content = message.get("content") if isinstance(message, dict) else ""
    return str(content or "").strip()


def _load_prompts(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        row = json.loads(line)
        if isinstance(row, dict) and str(row.get("prompt") or "").strip():
            rows.append(row)
    return rows


def collect(
    *,
    prompts: Path,
    endpoint: str,
    model: str,
    out_dir: Path,
    family: str,
    max_prompts: int,
    timeout: float,
    temperature: float,
) -> dict[str, Any]:
    rows = _load_prompts(prompts)
    if max_prompts > 0:
        rows = rows[:max_prompts]
    if not rows:
        raise SystemExit("distill-collect: no prompts")
    out_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    out = out_dir / f"distill-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}.jsonl"
    count = 0
    with out.open("w", encoding="utf-8") as handle:
        for index, row in enumerate(rows):
            prompt = str(row["prompt"]).strip()
            body = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": float(row.get("temperature", temperature)),
                "seed": int(row.get("seed", index)),
                "max_tokens": int(row.get("max_tokens", 512)),
                "stream": False,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            try:
                response = _post(endpoint, body, timeout)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise SystemExit(f"distill-collect: teacher request failed: {exc}") from exc
            answer = _answer(response)
            if not answer:
                raise SystemExit(f"distill-collect: empty teacher answer for prompt {index}")
            trace_id = hashlib.sha256(f"{prompt}\n{answer}".encode()).hexdigest()[:16]
            trace = {
                "schema": "sparknet-distill-trace/1",
                "trace_id": trace_id,
                "model_id": model,
                "family": family,
                "prompt": prompt,
                "response": answer,
                "consent": True,
                "source": "curated-distill-prompts",
                "created_at": _now(),
            }
            handle.write(json.dumps(trace, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    out.chmod(0o600)
    return {"out": str(out), "traces": count, "model": model, "family": family}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="collect consented teacher traces")
    parser.add_argument("--prompts", type=Path, default=Path("master-node/configs/distill-prompts.jsonl"))
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000/v1/chat/completions")
    parser.add_argument("--model", default="qwen3-30b")
    parser.add_argument("--out", type=Path, default=Path("/mnt/ai/distill/traces"))
    parser.add_argument("--family", default="qwen3")
    parser.add_argument("--max", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=600.0)
    parser.add_argument("--temperature", type=float, default=0.7)
    args = parser.parse_args(argv)
    result = collect(
        prompts=args.prompts,
        endpoint=args.endpoint,
        model=args.model,
        out_dir=args.out,
        family=args.family,
        max_prompts=args.max,
        timeout=args.timeout,
        temperature=args.temperature,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
