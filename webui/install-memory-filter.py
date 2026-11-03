#!/usr/bin/env python3
"""Install the Sparknet memory filter as an Open WebUI Filter Function.

This is an admin-token operation against the node's own loopback WebUI. The
filter content is read from `webui/functions/sparknet_memory_filter.py`; its
Valves default to the memory gateway URL and the WebUI service token supplied by
the node's generated env-file.

Usage::

    webui/install-memory-filter.py --webui http://127.0.0.1:8181 \
      --email admin@sparknet.local --password-file .state/webui-admin-password

The WebUI API is pinned to 0.12.x; a path or shape change is a refusal, not a
silent no-op.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FUNCTION = HERE / "functions" / "sparknet_memory_filter.py"
if not FUNCTION.is_file():
    FUNCTION = HERE.parent / "shared" / "sparknet-memory-filter.py"
FUNCTION_ID = "sparknet-memory"


def _load_provisioner() -> Any:
    path = ROOT / "peer-node" / "services" / "sparknet-vault-provisioner.py"
    if not path.is_file():
        raise SystemExit(f"missing provisioner at {path}")
    spec = importlib.util.spec_from_file_location("_sparknet_provisioner_filter", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _request(base: str, path: str, method: str, token: str, body: Any = None) -> tuple[int, Any]:
    import urllib.error
    import urllib.request

    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    request.add_header("Accept", "application/json")
    request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=60) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode("utf-8")) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode("utf-8"))
        except Exception:
            return exc.code, raw.decode("utf-8", "replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="install the Sparknet memory filter into Open WebUI")
    parser.add_argument("--webui", default="http://127.0.0.1:8181")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password-file", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    content = FUNCTION.read_text(encoding="utf-8")
    payload = {
        "id": FUNCTION_ID,
        "name": "Sparknet Memory",
        "type": "filter",
        "content": content,
        "meta": {"description": "Per-vault Sparknet memory recall and turn capture", "manifest": {}},
    }
    if args.dry_run:
        print(json.dumps({**payload, "content": f"<{len(content)} bytes>"}, indent=2))
        return 0
    provisioner = _load_provisioner()
    password = Path(args.password_file).read_text(encoding="utf-8").strip()
    token = provisioner.webui_token(args.webui, args.email, password)
    status, body = _request(args.webui, "/api/v1/functions/create", "POST", token, payload)
    if status not in (200, 201):
        print(f"install-memory-filter: refused: HTTP {status}: {body}", file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "id": FUNCTION_ID, "response": body}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
