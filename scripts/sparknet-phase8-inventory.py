#!/usr/bin/env python3
"""Maintain and check the Phase 8 416-file remediation inventory.

The markdown register is the human annex; the JSON file is the execution state.
`sync` seeds missing rows without discarding work already recorded. `check`
proves coverage and shape on every commit. `closure` is the stricter gate used
only when Step 90 is declared done.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTER = ROOT / "_archives" / "phase8-rewrite-register.md"
INVENTORY = ROOT / "_archives" / "phase8-inventory.json"
EXPECTED_FILES = 416
STATUSES = {
    "pending",
    "reviewed-clean",
    "fixed",
    "hardened",
    "test-verified",
    "needs-decision",
    "excluded-generated",
}
TERMINAL = {"reviewed-clean", "fixed", "hardened", "test-verified", "excluded-generated"}
ROW_RE = re.compile(r"^\| `([^`]+)` \| (\d+) \| (\w+) \| (\w+) \|$")


def parse_register() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        match = ROW_RE.match(line)
        if not match:
            continue
        path, loc, risk, prior = match.groups()
        rows.append(
            {
                "path": path,
                "loc": int(loc),
                "risk": risk,
                "language": Path(path).suffix.lstrip(".") or "none",
                "area": Path(path).parts[0],
                "prior_disposition": prior,
                "status": "pending",
                "finding_ids": [],
                "evidence": "",
                "test": "",
                "commit": "",
                "reviewer": "",
                "notes": "",
            }
        )
    return rows


def load_inventory() -> dict[str, object]:
    if not INVENTORY.is_file():
        raise FileNotFoundError(f"missing {INVENTORY}; run `make phase8-sync`")
    data = json.loads(INVENTORY.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        raise ValueError(f"{INVENTORY} is not a Phase 8 inventory")
    return data


def sync(force: bool) -> int:
    fresh = parse_register()
    if INVENTORY.is_file() and not force:
        existing = {row["path"]: row for row in load_inventory()["files"] if isinstance(row, dict) and "path" in row}
        for row in fresh:
            old = existing.get(str(row["path"]))
            if old:
                for key in ("status", "finding_ids", "evidence", "test", "commit", "reviewer", "notes"):
                    if key in old:
                        row[key] = old[key]
    document = {
        "schema": "sparknet-phase8-inventory/1",
        "generated_at": "2026-11-08",
        "source": str(REGISTER.relative_to(ROOT)),
        "files": fresh,
    }
    INVENTORY.write_text(json.dumps(document, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"phase8-sync: wrote {len(fresh)} rows to {INVENTORY.relative_to(ROOT)}")
    return 0


def _errors(strict: bool) -> list[str]:
    try:
        document = load_inventory()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [str(exc)]
    files = document.get("files")
    if not isinstance(files, list):
        return ["inventory has no files array"]
    errors: list[str] = []
    if len(files) != EXPECTED_FILES:
        errors.append(f"inventory has {len(files)} rows; expected {EXPECTED_FILES}")
    seen: set[str] = set()
    for index, row in enumerate(files):
        where = f"row {index}"
        if not isinstance(row, dict):
            errors.append(f"{where}: not an object")
            continue
        path = row.get("path")
        if not isinstance(path, str) or not path:
            errors.append(f"{where}: path is missing")
            continue
        where = path
        if path in seen:
            errors.append(f"{where}: duplicate path")
        seen.add(path)
        if not (ROOT / path).is_file():
            errors.append(f"{where}: file does not exist")
        status = row.get("status")
        if status not in STATUSES:
            errors.append(f"{where}: invalid status {status!r}")
        if strict and status == "needs-decision":
            errors.append(f"{where}: needs-decision")
        if strict and status == "pending":
            errors.append(f"{where}: still pending")
        if status in {"fixed", "hardened"} and not str(row.get("evidence") or "").strip():
            errors.append(f"{where}: {status} has no evidence")
        if status == "fixed" and not str(row.get("test") or "").strip():
            errors.append(f"{where}: fixed has no regression test reference")
        if status == "test-verified" and not str(row.get("test") or "").strip():
            errors.append(f"{where}: test-verified has no test evidence")
    return errors


def check(strict: bool) -> int:
    errors = _errors(strict)
    if errors:
        print("sparknet-phase8-inventory: FAILED", file=sys.stderr)
        for error in errors[:40]:
            print(f"  - {error}", file=sys.stderr)
        if len(errors) > 40:
            print(f"  ... {len(errors) - 40} more", file=sys.stderr)
        return 2
    print("sparknet-phase8-inventory: 416 rows, all covered and well formed")
    return 0


def stats() -> int:
    document = load_inventory()
    rows = [row for row in document["files"] if isinstance(row, dict)]
    from collections import Counter

    print(f"files={len(rows)} loc={sum(int(row.get('loc', 0)) for row in rows)}")
    print("risk=" + json.dumps(Counter(row.get("risk") for row in rows), sort_keys=True))
    print("status=" + json.dumps(Counter(row.get("status") for row in rows), sort_keys=True))
    print("area=" + json.dumps(Counter(row.get("area") for row in rows), sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sparknet-phase8-inventory")
    parser.add_argument("command", choices=("sync", "check", "closure", "stats"))
    parser.add_argument("--force", action="store_true", help="reset all statuses from the markdown register")
    args = parser.parse_args(argv)
    if args.command == "sync":
        return sync(args.force)
    if args.command == "check":
        return check(strict=False)
    if args.command == "closure":
        return check(strict=True)
    return stats()


if __name__ == "__main__":
    raise SystemExit(main())
