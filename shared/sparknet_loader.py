#!/usr/bin/env python3
"""The one by-path module loader for the fabric.

Every shared module proves there is exactly one implementation by loading its
siblings *by path* rather than by import: an import would let a role quietly
carry a private copy, and two copies that must agree byte-for-byte are a second
trust boundary. That load was copy-pasted in seven modules (consensus, http,
merkle, provenance, proposal, election, and the master ledger); this is the
single implementation.

This module is plumbing, not crypto. It protects the ability to *find* the one
crypto module; it does not sign, verify or hash anything itself. A test
(``tests/test_contracts.py::test_only_one_shared_loader_exists``) fails if a
shared module reintroduces its own ``spec_from_file_location`` copy.

Resolution order for ``filename`` (first hit wins):

1. each explicit ``dirs`` entry, if given — else this module's own directory;
2. ``$SPARKNET_SHARED_DIR/shared`` and its parent's ``shared/``;
3. ``$VAULT_PATH/shared`` and its parent's ``shared/``.

Modules are cached in ``sys.modules`` under ``modname`` and returned as-is on a
second call, so two callers never end up with two module objects (two
``isinstance`` targets, two loader caches). A module is registered *before*
``exec_module``: dataclasses resolves its own module through ``sys.modules``,
and registering afterwards raises an ``AttributeError`` that names neither the
cause nor the file.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

#: This module's own directory — ``shared/`` in a checkout.
DEFAULT_SHARED_DIR = Path(__file__).resolve().parent

_ENV_DIRS = ("SPARKNET_SHARED_DIR", "VAULT_PATH")


def _env(name: str) -> str | None:
    raw = os.environ.get(name, "").strip()
    return raw or None


def candidates(filename: str, dirs: Iterable[Path] | None = None) -> list[Path]:
    """Every path ``filename`` might live at, in resolution order."""
    roots: list[Path] = [Path(d) for d in dirs] if dirs else [DEFAULT_SHARED_DIR]
    for env in _ENV_DIRS:
        raw = _env(env)
        if raw:
            roots.append(Path(raw) / "shared")
            roots.append(Path(raw).parent / "shared")
    return [root / filename for root in roots]


def load_by_path(name: str, path: Path, *, error: type[Exception] = ImportError, message: str | None = None) -> Any:
    """Load one hyphen-named file by path, once.

    ``error``/``message`` let a caller raise its own refusal type (a
    ``ConsensusError``, a ``ProvenanceError``) instead of the generic
    ``ImportError``, because each surface owns its own failure vocabulary.
    """
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise error(message or f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        # A failed load must not leave a half-initialised module cached under
        # the canonical name; the next caller would receive the broken object.
        sys.modules.pop(name, None)
        raise
    return module


def load_shared(
    filename: str,
    modname: str,
    *,
    dirs: Iterable[Path] | None = None,
    error: type[Exception] = FileNotFoundError,
    message: Callable[[], str] | str | None = None,
    required: Iterable[str] = (),
    missing_ok: bool = False,
) -> Any:
    """Find ``filename`` on the shared search path and load it as ``modname``.

    ``required`` names sibling files that must exist beside the one found; a
    caller that depends on two canonical files (a transport plus the authz it
    verifies with) refuses before loading a half-usable module. ``missing_ok``
    returns ``None`` instead of raising for an optional surface; the caller
    keeps its own policy about whether that is fatal.
    """
    if modname in sys.modules:
        return sys.modules[modname]
    for path in candidates(filename, dirs):
        if path.is_file():
            missing = [dep for dep in required if not (path.parent / dep).is_file()]
            if missing:
                raise error(
                    f"cannot locate {', '.join(missing)} beside {filename}; "
                    "the fabric carries exactly one implementation and this tool "
                    "does not carry a fallback"
                )
            return load_by_path(modname, path, error=error, message=_text(message))
    if missing_ok:
        return None
    if callable(message):
        raise error(message())
    raise error(
        _text(message)
        or (
            f"cannot locate {filename}; the fabric carries exactly one "
            "implementation and this tool does not carry a fallback"
        )
    )


def _text(message: Callable[[], str] | str | None) -> str | None:
    if message is None or callable(message):
        return None
    return message
