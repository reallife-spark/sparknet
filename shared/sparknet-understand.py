#!/usr/bin/env python3
"""Loader for the Understand-Anything core.

The implementation lives in ``shared/sparknet_understand/``. Loading by path is
the fabric's rule: a role must read the one copy in this tree, not an installed
package that happens to shadow it.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    shared = Path(__file__).resolve().parent
    if str(shared) not in sys.path:
        sys.path.insert(0, str(shared))
    from sparknet_understand.cli import main as cli_main

    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
