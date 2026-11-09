"""Shared fixtures for the fabric suite.

The root ``tests/`` tree covers everything that is neither peer- nor
master-specific: the cross-role contract, the repository layout and claims, the
shell contract, and the vendored wiki skills. Role subvaults keep their own
conftest, so this one stays deliberately small — a fixture to locate the fabric
root and the place the test tiers are exercised from.

The tier markers (``unit``, ``integration``, ``contract``, ``layout``, ``slow``)
are registered in ``pyproject.toml`` so ``--strict-markers`` accepts them and
``pytest -m <tier>`` can select them as tests begin to carry the marks.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))

from contract_helpers import SHARED_PATH, load  # noqa: E402 - after the shared path shim
from sparknet_loader import load_by_path  # noqa: E402 - shared/ is added by path above


@pytest.fixture
def repo_root() -> Path:
    """The fabric root, resolved from this file rather than the cwd.

    Tests that shell out or read repository files must not depend on where
    pytest was invoked from; resolving from ``__file__`` keeps them correct
    under ``make``, a bare ``pytest`` and the bundle-verify extraction alike.
    """
    return Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def overlay() -> dict:
    return load("overlay.json")


@pytest.fixture(scope="module")
def capabilities() -> dict:
    return load("capabilities.json")


@pytest.fixture(scope="module")
def identity_schema() -> dict:
    return load("identity-schema.json")


@pytest.fixture(scope="module")
def ports() -> dict:
    return load("ports.json")


@pytest.fixture(scope="module")
def authz() -> ModuleType:
    """Load the one shared implementation through the one loader.

    It lives outside the package so that neither role can accidentally import a
    private copy; loading it through ``sparknet_loader`` is what proves there is
    only one loader and one implementation.
    """
    return load_by_path("sparknet_authz", SHARED_PATH)
