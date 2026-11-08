"""The one by-path loader never caches a half-initialised module."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _loader():
    spec = importlib.util.spec_from_file_location("loader_test", ROOT / "shared" / "sparknet_loader.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_failed_load_is_not_cached(tmp_path):
    loader = _loader()
    bad = tmp_path / "bad.py"
    bad.write_text("raise RuntimeError('boom')\n")
    name = "sparknet_bad_module_for_loader_test"
    sys.modules.pop(name, None)
    with pytest.raises(RuntimeError, match="boom"):
        loader.load_by_path(name, bad)
    assert name not in sys.modules
