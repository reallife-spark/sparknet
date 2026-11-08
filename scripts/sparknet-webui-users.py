#!/usr/bin/env python3
"""Open WebUI user audit, migration and Master admin-only enforcement.

The fabric's user policy is deliberately asymmetric:

* **peer** — every human user lives here; signup lands ``pending`` until approved;
* **master** — the human administrator is the only account. Users are supervised
  through the peer's own signed admin channel, never by a second account.

This tool is an operator aid, not an authority path. It can read the WebUI admin
API, stage a user's chats, and (with ``--apply`` and an archive directory) remove
non-admin accounts from a Master WebUI. It never touches a vault, registry,
ledger or key.

Commands::

    audit --webui http://127.0.0.1:8181 --admin-email ... --password-file ...
    export-user --webui ... --user-email ... --out DIR
    import-user --webui ... --container sparknet-webui --user-email ... --dir DIR
    enforce-master --webui ... --admin-email admin@sparknet.local --archive-dir DIR [--apply]

``import-user`` runs the peer's own Open WebUI ORM inside its container. That is
intentional: the public chat-import endpoint assigns to the caller, and an admin
must not impersonate a user just to move one chat. The script stages the exact
chat JSON, backs it up, and records the import in a manifest.
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
from typing import Any

DEFAULT_WEBUI = "http://127.0.0.1:8181"
DEFAULT_ADMIN_EMAIL = "admin@sparknet.local"


def log(message: str) -> None:
    print("[{}] {}".format(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), message), flush=True)


def _request(base: str, path: str, method: str, token: str = "", body: Any = None) -> tuple[int, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    request.add_header("Accept", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=60) as response:
            raw = response.read()
            return response.status, (json.loads(raw.decode("utf-8")) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw.decode("utf-8"))
        except Exception:
            return exc.code, raw.decode("utf-8", "replace")


def _signin(base: str, email: str, password: str) -> str:
    status, body = _request(base, "/api/v1/auths/signin", "POST", body={"email": email, "password": password})
    if status != 200 or not isinstance(body, dict) or not body.get("token"):
        raise SystemExit(f"signin failed: HTTP {status}: {body}")
    return str(body["token"])


def _users(base: str, token: str) -> list[dict[str, Any]]:
    status, body = _request(base, "/api/v1/users/", "GET", token)
    if status != 200:
        raise SystemExit(f"users list failed: HTTP {status}: {body}")
    if isinstance(body, list):
        return body
    if isinstance(body, dict) and isinstance(body.get("users"), list):
        return body["users"]
    if isinstance(body, dict) and isinstance(body.get("items"), list):
        return body["items"]
    return []


def _find_user(users: list[dict[str, Any]], email: str) -> dict[str, Any]:
    wanted = email.strip().lower()
    for user in users:
        if isinstance(user, dict) and str(user.get("email") or "").strip().lower() == wanted:
            return user
    raise SystemExit(f"user not found: {email}")


def _chats_for_user(base: str, token: str, user_id: str) -> list[dict[str, Any]]:
    status, body = _request(base, f"/api/v1/chats/list/user/{user_id}", "GET", token)
    if status != 200:
        raise SystemExit(f"chat list failed: HTTP {status}: {body}")
    if isinstance(body, list):
        return body
    if isinstance(body, dict) and isinstance(body.get("items"), list):
        return body["items"]
    return []


def _full_chat(base: str, token: str, chat_id: str) -> dict[str, Any] | None:
    status, body = _request(base, f"/api/v1/chats/{chat_id}", "GET", token)
    if status != 200 or not isinstance(body, dict):
        log(f"chat {chat_id} could not be exported: HTTP {status}")
        return None
    return body


def cmd_audit(args: argparse.Namespace) -> int:
    token = _signin(args.webui, args.admin_email, Path(args.password_file).read_text().strip())
    users = _users(args.webui, token)
    rows = []
    for user in users:
        user_id = str(user.get("id") or "")
        rows.append(
            {
                "id": user_id,
                "email": user.get("email"),
                "name": user.get("name"),
                "role": user.get("role"),
                "chats": len(_chats_for_user(args.webui, token, user_id)) if user_id else 0,
            }
        )
    print(json.dumps({"webui": args.webui, "users": rows}, indent=2, sort_keys=True))
    return 0


def cmd_export_user(args: argparse.Namespace) -> int:
    token = _signin(args.webui, args.admin_email, Path(args.password_file).read_text().strip())
    user = _find_user(_users(args.webui, token), args.user_email)
    user_id = str(user["id"])
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    os.chmod(out, 0o700)
    chats = []
    for item in _chats_for_user(args.webui, token, user_id):
        chat_id = str(item.get("id") or "")
        if not chat_id:
            continue
        full = _full_chat(args.webui, token, chat_id)
        if full is not None:
            chats.append(full)
    payload = {
        "schema": "sparknet-webui-user-export/1",
        "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user": user,
        "chats": chats,
    }
    path = out / "user-export.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(path, 0o600)
    log(f"exported {len(chats)} chat(s) for {args.user_email} to {path}")
    return 0


IMPORT_SNIPPET = r"""
import asyncio, json, sys
from open_webui.models.chats import Chats, ChatImportForm

payload = json.load(sys.stdin)
user_id = payload["user_id"]
imported = []
async def main():
    for row in payload["chats"]:
        form = ChatImportForm(
            chat=row.get("chat") or {},
            variables=row.get("variables") or {},
            folder_id=None,
            meta=row.get("meta") or {},
            pinned=bool(row.get("pinned") or False),
            archived=bool(row.get("archived") or False),
            current_message_id=row.get("current_message_id"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
        result = await Chats.import_chats(user_id, [form])
        imported.extend([item.id for item in result])
    print(json.dumps({"ok": True, "imported": imported}))
asyncio.run(main())
"""


def cmd_import_user(args: argparse.Namespace) -> int:
    token = _signin(args.webui, args.admin_email, Path(args.password_file).read_text().strip())
    user = _find_user(_users(args.webui, token), args.user_email)
    user_id = str(user["id"])
    export_path = Path(args.dir).resolve() / "user-export.json"
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    chats = payload.get("chats") if isinstance(payload, dict) else None
    if not isinstance(chats, list) or not chats:
        log("no chats to import")
        return 0
    body = json.dumps({"user_id": user_id, "chats": chats}, ensure_ascii=False).encode("utf-8")
    # The WebUI app requires WEBUI_SECRET_KEY at import time. A `docker exec`
    # process does not inherit the container's start environment, so read the
    # value from the running container (never print it) and pass it through.
    secret = os.environ.get("SPARKNET_WEBUI_SECRET_KEY", "").strip()
    if not secret:
        inspected = subprocess.run(
            ["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", args.container],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        for line in inspected.stdout.decode("utf-8", "replace").splitlines():
            if line.startswith("WEBUI_SECRET_KEY="):
                secret = line.split("=", 1)[1].strip()
                break
    if not secret:
        # Open WebUI's start script writes the auto-generated key here when the
        # environment value is empty. A `docker exec` process does not inherit
        # that file automatically.
        read = subprocess.run(
            ["docker", "exec", args.container, "cat", "/app/backend/.webui_secret_key"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if read.returncode == 0:
            secret = read.stdout.decode("utf-8", "replace").strip()
    command = ["docker", "exec", "-i"]
    child_env = dict(os.environ)
    if secret:
        # Pass the name only; docker reads the value from this process's
        # environment, so it never appears in argv or /proc/<pid>/cmdline.
        command += ["-e", "WEBUI_SECRET_KEY"]
        child_env["WEBUI_SECRET_KEY"] = secret
    command += [args.container, "python3", "-c", IMPORT_SNIPPET]
    completed = subprocess.run(command, input=body, capture_output=True, check=False, env=child_env)
    if completed.returncode != 0:
        raise SystemExit("container import failed: {}".format(completed.stderr.decode("utf-8", "replace")))
    log("imported chats: {}".format(completed.stdout.decode("utf-8", "replace").strip()))
    manifest = Path(args.dir).resolve() / "import-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "sparknet-webui-user-import/1",
                "imported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "target_user_id": user_id,
                "source_user_id": (payload.get("user") or {}).get("id"),
                "chats": len(chats),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    os.chmod(manifest, 0o600)
    return 0


def cmd_enforce_master(args: argparse.Namespace) -> int:
    token = _signin(args.webui, args.admin_email, Path(args.password_file).read_text().strip())
    users = _users(args.webui, token)
    admin = [u for u in users if str(u.get("email") or "").lower() == args.admin_email.lower()]
    if len(admin) != 1:
        raise SystemExit(f"expected exactly one {args.admin_email} account, found {len(admin)}")
    others = [u for u in users if str(u.get("role")) != "admin"]
    if not others:
        log("master WebUI is admin-only")
        return 0
    archive = Path(args.archive_dir).resolve()
    archive.mkdir(parents=True, exist_ok=True)
    os.chmod(archive, 0o700)
    report = []
    for user in others:
        user_id = str(user.get("id") or "")
        chats = _chats_for_user(args.webui, token, user_id)
        staging = archive / (str(user.get("email") or user_id).replace("@", "_at_"))
        staging.mkdir(parents=True, exist_ok=True)
        os.chmod(staging, 0o700)
        (staging / "user.json").write_text(json.dumps(user, indent=2, ensure_ascii=False), encoding="utf-8")
        for item in chats:
            chat_id = str(item.get("id") or "")
            full = _full_chat(args.webui, token, chat_id) if chat_id else None
            if full is not None:
                (staging / (f"chat-{chat_id}.json")).write_text(
                    json.dumps(full, indent=2, ensure_ascii=False), encoding="utf-8"
                )
        report.append({"email": user.get("email"), "id": user_id, "chats": len(chats)})
        if args.apply:
            status, body = _request(args.webui, f"/api/v1/users/{user_id}", "DELETE", token)
            if status != 200:
                raise SystemExit("delete {} failed: HTTP {}: {}".format(user.get("email"), status, body))
    print(
        json.dumps(
            {"archive": str(archive), "removed": report if args.apply else [], "dry_run": not args.apply}, indent=2
        )
    )
    return 0


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sparknet-webui-users", description="Open WebUI user audit and Master admin-only enforcement"
    )
    p.add_argument("--webui", default=os.environ.get("SPARKNET_WEBUI", DEFAULT_WEBUI))
    p.add_argument("--admin-email", default=os.environ.get("SPARKNET_WEBUI_ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL))
    p.add_argument("--password-file", default=os.environ.get("SPARKNET_WEBUI_ADMIN_PASSWORD_FILE", ""))
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("audit")
    export = sub.add_parser("export-user")
    export.add_argument("--user-email", required=True)
    export.add_argument("--out", required=True)
    imp = sub.add_parser("import-user")
    imp.add_argument("--container", default="sparknet-webui")
    imp.add_argument("--user-email", required=True)
    imp.add_argument("--dir", required=True)
    enforce = sub.add_parser("enforce-master")
    enforce.add_argument("--archive-dir", required=True)
    enforce.add_argument("--apply", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.password_file:
        raise SystemExit("--password-file is required")
    if args.command == "audit":
        return cmd_audit(args)
    if args.command == "export-user":
        return cmd_export_user(args)
    if args.command == "import-user":
        return cmd_import_user(args)
    if args.command == "enforce-master":
        return cmd_enforce_master(args)
    raise SystemExit("unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
