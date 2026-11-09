#!/usr/bin/env python3
"""Promote or roll back a verified model manifest.

The pull/verify tool writes pinned manifests; this tool records which manifest is
active on a node, keeps the previous one for rollback, and refuses a promotion
without a passing benchmark result. It never downloads, starts or deletes weights.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))
from sparknet_loader import load_by_path  # noqa: E402 - shared/ is added by path above

STORE = Path(os.environ.get("SPARKNET_MODEL_STORE", "/mnt/ai/models"))
CATALOG = ROOT / "contracts" / "model-catalog.json"
PULL = ROOT / "scripts" / "sparknet-model-pull.py"
MIN_QUALITY = 0.8


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"model-update: cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"model-update: {path} is not an object")
    return data


def pull_module() -> Any:
    return load_by_path(
        "sparknet_model_pull_update", PULL, error=SystemExit, message=f"model-update: cannot load {PULL}"
    )


def state_path(store: Path, node: str) -> Path:
    return store / "state" / f"{node}.json"


def load_state(store: Path, node: str) -> dict[str, Any]:
    path = state_path(store, node)
    if not path.is_file():
        return {"schema": "sparknet-model-state/1", "node": node, "active": None, "previous": None, "candidate": None}
    return load_json(path)


def write_state(store: Path, node: str, state: dict[str, Any]) -> Path:
    path = state_path(store, node)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    state["updated_at"] = now_iso()
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return path


def verify_manifest(store: Path, manifest_path: Path, model_id: str) -> dict[str, Any]:
    manifest = load_json(manifest_path)
    if str(manifest.get("id") or "") != model_id:
        raise SystemExit(f"model-update: manifest id {manifest.get('id')!r} does not match {model_id!r}")
    if manifest.get("pinned") is not True:
        raise SystemExit("model-update: manifest is not pinned")
    pull = pull_module()
    errors = pull.verify_model(store, model_id)
    if errors:
        raise SystemExit("model-update: " + "; ".join(errors))
    return manifest


def check(node: str, store: Path, catalog_path: Path, *, verify: bool = False) -> dict[str, Any]:
    pull = pull_module()
    catalog = pull.load_catalog(catalog_path)
    errors = pull.validate_catalog(catalog)
    if errors:
        raise SystemExit("model-update: " + "; ".join(errors))
    rows = []
    for model in pull.select_models(catalog, node):
        model_id = str(model["id"])
        manifest = pull.load_manifest(store, model_id)
        if manifest is None:
            problems = ["manifest missing"]
        elif verify:
            problems = pull.verify_model(store, model_id)
        else:
            problems = [] if manifest.get("pinned") is True else ["manifest is not pinned"]
        rows.append(
            {
                "id": model_id,
                "role": model.get("role"),
                "status": model.get("status"),
                "manifest": bool(manifest),
                "pinned": bool(manifest and manifest.get("pinned")),
                "revision": (manifest or {}).get("resolved_revision") or (manifest or {}).get("revision"),
                "problems": problems,
            }
        )
    return {"node": node, "catalog": str(catalog_path), "models": rows}


def set_candidate(node: str, store: Path, model_id: str, manifest_path: Path) -> dict[str, Any]:
    verify_manifest(store, manifest_path, model_id)
    state = load_state(store, node)
    state["candidate"] = {"id": model_id, "manifest": str(manifest_path), "set_at": now_iso()}
    path = write_state(store, node, state)
    return {"ok": True, "node": node, "candidate": state["candidate"], "state": str(path)}


def promote(node: str, store: Path, model_id: str, operator: str, bench_path: Path) -> dict[str, Any]:
    state = load_state(store, node)
    candidate = state.get("candidate")
    if not isinstance(candidate, dict) or candidate.get("id") != model_id:
        raise SystemExit("model-update: candidate does not match the requested model")
    if state.get("active") and state["active"].get("id") == model_id:
        raise SystemExit("model-update: model is already active")
    bench = load_json(bench_path)
    rows = bench.get("candidates") if isinstance(bench.get("candidates"), list) else [bench]
    result = next((row for row in rows if isinstance(row, dict) and row.get("id") == model_id), None)
    if result is None:
        raise SystemExit("model-update: benchmark does not name the requested model")
    if result.get("error"):
        raise SystemExit(f"model-update: benchmark failed: {result['error']}")
    quality = result.get("quality_pass_rate")
    if not isinstance(quality, (int, float)) or quality < MIN_QUALITY:
        raise SystemExit(f"model-update: quality {quality!r} is below {MIN_QUALITY}")
    if not operator.strip():
        raise SystemExit("model-update: operator is required")
    state["previous"] = state.get("active")
    state["active"] = {
        "id": model_id,
        "manifest": candidate["manifest"],
        "promoted_at": now_iso(),
        "operator": operator,
    }
    state["candidate"] = None
    path = write_state(store, node, state)
    return {"ok": True, "node": node, "active": state["active"], "previous": state["previous"], "state": str(path)}


def rollback(node: str, store: Path, operator: str) -> dict[str, Any]:
    state = load_state(store, node)
    previous = state.get("previous")
    active = state.get("active")
    if not isinstance(previous, dict) or not isinstance(active, dict):
        raise SystemExit("model-update: both active and previous are required for rollback")
    if not operator.strip():
        raise SystemExit("model-update: operator is required")
    state["active"] = {**previous, "promoted_at": now_iso(), "operator": operator}
    state["previous"] = active
    path = write_state(store, node, state)
    return {"ok": True, "node": node, "active": state["active"], "previous": state["previous"], "state": str(path)}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="promote or roll back a verified model manifest")
    parser.add_argument("command", choices=("status", "check", "set-candidate", "promote", "rollback"))
    parser.add_argument("--node", choices=("agx64", "agx32"), required=True)
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--catalog", type=Path, default=CATALOG)
    parser.add_argument("--model", default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--bench", type=Path, default=None)
    parser.add_argument("--operator", default=os.environ.get("USER", ""))
    parser.add_argument("--verify", action="store_true", help="re-hash every model file (slow)")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "status":
        output = load_state(args.store, args.node)
    elif args.command == "check":
        output = check(args.node, args.store, args.catalog, verify=args.verify)
    elif args.command == "set-candidate":
        if not args.model or not args.manifest:
            raise SystemExit("model-update: set-candidate needs --model and --manifest")
        output = set_candidate(args.node, args.store, args.model, args.manifest)
    elif args.command == "promote":
        if not args.model or not args.bench:
            raise SystemExit("model-update: promote needs --model and --bench")
        output = promote(args.node, args.store, args.model, args.operator, args.bench)
    else:
        output = rollback(args.node, args.store, args.operator)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
