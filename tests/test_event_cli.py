"""The event CLI answers --help without touching the bus."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sparknet-event.py"


def test_event_cli_help():
    result = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "publish" in result.stdout and "subscribe" in result.stdout
