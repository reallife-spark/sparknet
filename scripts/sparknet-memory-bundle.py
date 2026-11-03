#!/usr/bin/env python3
"""Export, validate, stage and import a per-vault memory bundle.

A bundle is a bounded JSON document (`sparknet-memory-bundle/1`) containing
records from one vault. It is the payload a `session-handoff` or `kb-share` may
carry; it is never a new share type and never bypasses inbox acceptance.

    sparknet-memory-bundle.py export --vault . --out bundle.json
    sparknet-memory-bundle.py validate bundle.json
    sparknet-memory-bundle.py stage --bundle bundle.json --inbox 01_Inbox/share-abc
    sparknet-memory-bundle.py import --vault . --bundle bundle.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

SCHEMA = "sparknet-memory-bundle/1"


def _state(vault: Path) -> Path:
    explicit = os.environ.get("SPARKNET_STATE_DIR", "").strip()
    return Path(explicit) if explicit else vault / ".state"


def _token(vault: Path) -> str:
    try:
        return (_state(vault) / "memory.local.token").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def call(vault: Path, method: str, path: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    token = _token(vault)
    if not token:
        raise SystemExit("missing memory.local.token; run the node setup first")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    base = os.environ.get("SPARKNET_MEMORY_GATEWAY_URL", "http://127.0.0.1:4093").rstrip("/")
    request = urllib.request.Request(base + path, data=data, method=method)
    request.add_header("Accept", "application/json")
    request.add_header("X-Sparknet-Local-Token", token)
    request.add_header("X-Sparknet-Vault-Path", str(vault))
    if data is not None:
        request.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode("utf-8"))
        except Exception:
            return exc.code, {"ok": False, "error": raw.decode("utf-8", "replace")}
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return 503, {"ok": False, "error": str(exc)}


def validate_bundle(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SystemExit("bundle must be a JSON object")
    if value.get("schema") != SCHEMA:
        raise SystemExit(f"bundle schema must be {SCHEMA}")
    records = value.get("records")
    if not isinstance(records, list):
        raise SystemExit("bundle.records must be a list")
    if len(records) > 5000:
        raise SystemExit("bundle carries more than 5000 records")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise SystemExit(f"record {index} is not an object")
        if record.get("memory_type") == "short_term":
            raise SystemExit("a bundle must never carry short_term/cache records")
        if record.get("memory_type") not in {"episodic", "semantic", "procedural", "shared"}:
            raise SystemExit(f"record {index} has an unknown memory_type")
    return value


def cmd_export(args: argparse.Namespace) -> int:
    vault = Path(args.vault).expanduser().resolve()
    status, payload = call(vault, "POST", "/v1/memory/export", {"vault_path": str(vault)})
    if status >= 400 or not isinstance(payload, dict):
        print(json.dumps(payload, indent=2), file=sys.stderr)
        return 2
    validate_bundle(payload)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out), "records": len(payload.get("records") or [])}, indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.bundle).expanduser()
    bundle = json.loads(path.read_text(encoding="utf-8"))
    validate_bundle(bundle)
    print(json.dumps({"ok": True, "vault_id": bundle.get("vault_id"), "records": len(bundle["records"])}, indent=2))
    return 0


def cmd_stage(args: argparse.Namespace) -> int:
    path = Path(args.bundle).expanduser()
    bundle = validate_bundle(json.loads(path.read_text(encoding="utf-8")))
    inbox = Path(args.inbox).expanduser()
    inbox.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = inbox / "memory-bundle.json"
    destination.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(destination, 0o600)
    print(json.dumps({"ok": True, "staged": str(destination)}, indent=2))
    return 0


def cmd_import(args: argparse.Namespace) -> int:
    vault = Path(args.vault).expanduser().resolve()
    bundle = validate_bundle(json.loads(Path(args.bundle).expanduser().read_text(encoding="utf-8")))
    status, payload = call(
        vault,
        "POST",
        "/v1/memory/import",
        {"vault_path": str(vault), "bundle": bundle, "replace": bool(args.replace)},
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if status < 400 else 2


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="manage per-vault memory bundles")
    sub = p.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="export this vault's records")
    export.add_argument("--vault", default=".")
    export.add_argument("--out", required=True)
    export.set_defaults(func=cmd_export)
    validate = sub.add_parser("validate", help="validate a bundle without importing")
    validate.add_argument("bundle")
    validate.set_defaults(func=cmd_validate)
    stage = sub.add_parser("stage", help="stage a bundle in a share inbox")
    stage.add_argument("--bundle", required=True)
    stage.add_argument("--inbox", required=True)
    stage.set_defaults(func=cmd_stage)
    import_cmd = sub.add_parser("import", help="import an accepted bundle")
    import_cmd.add_argument("--vault", default=".")
    import_cmd.add_argument("--bundle", required=True)
    import_cmd.add_argument("--replace", action="store_true")
    import_cmd.set_defaults(func=cmd_import)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
