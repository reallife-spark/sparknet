#!/usr/bin/env python3
"""Survey the open-weight catalog and the node's live Ollama inventory.

The survey is read-only until `run`: it never pulls, promotes or deletes a
model. `run` loads each selected model through the same fixed suite used by the
bake-off harness, then writes a report. Model weights stay on the host store and
never enter a vault, bundle or 4223.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
from sparknet_loader import load_by_path  # noqa: E402 - shared/ is added by path above

CATALOG = ROOT / "contracts" / "model-catalog.json"
STORE = Path(os.environ.get("SPARKNET_MODEL_STORE", "/mnt/ai/models"))
BENCH = ROOT / "scripts" / "sparknet-model-bench.py"
ROLE_CONFIG = {
    "agx64": ROOT / "master-node" / "configs" / "model-runtime" / "bakeoff.json",
    "agx32": ROOT / "peer-node" / "configs" / "model-runtime" / "bakeoff.json",
}
OLLAMA = "http://127.0.0.1:11434"
NODE_MEMORY_GB = {"agx64": 64, "agx32": 32}
MEMORY_SAFETY_GB = 6

#: Catalog ids whose live Ollama tag is not just `<id>:latest`.
LIVE_ALIASES = {
    "qwen3.6-35b-a3b-q4-k-m": "qwen3.6-35b-262k:latest",
    "qwen3.6-35b-a3b-q8": "qwen3.6-35b-262k-q8:latest",
    "qwen3.8-27b-q4": "qwen3.8-27b-q4:latest",
    "qwen3.5-9b-q8": "qwen3.5-9b-q8:latest",
    "qwen3.6-27b-q4-k-m": "qwen3.6-27b-q4:latest",
    "qwen3-32b-q4-k-m": "qwen3-32b-q4:latest",
    "qwen3-0.6b-q8": "qwen3-0.6b-q8:latest",
    "qwen3-embedding-0.6b": "qwen3-embedding:latest",
    "qwen3-30b-a3b-2507-q4-k-m": "qwen3-30b-2507:latest",
    "qwen3-4b-2507-q4-k-m": "qwen3-4b-2507:latest",
    "qwen3-coder-30b-a3b-q4-k-m": "qwen3-coder-30b-65k:latest",
    "qwen3-embedding-0.6b-q8": "qwen3-embedding-0.6b:latest",
    "qwen3-vl-4b-q4-k-m": "qwen3-vl-4b-65k:latest",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"model-survey: cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"model-survey: {path} is not an object")
    return data


def bench_module() -> Any:
    return load_by_path(
        "sparknet_model_bench_survey", BENCH, error=SystemExit, message=f"model-survey: cannot load {BENCH}"
    )


def get_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise SystemExit(f"model-survey: cannot read {url}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def post_json(url: str, body: dict[str, Any], timeout: float = 120.0) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise SystemExit(f"model-survey: cannot read {url}: {exc}") from exc
    return data if isinstance(data, dict) else {}


def catalog_models(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    models = catalog.get("models")
    if not isinstance(models, list):
        raise SystemExit("model-survey: catalog has no models list")
    return [model for model in models if isinstance(model, dict)]


def manifests(store: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    root = store / "manifests"
    if not root.is_dir():
        return result
    for path in sorted(root.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("id"):
            result[str(data["id"])] = data
    return result


def live_tags(base_url: str) -> list[dict[str, Any]]:
    data = get_json(base_url.rstrip("/") + "/api/tags")
    rows = data.get("models")
    if not isinstance(rows, list):
        return []
    return [
        {
            "name": str(row.get("name") or ""),
            "digest": str(row.get("digest") or ""),
            "size_gb": round(float(row.get("size") or 0) / 1024**3, 1),
            "modified_at": row.get("modified_at"),
        }
        for row in rows
        if isinstance(row, dict) and row.get("name")
    ]


def tag_for(model_id: str, tags: list[dict[str, Any]]) -> str | None:
    explicit = LIVE_ALIASES.get(model_id)
    names = {row["name"] for row in tags}
    if explicit and explicit in names:
        return explicit
    for candidate in (f"{model_id}:latest", model_id):
        if candidate in names:
            return candidate
    return None


def role_config(node: str) -> dict[str, Any]:
    path = ROLE_CONFIG[node]
    return load_json(path) if path.is_file() else {}


def survey(
    catalog: dict[str, Any], store: Path, node: str, base_url: str, include_untracked: bool = False
) -> dict[str, Any]:
    error = None
    try:
        tags = live_tags(base_url)
    except SystemExit as exc:
        tags = []
        error = str(exc)
    tag_names = {row["name"]: row for row in tags}
    known = manifests(store)
    models = []
    mapped_tags: set[str] = set()
    for model in catalog_models(catalog):
        model_id = str(model.get("id") or "")
        live = tag_for(model_id, tags)
        if live:
            mapped_tags.add(live)
        manifest = known.get(model_id)
        size_gb = float(model.get("size_gb") or 0)
        fast_gb = float(model.get("fast_memory_gb") or size_gb)
        skip = None
        if node not in model.get("nodes", []):
            skip = "not_eligible_for_node"
        elif model.get("runtime_note") and "blocked" in str(model["runtime_note"]).lower():
            skip = "runtime_unsupported"
        elif not live:
            skip = "not_imported"
        elif fast_gb + MEMORY_SAFETY_GB > NODE_MEMORY_GB[node]:
            skip = "memory_fit"
        models.append(
            {
                "catalog_id": model_id,
                "live_tag": live,
                "role": model.get("role"),
                "family": model.get("family"),
                "license": model.get("license"),
                "runtime": model.get("runtime"),
                "format": model.get("format"),
                "size_gb": size_gb,
                "fast_memory_gb": fast_gb,
                "context_tokens": model.get("context_tokens"),
                "status": model.get("status"),
                "manifest": manifest,
                "manifest_pinned": bool(manifest and manifest.get("pinned")),
                "digest": (tag_names.get(live) or {}).get("digest") if live else None,
                "skip": skip,
            }
        )
    untracked = []
    if include_untracked:
        for row in tags:
            if row["name"] in mapped_tags:
                continue
            skip = "memory_fit" if row["size_gb"] + MEMORY_SAFETY_GB > NODE_MEMORY_GB[node] else None
            untracked.append(
                {
                    "catalog_id": None,
                    "live_tag": row["name"],
                    "role": "untracked",
                    "digest": row["digest"],
                    "size_gb": row["size_gb"],
                    "status": "untracked",
                    "skip": skip,
                }
            )
    return {
        "node": node,
        "generated_at": now_iso(),
        "error": error,
        "catalog": models,
        "untracked": untracked,
        "tags": tags,
    }


def plan(survey_doc: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for row in survey_doc.get("catalog", []):
        if row.get("skip"):
            rows.append({**row, "action": "skip"})
            continue
        if row.get("role") == "embedding":
            rows.append({**row, "action": "embedding"})
        else:
            rows.append({**row, "action": "benchmark"})
    for row in survey_doc.get("untracked", []):
        rows.append({**row, "action": "benchmark"})
    return {"node": survey_doc.get("node"), "generated_at": now_iso(), "rows": rows, "counts": _counts(rows)}


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        action = str(row.get("action"))
        counts[action] = counts.get(action, 0) + 1
    return counts


def embedding_probe(base_url: str, model: str, timeout: float = 120.0) -> dict[str, Any]:
    started = time.perf_counter()
    data = post_json(
        base_url.rstrip("/") + "/api/embeddings",
        {"model": model, "prompt": "sparknet model survey embedding probe"},
        timeout=timeout,
    )
    elapsed = time.perf_counter() - started
    vector = data.get("embedding")
    return {
        "id": model,
        "model": model,
        "role": "embedding",
        "dimension": len(vector) if isinstance(vector, list) else None,
        "latency_s": round(elapsed, 3),
        "ok": isinstance(vector, list) and bool(vector),
    }


def run(
    survey_doc: dict[str, Any], node: str, base_url: str, *, dry_run: bool, only: list[str] | None
) -> dict[str, Any]:
    plan_doc = plan(survey_doc)
    config = role_config(node)
    provider = {"kind": "ollama", "base_url": base_url}
    prompts = config.get("prompts") or []
    options = {
        "runs": 1,
        **(config.get("options") or {}),
    }
    bench = bench_module()
    results = []
    for row in plan_doc["rows"]:
        if only and row.get("catalog_id") not in only and row.get("live_tag") not in only:
            continue
        if row["action"] == "skip":
            results.append({**row, "skipped": True})
            continue
        if dry_run:
            results.append({**row, "dry_run": True})
            continue
        if row["action"] == "embedding":
            results.append({**row, "result": embedding_probe(base_url, str(row["live_tag"]))})
            continue
        if not prompts:
            results.append({**row, "error": "no benchmark prompts configured"})
            continue
        candidate = {"id": row.get("catalog_id") or row["live_tag"], "model": row["live_tag"], "role": row.get("role")}
        try:
            summary = bench.measure(
                candidate=candidate,
                provider=provider,
                options=options,
                prompts=prompts,
                timeout=float(options.get("timeout_seconds", 600)),
            )
            results.append({**row, "result": summary})
        except Exception as exc:
            results.append({**row, "error": str(exc)})
    return {"schema": "sparknet-model-survey/1", "node": node, "generated_at": now_iso(), "results": results}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="survey open-weight models in the catalog and live Ollama store")
    parser.add_argument("command", choices=("inventory", "plan", "run", "report"))
    parser.add_argument("--node", choices=("agx64", "agx32"), default="agx32")
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--ollama-url", default=OLLAMA)
    parser.add_argument("--include-untracked", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    catalog = load_json(args.catalog)
    survey_doc = survey(catalog, args.store, args.node, args.ollama_url, args.include_untracked)
    if args.command == "inventory":
        output = survey_doc
    elif args.command == "plan":
        output = plan(survey_doc)
    else:
        output = run(survey_doc, args.node, args.ollama_url, dry_run=args.dry_run, only=args.model or None)
    text = json.dumps(output, indent=2, sort_keys=True) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"model-survey: wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
