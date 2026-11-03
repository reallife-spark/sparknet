#!/usr/bin/env python3
"""Deprecated one-release alias for ``scripts/sparknet-vector.py``.

The backend moved from Chroma to Qdrant. The old command name is kept so an
operator's shell history and a staged unit keep working during the migration
window; every invocation prints a deprecation note and then runs the new
implementation. Remove this file when the Chroma volumes are retired.
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

TARGET = Path(__file__).with_name("sparknet-vector.py")


def main() -> int:
    print(
        "sparknet-chroma: deprecated alias; use scripts/sparknet-vector.py (Qdrant is the store now)",
        file=sys.stderr,
    )
    runpy.run_path(str(TARGET), run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
