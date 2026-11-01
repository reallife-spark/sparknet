"""The executable three-node share rehearsal must stay green."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "sparknet-share-rehearsal.py"


def test_three_node_share_rehearsal_passes(tmp_path: Path) -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--work", str(tmp_path / "share")],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=ROOT,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "10 passed, 0 failed" in proc.stdout
