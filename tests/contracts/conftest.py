"""Fixtures shared by the split contract tests.

The root ``tests/conftest.py`` still provides the repository-wide fixtures
(``authz``, ``capabilities``, ``ports``, ...). This file only adds what more than
one contract module needs and puts the repository test helper on the path from
the subdirectory.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "shared", ROOT / "tests"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from contract_helpers import load  # noqa: E402 - after the path shim


@pytest.fixture(scope="module")
def rfi_schema() -> dict:
    return load("rfi-schema.json")


@pytest.fixture(scope="module")
def tracking() -> dict:
    return load("tracking-schema.json")
