#!/usr/bin/env python3
"""On-demand model runtime leases for a sparknet node.

Open WebUI, Qdrant and the fabric services stay resident. A large model runtime
is a warm lease: it is started explicitly, health-checked, and stopped when its
idle window expires. A model cannot call this; only an operator or the local UI
may. The teacher is eligible only on the peer (agx64); the student only on the
Master (agx32).

Usage::

    scripts/sparknet-model-runtime.py status --role peer
    scripts/sparknet-model-runtime.py start teacher --role peer
    scripts/sparknet-model-runtime.py stop teacher --role peer
    scripts/sparknet-model-runtime.py reap --role master --interval 60
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = ROOT / "contracts" / "model-catalog.json"
DEFAULT_STORE = Path(os.environ.get("SPARKNET_MODEL_STORE", "/mnt/ai/models"))
ROLE_CONFIG = {
    "peer": ROOT / "peer-node" / "configs" / "model-runtime" / "runtime.json",
    "master": ROOT / "master-node" / "configs" / "model-runtime" / "runtime.json",
}
NODES = {"peer": "agx64", "master": "agx32"}
SCHEMA = "sparknet-model-runtime/1"


class Refusal(RuntimeError):
    """A refusal the operator can act on."""


def log(message: str) -> None:
    print(f"[model-runtime] {message}", file=sys.stderr, flush=True)


def now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now().isoformat(timespec="seconds").replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Refusal(f"cannot read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise Refusal(f"{path} is not a JSON object")
    return data


def catalog_by_id(path: Path) -> dict[str, dict[str, Any]]:
    catalog = load_json(path)
    models = catalog.get("models")
    if not isinstance(models, list):
        raise Refusal(f"{path} has no models list")
    return {str(model.get("id")): model for model in models if isinstance(model, dict)}


def default_state(role: str) -> Path:
    explicit = os.environ.get("SPARKNET_MODEL_RUNTIME_STATE", "").strip()
    if explicit:
        return Path(explicit)
    state = os.environ.get("SPARKNET_STATE_DIR", "").strip()
    if state:
        return Path(state) / "model-runtime"
    return Path.home() / ".local" / "state" / "sparknet" / role / "model-runtime"


def validate_config(config: dict[str, Any], role: str, catalog: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    if config.get("schema") != SCHEMA:
        errors.append(f"schema must be {SCHEMA}")
    if config.get("role") != role:
        errors.append(f"role must be {role}")
    node = str(config.get("node") or "")
    if node != NODES[role]:
        errors.append(f"node must be {NODES[role]} for role {role}")
    defaults = config.get("defaults")
    if not isinstance(defaults, dict):
        errors.append("defaults must be an object")
        defaults = {}
    for key in ("idle_stop_minutes", "min_free_gb", "health_timeout_seconds", "memory_safety_gb"):
        try:
            if float(defaults.get(key, 0)) < 0:
                errors.append(f"defaults.{key} must not be negative")
        except (TypeError, ValueError):
            errors.append(f"defaults.{key} must be numeric")
    profiles = config.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        return [*errors, "profiles must be a non-empty object"]
    for name, profile in profiles.items():
        label = f"profiles.{name}"
        if not isinstance(profile, dict):
            errors.append(f"{label} must be an object")
            continue
        model_id = str(profile.get("model_id") or "")
        model = catalog.get(model_id)
        if model is None:
            errors.append(f"{label}: unknown model_id {model_id!r}")
        else:
            if node not in model.get("nodes", []):
                errors.append(f"{label}: model {model_id} is not eligible for {node}")
            expected_role = "teacher" if role == "peer" else "student"
            if model.get("role") != expected_role:
                errors.append(f"{label}: model {model_id} is {model.get('role')}, not {expected_role}")
        for key in ("compose_file", "project", "profile", "model_env", "health_url"):
            if not str(profile.get(key) or "").strip():
                errors.append(f"{label}: missing {key}")
        services = profile.get("services")
        if not isinstance(services, list) or not services:
            errors.append(f"{label}: services must be a non-empty list")
        try:
            if float(profile.get("memory_gb", 0)) <= 0:
                errors.append(f"{label}: memory_gb must be positive")
        except (TypeError, ValueError):
            errors.append(f"{label}: memory_gb must be numeric")
        if not str(profile.get("health_url", "")).startswith("http://127.0.0.1:"):
            errors.append(f"{label}: health_url must be loopback")
        conflicts = profile.get("conflicts", [])
        if not isinstance(conflicts, list):
            errors.append(f"{label}: conflicts must be a list")
    return errors


def profile(config: dict[str, Any], name: str) -> dict[str, Any]:
    profiles = config.get("profiles")
    if not isinstance(profiles, dict) or name not in profiles:
        raise Refusal(f"unknown profile {name!r}; expected one of {', '.join(sorted(profiles or {}))}")
    value = profiles[name]
    if not isinstance(value, dict):
        raise Refusal(f"profile {name} is not an object")
    return value


def state_root(role: str) -> Path:
    root = default_state(role)
    (root / "leases").mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def lease_path(role: str, name: str) -> Path:
    return state_root(role) / "leases" / f"{name}.json"


def read_leases(role: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted((state_root(role) / "leases").glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            result[path.stem] = data
    return result


def write_lease(role: str, name: str, lease: dict[str, Any]) -> Path:
    path = lease_path(role, name)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = json.dumps(lease, indent=2, sort_keys=True) + "\n"
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


def remove_lease(role: str, name: str) -> None:
    lease_path(role, name).unlink(missing_ok=True)


def audit(role: str, event: dict[str, Any]) -> None:
    root = state_root(role)
    path = root / "audit.jsonl"
    row = {"at": now_iso(), **event}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    os.chmod(path, 0o600)


def mem_available_gb(meminfo: Path) -> float | None:
    try:
        for line in meminfo.read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                parts = line.split()
                return int(parts[1]) / 1024**2
    except (OSError, ValueError, IndexError):
        return None
    return None


def model_file(store: Path, model_id: str) -> str:
    path = store / "manifests" / f"{model_id}.json"
    manifest = load_json(path)
    if manifest.get("pinned") is not True:
        raise Refusal(f"{model_id}: manifest is not pinned; run model-pull --verify")
    relative = str(manifest.get("model_file") or "")
    if not relative:
        raise Refusal(f"{model_id}: manifest has no model_file")
    local = store / model_id / relative
    if not local.is_file():
        raise Refusal(f"{model_id}: model file is missing: {local}")
    return f"/models/{model_id}/{relative}"


def compose_command(config: dict[str, Any], name: str, action: str) -> list[str]:
    item = profile(config, name)
    compose = Path(str(item["compose_file"]))
    if not compose.is_absolute():
        compose = ROOT / compose
    if not compose.is_file():
        raise Refusal(f"compose file is missing: {compose}")
    base = [
        "docker",
        "compose",
        "-f",
        str(compose),
        "-p",
        str(item["project"]),
        "--profile",
        str(item["profile"]),
    ]
    if action == "up":
        return [*base, "up", "-d", *[str(service) for service in item["services"]]]
    if action == "stop":
        return [*base, "stop", *[str(service) for service in item["services"]]]
    raise Refusal(f"unknown compose action {action!r}")


def run_command(cmd: list[str], env: dict[str, str], dry_run: bool) -> None:
    if dry_run:
        print(shlex.join(cmd))
        return
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False, timeout=300)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-2000:]
        raise Refusal(f"command failed ({result.returncode}): {shlex.join(cmd)}\n{detail}")


def health(url: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if 200 <= int(response.status) < 300:
                    return True
        except Exception as exc:
            last_error = str(exc)
        time.sleep(2)
    if last_error:
        log(f"health probe {url}: {last_error}")
    return False


def start(
    *,
    config: dict[str, Any],
    role: str,
    name: str,
    store: Path,
    meminfo: Path,
    dry_run: bool,
    force: bool,
    replace: bool,
    health_timeout: float | None,
    operator: str,
) -> dict[str, Any]:
    item = profile(config, name)
    defaults = config.get("defaults") if isinstance(config.get("defaults"), dict) else {}
    leases = read_leases(role)
    if name in leases:
        return {"profile": name, "state": "already-leased", "lease": leases[name]}

    conflicts = set(item.get("conflicts", []))
    for other_name, _other in leases.items():
        other_item = config.get("profiles", {}).get(other_name, {})
        other_conflicts = set(other_item.get("conflicts", [])) if isinstance(other_item, dict) else set()
        if other_name in conflicts or name in other_conflicts:
            if not replace:
                raise Refusal(f"{name} conflicts with active lease {other_name}; use --replace")
            log(f"stopping conflicting lease {other_name}")
            stop(config=config, role=role, name=other_name, store=store, dry_run=dry_run, operator=operator)

    available = mem_available_gb(meminfo)
    required = float(item["memory_gb"]) + float(defaults.get("memory_safety_gb", 4))
    if available is not None and available < required:
        if not force:
            raise Refusal(
                f"{name} needs {required:.1f} GiB free; MemAvailable is {available:.1f} GiB "
                "(stop a conflicting runtime or use --force)"
            )
        log(f"WARNING: forcing {name} with only {available:.1f} GiB free")

    env = os.environ.copy()
    env[str(item["model_env"])] = model_file(store, str(item["model_id"]))
    env["SPARKNET_MODEL_STORE"] = str(store)
    cmd = compose_command(config, name, "up")
    run_command(cmd, env, dry_run)
    if dry_run:
        return {"profile": name, "state": "dry-run", "command": cmd, "model_file": env[str(item["model_env"])]}

    timeout = float(defaults.get("health_timeout_seconds", 180)) if health_timeout is None else health_timeout
    if timeout > 0 and not health(str(item["health_url"]), timeout):
        run_command(compose_command(config, name, "stop"), env, False)
        remove_lease(role, name)
        raise Refusal(f"{name}: health check failed at {item['health_url']}")

    lease = {
        "schema": "sparknet-model-lease/1",
        "role": role,
        "node": config.get("node"),
        "profile": name,
        "model_id": item["model_id"],
        "project": item["project"],
        "services": item["services"],
        "compose_file": item["compose_file"],
        "health_url": item["health_url"],
        "memory_gb": item["memory_gb"],
        "started_at": now_iso(),
        "idle_stop_minutes": int(item.get("idle_stop_minutes", defaults.get("idle_stop_minutes", 45))),
        "pinned": False,
        "operator": operator,
    }
    write_lease(role, name, lease)
    audit(role, {"event": "start", "profile": name, "model_id": item["model_id"], "operator": operator})
    log(f"{name}: ready ({item['model_id']})")
    return {"profile": name, "state": "ready", "lease": lease}


def stop(*, config: dict[str, Any], role: str, name: str, store: Path, dry_run: bool, operator: str) -> dict[str, Any]:
    leases = read_leases(role)
    lease = leases.get(name)
    if lease is None:
        return {"profile": name, "state": "not-leased"}
    env = os.environ.copy()
    env["SPARKNET_MODEL_STORE"] = str(store)
    run_command(compose_command(config, name, "stop"), env, dry_run)
    if not dry_run:
        remove_lease(role, name)
        audit(role, {"event": "stop", "profile": name, "model_id": lease.get("model_id"), "operator": operator})
    log(f"{name}: stopped")
    return {"profile": name, "state": "stopped"}


def status(role: str, config: dict[str, Any], probe: bool) -> dict[str, Any]:
    leases = read_leases(role)
    now_dt = now()
    rows: list[dict[str, Any]] = []
    for _name, lease in leases.items():
        started = str(lease.get("started_at") or "")
        try:
            age = (now_dt - datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds() / 60
        except ValueError:
            age = 0.0
        row = {
            **lease,
            "age_minutes": round(age, 1),
            "expired": age > float(lease.get("idle_stop_minutes", 45)),
        }
        if probe:
            row["healthy"] = health(str(lease.get("health_url")), 2)
        rows.append(row)
    return {"role": role, "node": config.get("node"), "leases": rows}


def reap(config: dict[str, Any], role: str, store: Path, operator: str, dry_run: bool) -> list[dict[str, Any]]:
    stopped: list[dict[str, Any]] = []
    for name, lease in read_leases(role).items():
        if lease.get("pinned"):
            continue
        try:
            started = datetime.fromisoformat(str(lease["started_at"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        age = (now() - started).total_seconds() / 60
        if age <= float(lease.get("idle_stop_minutes", 45)):
            continue
        stopped.append(stop(config=config, role=role, name=name, store=store, dry_run=dry_run, operator=operator))
    return stopped


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="sparknet on-demand model runtime leases")
    parser.add_argument("command", choices=("status", "start", "stop", "reap"))
    parser.add_argument("profile", nargs="?", help="profile name for start/stop")
    parser.add_argument("--role", choices=("peer", "master"), default=os.environ.get("SPARKNET_ROLE", "peer"))
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--meminfo", type=Path, default=Path("/proc/meminfo"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--health-timeout", type=float, default=None)
    parser.add_argument("--interval", type=float, default=60.0, help="reap loop seconds; 0 runs once")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--operator", default=os.environ.get("SPARKNET_OPERATOR", "operator"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = args.config or ROLE_CONFIG[args.role]
    try:
        config = load_json(config_path)
        catalog = catalog_by_id(args.catalog)
        errors = validate_config(config, args.role, catalog)
        if errors:
            for error in errors:
                print(f"model-runtime: {error}", file=sys.stderr)
            return 1
        if args.command == "status":
            result = status(args.role, config, args.probe)
        elif args.command == "start":
            if not args.profile:
                raise Refusal("start needs a profile")
            result = start(
                config=config,
                role=args.role,
                name=args.profile,
                store=args.store,
                meminfo=args.meminfo,
                dry_run=args.dry_run,
                force=args.force,
                replace=args.replace,
                health_timeout=args.health_timeout,
                operator=args.operator,
            )
        elif args.command == "stop":
            if not args.profile:
                raise Refusal("stop needs a profile")
            result = stop(
                config=config,
                role=args.role,
                name=args.profile,
                store=args.store,
                dry_run=args.dry_run,
                operator=args.operator,
            )
        else:
            if args.interval > 0 and not args.dry_run:
                while True:
                    stopped = reap(config, args.role, args.store, args.operator, args.dry_run)
                    if stopped:
                        log(f"reaped {len(stopped)} lease(s)")
                    time.sleep(max(5.0, args.interval))
            result = {"reaped": reap(config, args.role, args.store, args.operator, args.dry_run)}
        if args.json:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Refusal as exc:
        print(f"model-runtime: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
