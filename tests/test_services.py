"""The fabric's dependency allow-list and its two mirrored declarations.

Both `pyproject.toml` and `requirements.txt` cite this file as the guard for
the `cryptography`-only runtime surface. The original file was removed in the
two-role split (`78f1602`); `peer-node/tests/test_services.py` is that
submodule's own guard and is not reachable from a standalone fabric clone.

The guard is a characterization test: the invariant already holds, and the
mutation proof recorded in the Step 97 log shows it fails for the right reason.
"""

from __future__ import annotations

import re
from pathlib import Path

import tomllib

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
REQUIREMENTS = REPO_ROOT / "requirements.txt"

#: The only permitted third-party runtime package. Ed25519 is not in the
#: standard library, so the fabric cannot be stdlib-only; anything else is a
#: regression until someone justifies it in the same change.
ALLOWED_THIRD_PARTY = {"cryptography"}

_REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")


def _project() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]


def _declared_dependencies() -> list[str]:
    return list(_project()["dependencies"])


def _requirement_lines() -> list[str]:
    lines: list[str] = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def _package_name(spec: str) -> str:
    match = _REQUIREMENT_NAME.match(spec)
    assert match, f"not a requirement specifier: {spec!r}"
    return match.group(0).lower().replace("_", "-")


def test_pyproject_dependencies_stay_on_the_allowlist() -> None:
    declared = _declared_dependencies()
    assert declared, "the fabric declares no runtime dependencies"
    packages = {_package_name(spec) for spec in declared}
    assert packages == ALLOWED_THIRD_PARTY, f"pyproject dependencies drifted: {sorted(packages)}"


def test_requirements_txt_mirrors_pyproject_dependencies() -> None:
    requirements = _requirement_lines()
    declared = _declared_dependencies()
    assert sorted(requirements) == sorted(declared), (
        "requirements.txt and [project].dependencies disagree; both are cited as one list"
    )
    names = [_package_name(spec) for spec in requirements]
    assert len(names) == len(set(names)), f"duplicate requirement: {names}"
