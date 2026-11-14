#!/usr/bin/env python3
"""Pull and verify the sparknet model catalog.

The catalog is operator data, not a model tool: an LLM cannot call this. Weights
are not knowledge and never enter a vault, a bundle or 4223. The Master (agx64)
pulls teacher candidates; the peer (agx32) pulls student candidates; both may
pull embedding models. A teacher is never eligible for agx32.

Usage::

    scripts/sparknet-model-pull.py --check
    scripts/sparknet-model-pull.py --node agx64 --dry-run
    scripts/sparknet-model-pull.py --node agx64 --model qwen3.6-35b-a3b-q4-k-m
    scripts/sparknet-model-pull.py --node agx32 --verify
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = ROOT / "contracts" / "model-catalog.json"
DEFAULT_STORE = Path(os.environ.get("SPARKNET_MODEL_STORE", "/mnt/ai/models"))
DEFAULT_API_BASE = "https://huggingface.co/api/models"
DEFAULT_RESOLVE_BASE = "https://huggingface.co"
NODES = ("agx64", "agx32")
ROLES = ("teacher", "student", "embedding", "coder", "vision")
CHUNK = 1024 * 1024


class PullError(RuntimeError):
    """A refusal the operator can act on."""


def log(message: str) -> None:
    print(f"[model-pull] {message}", file=sys.stderr, flush=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_catalog(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PullError(f"cannot read catalog {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PullError(f"catalog {path} is not a JSON object")
    return data


def validate_catalog(catalog: dict[str, Any]) -> list[str]:
    """Return every reason the catalog is not safe to act on."""
    errors: list[str] = []
    if catalog.get("schema_version") != "1.0":
        errors.append("schema_version must be 1.0")
    if catalog.get("contract") != "model-catalog":
        errors.append("contract must be model-catalog")
    store = catalog.get("store")
    if not isinstance(store, dict):
        errors.append("store must be an object")
    else:
        if not str(store.get("root") or "").startswith("/"):
            errors.append("store.root must be an absolute path")
        try:
            if int(store.get("min_free_gb", 0)) < 1:
                errors.append("store.min_free_gb must be positive")
        except (TypeError, ValueError):
            errors.append("store.min_free_gb must be an integer")

    models = catalog.get("models")
    if not isinstance(models, list) or not models:
        return [*errors, "models must be a non-empty list"]

    seen: set[str] = set()
    for index, model in enumerate(models):
        label = f"models[{index}]"
        if not isinstance(model, dict):
            errors.append(f"{label} is not an object")
            continue
        model_id = str(model.get("id") or "")
        if not model_id:
            errors.append(f"{label} has no id")
            continue
        if model_id in seen:
            errors.append(f"{model_id}: duplicate id")
        seen.add(model_id)
        role = str(model.get("role") or "")
        if role not in ROLES:
            errors.append(f"{model_id}: role must be one of {ROLES}")
        nodes = model.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            errors.append(f"{model_id}: nodes must be a non-empty list")
            nodes = []
        for node in nodes:
            if node not in NODES:
                errors.append(f"{model_id}: unknown node {node!r}")
        if role == "teacher" and nodes != ["agx64"]:
            errors.append(f"{model_id}: a teacher is eligible only on agx64, not {nodes}")
        if role == "student" and nodes != ["agx32"]:
            errors.append(f"{model_id}: a student is eligible only on agx32, not {nodes}")
        if role == "embedding" and not set(nodes).issubset(set(NODES)):
            errors.append(f"{model_id}: embeddings must name only known nodes")
        if role in ("coder", "vision") and nodes != ["agx32"]:
            errors.append(f"{model_id}: a {role} model is eligible only on agx32, not {nodes}")
        for key in ("family", "generation", "repo", "revision", "format", "runtime", "license", "license_url", "why"):
            if not str(model.get(key) or "").strip():
                errors.append(f"{model_id}: missing {key}")
        include = model.get("include")
        if not isinstance(include, list) or not include:
            errors.append(f"{model_id}: include must be a non-empty list")
        for key in ("size_gb", "fast_memory_gb", "context_tokens"):
            try:
                if float(model.get(key, 0)) <= 0:
                    errors.append(f"{model_id}: {key} must be positive")
            except (TypeError, ValueError):
                errors.append(f"{model_id}: {key} must be numeric")
        if role in ("teacher", "student"):
            try:
                port = int(model.get("serving_port", 0))
                if not 1024 < port < 65536:
                    errors.append(f"{model_id}: serving_port is not a usable local port")
            except (TypeError, ValueError):
                errors.append(f"{model_id}: serving_port must be an integer")
        if model.get("status") not in ("candidate", "active", "retired"):
            errors.append(f"{model_id}: status must be candidate, active or retired")
    return errors


def select_models(catalog: dict[str, Any], node: str, requested: list[str] | None = None) -> list[dict[str, Any]]:
    if node not in NODES:
        raise PullError(f"unknown node {node!r}; expected one of {NODES}")
    models = [m for m in catalog.get("models", []) if node in m.get("nodes", [])]
    if requested:
        wanted = set(requested)
        models = [m for m in models if m.get("id") in wanted]
        missing = wanted - {m.get("id") for m in models}
        if missing:
            raise PullError(f"model(s) not eligible for {node}: {', '.join(sorted(missing))}")
    if not models:
        raise PullError(f"catalog selects no models for {node}")
    return models


def manifest_path(store: Path, model_id: str) -> Path:
    return store / "manifests" / f"{model_id}.json"


def load_manifest(store: Path, model_id: str) -> dict[str, Any] | None:
    path = manifest_path(store, model_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def choose_model_file(files: list[dict[str, Any]]) -> str | None:
    gguf = sorted(row["path"] for row in files if str(row.get("path", "")).lower().endswith(".gguf"))
    return gguf[0] if gguf else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_model(store: Path, model_id: str) -> list[str]:
    manifest = load_manifest(store, model_id)
    if manifest is None:
        return [f"{model_id}: manifest missing"]
    errors: list[str] = []
    if manifest.get("pinned") is not True:
        errors.append(f"{model_id}: manifest is not pinned")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return [*errors, f"{model_id}: manifest has no files"]
    for row in files:
        if not isinstance(row, dict) or not row.get("path"):
            errors.append(f"{model_id}: malformed file row")
            continue
        try:
            path = store / model_id / safe_relpath(row["path"])
        except PullError as exc:
            errors.append(f"{model_id}: {exc}")
            continue
        if not path.is_file():
            errors.append(f"{model_id}: missing {row['path']}")
            continue
        expected = str(row.get("sha256") or "")
        actual = sha256_file(path)
        if expected and actual != expected:
            errors.append(f"{model_id}: hash mismatch for {row['path']}")
        if int(row.get("size") or 0) and path.stat().st_size != int(row["size"]):
            errors.append(f"{model_id}: size mismatch for {row['path']}")
    return errors


def disk_guard(store: Path, min_free_gb: int, needed_bytes: int = 0) -> None:
    store.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(store).free
    required = int(min_free_gb) * 1024**3 + max(0, needed_bytes)
    if free < required:
        raise PullError(
            f"free space at {store} is {free / 1024**3:.1f} GiB; "
            f"need {required / 1024**3:.1f} GiB (min_free_gb={min_free_gb})"
        )


def _request(url: str, token: str | None, timeout: float = 60) -> urllib.request.Request:
    request = urllib.request.Request(url)
    request.add_header("User-Agent", "sparknet-model-pull/1")
    request.add_header("Accept-Encoding", "identity")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    return request


def fetch_json(url: str, token: str | None, timeout: float = 60) -> Any:
    request = _request(url, token)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def resolve_revision(repo: str, revision: str, token: str | None, api_base: str) -> str:
    try:
        data = fetch_json(f"{api_base.rstrip('/')}/{repo}", token)
    except Exception:
        return revision
    if isinstance(data, dict) and isinstance(data.get("sha"), str) and data["sha"]:
        return data["sha"]
    return revision


def safe_relpath(value: Any) -> str:
    path = PurePosixPath(str(value).strip())
    if not path.parts or path.is_absolute() or any(part in ("", "..") for part in path.parts):
        raise PullError(f"unsafe model file path: {value!r}")
    return path.as_posix()


def resolve_files(model: dict[str, Any], token: str | None, api_base: str) -> list[dict[str, Any]]:
    repo = str(model["repo"])
    revision = str(model.get("revision") or "main")
    include = [str(pattern) for pattern in model.get("include", [])]
    url = f"{api_base.rstrip('/')}/{repo}/tree/{urllib.parse.quote(revision, safe='')}?recursive=1"
    try:
        rows = fetch_json(url, token)
    except Exception as exc:
        raise PullError(f"{model['id']}: cannot list {repo}@{revision}: {exc}") from exc
    if not isinstance(rows, list):
        raise PullError(f"{model['id']}: unexpected tree response for {repo}@{revision}")
    selected: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("type") != "file":
            continue
        path = str(row.get("path") or "")
        if not path or not any(fnmatch.fnmatch(path, pattern) for pattern in include):
            continue
        path = safe_relpath(path)
        lfs = row.get("lfs") if isinstance(row.get("lfs"), dict) else {}
        digest = str(lfs.get("oid") or row.get("oid") or "")
        selected.append(
            {
                "path": path,
                "size": int(row.get("size") or 0),
                "sha256": digest if len(digest) == 64 and all(c in "0123456789abcdef" for c in digest.lower()) else "",
            }
        )
    selected.sort(key=lambda row: row["path"])
    if not selected:
        raise PullError(f"{model['id']}: no files matched {include} in {repo}@{revision}")
    return selected


def download_file(
    *,
    repo: str,
    revision: str,
    remote_path: str,
    dest: Path,
    token: str | None,
    expected_sha: str,
    resolve_base: str,
    timeout: float = 300,
) -> tuple[int, str]:
    url = (
        f"{resolve_base.rstrip('/')}/{repo}/resolve/"
        f"{urllib.parse.quote(revision, safe='')}/{urllib.parse.quote(remote_path, safe='/')}"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file() and (not expected_sha or sha256_file(dest) == expected_sha):
        return dest.stat().st_size, expected_sha or sha256_file(dest)

    fd, temp_name = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".part", dir=dest.parent)
    temp = Path(temp_name)
    digest = hashlib.sha256()
    size = 0
    try:
        request = _request(url, token, timeout)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(request, timeout=timeout) as response, os.fdopen(fd, "wb") as handle:
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        actual = digest.hexdigest()
        if expected_sha and actual != expected_sha:
            raise PullError(f"{remote_path}: sha256 {actual} does not match {expected_sha}")
        os.chmod(temp, 0o600)
        os.replace(temp, dest)
        return size, actual
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def write_manifest(store: Path, manifest: dict[str, Any]) -> Path:
    path = manifest_path(store, str(manifest["id"]))
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
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


def pull_model(
    *,
    model: dict[str, Any],
    store: Path,
    node: str,
    min_free_gb: int,
    token: str | None,
    api_base: str,
    resolve_base: str,
    dry_run: bool,
    force: bool,
) -> dict[str, Any]:
    model_id = str(model["id"])
    existing = load_manifest(store, model_id)
    if existing and not force:
        errors = verify_model(store, model_id)
        if not errors:
            log(f"{model_id}: already present and verified")
            return existing
        log(f"{model_id}: existing copy is incomplete; re-pulling")

    revision = str(model.get("revision") or "main")
    resolved = resolve_revision(str(model["repo"]), revision, token, api_base)
    files = resolve_files(model, token, api_base)
    needed = sum(int(row["size"]) for row in files)
    store.mkdir(parents=True, exist_ok=True)
    disk_guard(store, min_free_gb, needed)
    log(f"{model_id}: {len(files)} files, {needed / 1024**3:.1f} GiB, {model['repo']}@{resolved[:12]}")

    if dry_run:
        for row in files:
            print(f"{model_id}\t{row['path']}\t{row['size']}")
        return {"id": model_id, "dry_run": True, "files": files, "resolved_revision": resolved}

    completed: list[dict[str, Any]] = []
    for row in files:
        dest = store / model_id / safe_relpath(row["path"])
        model_root = (store / model_id).resolve()
        try:
            dest.resolve().relative_to(model_root)
        except ValueError as exc:
            raise PullError(f"{model_id}: unsafe destination {dest}") from exc
        size, digest = download_file(
            repo=str(model["repo"]),
            revision=resolved,
            remote_path=row["path"],
            dest=dest,
            token=token,
            expected_sha=str(row.get("sha256") or ""),
            resolve_base=resolve_base,
        )
        completed.append({"path": row["path"], "sha256": digest, "size": size})
        log(f"{model_id}: {row['path']} ({size / 1024**2:.1f} MiB)")

    manifest = {
        "schema": "sparknet-model-manifest/1",
        "id": model_id,
        "family": model.get("family"),
        "generation": model.get("generation"),
        "role": model.get("role"),
        "node": node,
        "repo": model.get("repo"),
        "revision": revision,
        "resolved_revision": resolved,
        "license": model.get("license"),
        "license_url": model.get("license_url"),
        "format": model.get("format"),
        "runtime": model.get("runtime"),
        "context_tokens": model.get("context_tokens"),
        "serving_port": model.get("serving_port"),
        "model_file": choose_model_file(completed),
        "files": completed,
        "total_bytes": sum(int(row["size"]) for row in completed),
        "pinned": True,
        "pulled_at": now_iso(),
        "puller": os.environ.get("SPARKNET_OPERATOR", "operator"),
        "store": str(store),
    }
    path = write_manifest(store, manifest)
    log(f"{model_id}: manifest {path}")
    return manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull and verify sparknet model candidates")
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--node", choices=NODES)
    parser.add_argument("--model", action="append", default=[], help="model id (repeatable)")
    parser.add_argument("--check", action="store_true", help="validate the catalog only")
    parser.add_argument("--verify", action="store_true", help="verify an existing pull")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--resolve-base", default=DEFAULT_RESOLVE_BASE)
    parser.add_argument("--token-file", type=Path, default=None)
    parser.add_argument("--timeout", type=float, default=300)
    return parser.parse_args(argv)


def read_token(path: Path | None) -> str | None:
    if path is not None:
        try:
            return path.expanduser().read_text(encoding="utf-8").strip() or None
        except OSError as exc:
            raise PullError(f"cannot read token file {path}: {exc}") from exc
    return os.environ.get("HF_TOKEN") or None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        catalog = load_catalog(args.catalog)
        errors = validate_catalog(catalog)
        if errors:
            for error in errors:
                print(f"model-catalog: {error}", file=sys.stderr)
            return 1
        if args.check:
            print(f"model-catalog: ok ({len(catalog['models'])} candidates)")
            return 0
        if not args.node:
            raise PullError("--node agx64|agx32 is required unless --check is used")
        models = select_models(catalog, args.node, args.model)
        token = read_token(args.token_file)
        min_free = int(catalog["store"]["min_free_gb"])
        results: list[dict[str, Any]] = []
        failed = False
        for model in models:
            try:
                if args.verify:
                    model_errors = verify_model(args.store, str(model["id"]))
                    if model_errors:
                        failed = True
                        results.append({"id": model["id"], "errors": model_errors})
                        for error in model_errors:
                            log(error)
                    else:
                        results.append({"id": model["id"], "verified": True})
                        log(f"{model['id']}: verified")
                    continue
                results.append(
                    pull_model(
                        model=model,
                        store=args.store,
                        node=args.node,
                        min_free_gb=min_free,
                        token=token,
                        api_base=args.api_base,
                        resolve_base=args.resolve_base,
                        dry_run=args.dry_run,
                        force=args.force,
                    )
                )
            except PullError as exc:
                failed = True
                log(str(exc))
                results.append({"id": model.get("id"), "error": str(exc)})
        if args.json:
            print(json.dumps({"node": args.node, "models": results}, indent=2, sort_keys=True))
        return 1 if failed else 0
    except PullError as exc:
        print(f"model-pull: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
