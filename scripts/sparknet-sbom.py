#!/usr/bin/env python3
"""Generate a deterministic CycloneDX SBOM for the fabric.

Why this exists
~~~~~~~~~~~~~~~
A deployment asks "what is in this, and at what version?" and until now the
answer lived in three places that could disagree: ``VERSION`` (which did not
exist), ``pyproject.toml``'s ``version`` and ``requirements.txt``. This script
puts the answer in one generated, machine-readable place — ``sbom/sparknet.cdx.json``
— the same way ``scripts/sparknet-render.py`` turns the contract SSOT into
``contracts/manifest.json``.

Two consequences worth holding onto:

1. **It is generated, never hand-edited.** ``--check`` fails when ``VERSION``,
   the runtime dependency or the vendored skill suite changed without the SBOM
   being regenerated. That is the drift gate: edit one of them, run ``make sbom``.
2. **Determinism is the contract.** No timestamp, no hostname, and a stable
   component order — the same inputs always render byte-identical output, so
   ``--check`` compares text rather than trying to understand it. The CycloneDX
   ``serialNumber`` is deliberately omitted: every UUIDv4 is time-and-machine
   dependent, which would defeat the check.

What goes in it
~~~~~~~~~~~~~~~
The SBOM is deliberately small and honest, because sparknet is not a package
with a lockfile:

* the **application** — ``sparknet`` at the version in ``VERSION``;
* its one **runtime dependency** — ``cryptography`` at the *declared* constraint
  from ``requirements.txt`` (there is no lockfile, so pinning a concrete version
  would be a lie);
* the **vendored wiki skill suite** — one component per skill, hashed, MIT.

Usage::

    scripts/sparknet-sbom.py            # write sbom/sparknet.cdx.json
    scripts/sparknet-sbom.py --check    # fail if it is stale (no write)

Exit codes: 0 ok, 1 stale (``--check``) or an unreadable input.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

#: The generated file, relative to the repo root. Never hand-edited.
DEFAULT_OUT = Path("sbom") / "sparknet.cdx.json"

#: The CycloneDX specification this document conforms to.
SPEC_VERSION = "1.5"

#: Bumped only if this document's own shape changes.
SBOM_SCHEMA_VERSION = "1.0"

#: The one runtime dependency, read from requirements.txt rather than hardcoded
#: so the SBOM cannot silently disagree with what `make bundle` installs.
RUNTIME_DEPENDENCY = "cryptography"

#: Where the vendored skills live, and the file that identifies one.
SKILLS_DIR = ".opencode/skills"
SKILL_MARKER = "SKILL.md"

#: The vendored suite's license, as recorded in .opencode/skills/README.md.
VENDORED_SKILL_LICENSE = "MIT"

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

_REPO_ROOT = Path(__file__).resolve().parent.parent


def sha256_file(path: Path) -> str:
    """Return the hex sha256 of ``path`` (read in chunks, never all at once)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_version(root: Path) -> str:
    """Return the version from ``VERSION``, or raise ``ValueError`` if malformed.

    The format is pinned here, not in the test: a version nobody can parse is
    worse than no version, because the SBOM and the CLI would both repeat it.
    """
    path = root / "VERSION"
    if not path.is_file():
        raise ValueError(f"{path} is missing")
    text = path.read_text(encoding="utf-8").strip()
    if not _VERSION_RE.match(text):
        raise ValueError(f"{path} is not MAJOR.MINOR.PATCH: {text!r}")
    return text


def _read_dependency_constraint(root: Path, name: str) -> str:
    """Return the ``name`` constraint from ``requirements.txt`` (e.g. ``>=42``)."""
    path = root / "requirements.txt"
    if not path.is_file():
        raise ValueError(f"{path} is missing")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.split(">=")[0].split("==")[0].split("~=")[0].strip() == name:
            constraint = line[len(name) :].strip()
            return constraint or "(unpinned)"
    raise ValueError(f"requirements.txt does not declare {name!r}")


def _vendored_skills(root: Path) -> list[dict]:
    """Return the vendored skills, sorted by name, each with a SKILL.md hash."""
    skills_dir = root / SKILLS_DIR
    if not skills_dir.is_dir():
        raise ValueError(f"{skills_dir} is missing (run make wiki-sync)")
    skills = []
    for entry in sorted(skills_dir.iterdir(), key=lambda p: p.name):
        marker = entry / SKILL_MARKER
        if not (entry.is_dir() and marker.is_file()):
            continue
        skills.append(
            {
                "name": entry.name,
                "path": f"{SKILLS_DIR}/{entry.name}/{SKILL_MARKER}",
                "sha256": sha256_file(marker),
            }
        )
    if not skills:
        raise ValueError(f"no vendored skills under {skills_dir}")
    return skills


def _component(name: str, *, constraint: str) -> dict:
    return {
        "type": "library",
        "bom-ref": f"pkg:pypi/{name}",
        "name": name,
        "purl": f"pkg:pypi/{name}",
        "scope": "required",
        "properties": [
            {"name": "sparknet:declared-constraint", "value": constraint},
            {"name": "sparknet:declared-in", "value": "requirements.txt"},
        ],
    }


def _skill_component(skill: dict) -> dict:
    return {
        "type": "data",
        "bom-ref": f"vendored-wiki-skill:{skill['name']}",
        "name": skill["name"],
        "properties": [
            {"name": "sparknet:kind", "value": "vendored-wiki-skill"},
            {"name": "sparknet:path", "value": skill["path"]},
            {"name": "sparknet:license", "value": VENDORED_SKILL_LICENSE},
        ],
        "hashes": [{"alg": "SHA-256", "content": skill["sha256"]}],
    }


def build(root: Path) -> dict:
    """Return the SBOM dict rendered from the fabric at ``root``.

    Pure and deterministic: reads ``VERSION``, ``requirements.txt`` and the
    vendored skill suite, and assembles a fixed component list. Raises
    ``ValueError`` on an unreadable input so the caller can fail closed.
    """
    version = _read_version(root)
    constraint = _read_dependency_constraint(root, RUNTIME_DEPENDENCY)
    skills = _vendored_skills(root)

    components = [_component(RUNTIME_DEPENDENCY, constraint=constraint)]
    components += [_skill_component(skill) for skill in skills]
    components.sort(key=lambda c: c["name"])

    return {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "bom-ref": f"sparknet@{version}",
                "name": "sparknet",
                "version": version,
                "description": "The sparknet fabric: cross-role contracts, a peer node and an elected signing master.",
            },
            "tools": [
                {
                    "vendor": "sparknet",
                    "name": "sparknet-sbom.py",
                    "version": SBOM_SCHEMA_VERSION,
                }
            ],
        },
        "components": components,
    }


def render(sbom: dict) -> str:
    """Serialize ``sbom`` deterministically (sorted keys, 2-space, newline)."""
    return json.dumps(sbom, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    root = _REPO_ROOT
    parser = argparse.ArgumentParser(description="generate a CycloneDX SBOM for the fabric")
    parser.add_argument(
        "--out",
        default=None,
        help=f"the SBOM path (default: <repo>/{DEFAULT_OUT})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report drift and exit 1 instead of writing",
    )
    args = parser.parse_args(argv)

    out = Path(args.out).expanduser() if args.out else root / DEFAULT_OUT

    try:
        text = render(build(root))
    except ValueError as exc:
        print(f"sparknet-sbom: {exc}", file=sys.stderr)
        return 1

    if args.check:
        if not out.is_file():
            print(f"sparknet-sbom: {out} is missing — run `make sbom`", file=sys.stderr)
            return 1
        if out.read_text(encoding="utf-8") != text:
            print(
                f"sparknet-sbom: {out} is stale — VERSION, requirements.txt or the "
                f"vendored skills changed without the SBOM being regenerated. "
                f"Run `make sbom`.",
                file=sys.stderr,
            )
            return 1
        print(f"sparknet-sbom: {out} is up to date")
        return 0

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"sparknet-sbom: wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
