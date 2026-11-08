"""The 416-file Phase 8 inventory is complete and machine-checkable."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INVENTORY = ROOT / "_archives" / "phase8-inventory.json"
REGISTER = ROOT / "_archives" / "phase8-rewrite-register.md"
SCRIPT = ROOT / "scripts" / "sparknet-phase8-inventory.py"


def _document() -> dict:
    return json.loads(INVENTORY.read_text(encoding="utf-8"))


def test_inventory_has_every_file_exactly_once() -> None:
    files = _document()["files"]
    assert len(files) == 416
    paths = [row["path"] for row in files]
    assert len(paths) == len(set(paths))
    for row in files:
        assert (ROOT / row["path"]).is_file(), row["path"]
        assert row["status"] in {
            "pending",
            "reviewed-clean",
            "fixed",
            "hardened",
            "test-verified",
            "needs-decision",
            "excluded-generated",
        }
        assert row["prior_disposition"] in {"rewrite", "retain"}


def test_inventory_matches_the_human_register() -> None:
    import re

    rows = []
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\| `([^`]+)` \| (\d+) \| (\w+) \| (\w+) \|$", line)
        if match:
            rows.append(match.groups())
    assert len(rows) == 416
    files = {row["path"]: row for row in _document()["files"]}
    assert set(files) == {row[0] for row in rows}
    assert Counter(row["risk"] for row in files.values()) == {"low": 282, "medium": 63, "high": 71}


def test_phase8_check_command_passes() -> None:
    result = subprocess.run([sys.executable, str(SCRIPT), "check"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr + result.stdout
