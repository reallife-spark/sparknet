#!/usr/bin/env python3
"""Index a vault's knowledge pages into per-vault semantic memory.

Only `04_Evergreen/`, `05_Knowledge/` and `06_Projects/` are read. Daily notes,
sources, system files, raw captures and state are excluded by the Go indexer.
The gateway narrows the request to the selected vault before the store is
touched; this CLI never reads a memory store directly.

    sparknet-memory-index.py --vault . --user U-12345
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _token(vault: Path) -> str:
    state = Path(os.environ.get("SPARKNET_STATE_DIR", "").strip() or vault / ".state")
    try:
        return (state / "memory.local.token").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def call(vault: Path, body: dict[str, Any]) -> tuple[int, Any]:
    token = _token(vault)
    if not token:
        raise SystemExit("missing memory.local.token; run the node setup first")
    base = os.environ.get("SPARKNET_MEMORY_GATEWAY_URL", "http://127.0.0.1:4093").rstrip("/")
    request = urllib.request.Request(base + "/v1/memory/index", data=json.dumps(body).encode(), method="POST")
    request.add_header("Accept", "application/json")
    request.add_header("Content-Type", "application/json")
    request.add_header("X-Sparknet-Local-Token", token)
    request.add_header("X-Sparknet-Vault-Path", str(vault))
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=120) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode("utf-8"))
        except Exception:
            return exc.code, {"ok": False, "error": raw.decode("utf-8", "replace")}
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return 503, {"ok": False, "error": str(exc)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="index vault knowledge pages into semantic memory")
    parser.add_argument("--vault", default=".")
    parser.add_argument("--user", default=os.environ.get("SPARKNET_OWNER_ID", ""))
    parser.add_argument("--project", default="")
    parser.add_argument("--max-bytes", type=int, default=256 * 1024)
    args = parser.parse_args(argv)
    vault = Path(args.vault).expanduser().resolve()
    status, payload = call(
        vault,
        {
            "vault_path": str(vault),
            "user_id": args.user,
            "project_id": args.project,
            "max_bytes": args.max_bytes,
        },
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if status < 400 else 2


if __name__ == "__main__":
    raise SystemExit(main())
