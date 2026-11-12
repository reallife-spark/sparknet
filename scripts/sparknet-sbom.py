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
   the runtime dependency, the vendored skill suite or a role catalog changed
   without the SBOM being regenerated. That is the drift gate: edit one of
   them, run ``make sbom``.
2. **Determinism is the contract.** No timestamp, no hostname, and a stable
   component order — the same inputs always render byte-identical output, so
   ``--check`` compares text rather than trying to understand it. The CycloneDX
   ``serialNumber`` is deliberately omitted: every UUIDv4 is time-and-machine
   dependent, which would defeat the check.

What goes in it
~~~~~~~~~~~~~~~
The SBOM is deliberately small and honest, because sparknet is not a package
with a lockfile:

* the **application** — ``sparknet`` at the version in ``VERSION``. Its license
  is ``NOASSERTION`` until C1 chooses one, which is a fact, not an omission;
* its one **runtime dependency** — ``cryptography`` at the *declared* constraint
  from ``requirements.txt`` (there is no lockfile, so pinning a concrete version
  would be a lie);
* the **vendored wiki skill suite** — one component per skill, with a hash over
  the **whole skill directory** (not just ``SKILL.md``, so a changed reference
  file is drift) and the license the skill actually carries. The suite is MIT,
  but ``skill-creator`` ships its own Apache-2.0 ``LICENSE.txt``; a local skill
  has no grant while C1 is deferred and is recorded as ``NOASSERTION``;
* the **role-local catalogs** — one component per catalog, pinned by the hash of
  its ``.inventory.json`` (which already records per-skill hashes, licenses and
  provenance, so the SBOM stays small and still detects drift).

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
SBOM_SCHEMA_VERSION = "1.1"

#: The one runtime dependency, read from requirements.txt rather than hardcoded
#: so the SBOM cannot silently disagree with what `make bundle` installs.
RUNTIME_DEPENDENCY = "cryptography"

#: Where the vendored skills live, and the file that identifies one.
SKILLS_DIR = ".opencode/skills"
SKILL_MARKER = "SKILL.md"

#: Files a skill may carry to declare its own license. ``skill-creator`` is the
#: case that made this list necessary: it ships Apache-2.0, not the suite MIT.
SKILL_LICENSE_FILES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENSE.rst", "COPYING")

#: The suite fallback, from ``.opencode/skills/LICENSE`` (MIT, © Ar9av).
SUITE_LICENSE = "MIT"

#: Skills authored in-repo rather than vendored. Mirrors ``LOCAL_SKILLS`` in
#: ``scripts/sync-wiki-skills.py`` (the authoritative list) and is drift-gated by
#: ``tests/test_release.py``. A local skill has no upstream license grant, so
#: until C1 chooses a repo license the honest value is NOASSERTION.
LOCAL_SKILLS = frozenset({"wiki-audit", "setup-deep-modules"})

#: SPDX's "no assertion" value, used where a license is genuinely undecided.
NOASSERTION = "NOASSERTION"

#: Build noise that must not move a skill's tree hash.
SKILL_TREE_SKIP_PARTS = {"__pycache__", ".git"}

#: Role-local catalogs. Each is represented by its manifest hash rather than
#: one component per skill: the manifest already records per-skill hashes,
#: licenses and provenance, so the SBOM stays small and still detects drift.
ROLE_CATALOGS = {
    "peer": "peer-node/.opencode/skills",
    "master": "master-node/.opencode/skills",
}

_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")

_REPO_ROOT = Path(__file__).resolve().parent.parent


def sha256_file(path: Path) -> str:
    """Return the hex sha256 of ``path`` (read in chunks, never all at once)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_sha256(root: Path) -> str:
    """Return a deterministic tree hash: sorted relative path + file hash.

    Hashing only ``SKILL.md`` would miss a changed ``references/`` file or
    ``LICENSE.txt``, which is exactly the kind of drift a bill of materials is
    supposed to detect. Directory order is sorted by POSIX relative path and
    build noise (``__pycache__``, ``*.pyc``) is excluded, so the digest is stable
    across machines and runs.
    """
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if SKILL_TREE_SKIP_PARTS & set(rel.parts) or path.suffix == ".pyc":
            continue
        digest.update(rel.as_posix().encode("utf-8") + b"\0")
        digest.update(sha256_file(path).encode("ascii") + b"\n")
    return digest.hexdigest()


def _spdx_from_text(text: str) -> str:
    """Best-effort SPDX identifier for a license file, or NOASSERTION.

    Deliberately small: the vendored suite is MIT plus the one Apache-2.0
    outlier, and an unrecognised license must be reported as NOASSERTION rather
    than guessed. Apache is checked first because its text also contains the
    permissive grant phrasing used by MIT.
    """
    low = text.lower()
    if "apache license" in low and "version 2.0" in low:
        return "Apache-2.0"
    if "mit license" in low or "permission is hereby granted, free of charge" in low:
        return "MIT"
    if "bsd 3-clause" in low or "redistribution and use in source and binary forms" in low:
        return "BSD-3-Clause"
    if "isc license" in low:
        return "ISC"
    if "cc0" in low or "creative commons zero" in low:
        return "CC0-1.0"
    if "the unlicense" in low:
        return "Unlicense"
    return NOASSERTION


def _skill_license(skill_dir: Path, name: str) -> tuple[str, str]:
    """Return ``(spdx, source)`` for one skill.

    A skill's own license file wins; a local (in-repo) skill has no grant until
    C1 chooses one; every other vendored skill falls back to the suite license.
    """
    for candidate in SKILL_LICENSE_FILES:
        path = skill_dir / candidate
        if path.is_file():
            return _spdx_from_text(path.read_text(encoding="utf-8", errors="replace")), f"skill {candidate}"
    if name in LOCAL_SKILLS:
        return NOASSERTION, "local skill (repo license deferred)"
    return SUITE_LICENSE, "suite LICENSE"


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
    """Return the vendored skills, sorted by name, each with a tree hash and license."""
    skills_dir = root / SKILLS_DIR
    if not skills_dir.is_dir():
        raise ValueError(f"{skills_dir} is missing (run make wiki-sync)")
    skills = []
    for entry in sorted(skills_dir.iterdir(), key=lambda p: p.name):
        marker = entry / SKILL_MARKER
        if not (entry.is_dir() and marker.is_file()):
            continue
        license_id, license_source = _skill_license(entry, entry.name)
        skills.append(
            {
                "name": entry.name,
                "path": f"{SKILLS_DIR}/{entry.name}",
                "entrypoint": f"{SKILLS_DIR}/{entry.name}/{SKILL_MARKER}",
                "sha256": _tree_sha256(entry),
                "license": license_id,
                "license_source": license_source,
            }
        )
    if not skills:
        raise ValueError(f"no vendored skills under {skills_dir}")
    return skills


def _role_catalog(root: Path, role: str) -> dict:
    path = root / ROLE_CATALOGS[role]
    manifest = path / ".inventory.json"
    if not manifest.is_file():
        raise ValueError(f"{manifest} is missing (run make role-skills)")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        count = data["counts"]["skills"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ValueError(f"{manifest}: missing counts.skills") from exc
    if not isinstance(count, int) or count < 0:
        raise ValueError(f"{manifest}: counts.skills is not a non-negative integer")
    return {
        "role": role,
        "path": f"{ROLE_CATALOGS[role]}/.inventory.json",
        "count": count,
        "sha256": sha256_file(manifest),
    }


def _license_choice(license_id: str) -> list[dict]:
    """Render an SPDX id as CycloneDX ``licenses``; NOASSERTION is an expression."""
    if license_id == NOASSERTION:
        return [{"expression": NOASSERTION}]
    return [{"license": {"id": license_id}}]


def _role_component(catalog: dict) -> dict:
    return {
        "type": "data",
        "bom-ref": f"role-skill-catalog:{catalog['role']}",
        "name": f"{catalog['role']}-skill-catalog",
        "properties": [
            {"name": "sparknet:kind", "value": "role-skill-catalog"},
            {"name": "sparknet:path", "value": catalog["path"]},
            {"name": "sparknet:skills", "value": str(catalog["count"])},
            {"name": "sparknet:license-policy", "value": "sellable"},
        ],
        "hashes": [{"alg": "SHA-256", "content": catalog["sha256"]}],
    }


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
        "licenses": _license_choice(skill["license"]),
        "properties": [
            {"name": "sparknet:kind", "value": "vendored-wiki-skill"},
            {"name": "sparknet:path", "value": skill["path"]},
            {"name": "sparknet:entrypoint", "value": skill["entrypoint"]},
            {"name": "sparknet:hash-scope", "value": "tree"},
            {"name": "sparknet:license", "value": skill["license"]},
            {"name": "sparknet:license-source", "value": skill["license_source"]},
        ],
        "hashes": [{"alg": "SHA-256", "content": skill["sha256"]}],
    }


def build(root: Path) -> dict:
    """Return the SBOM dict rendered from the fabric at ``root``.

    Pure and deterministic: reads ``VERSION``, ``requirements.txt``, the vendored
    skill suite and the two role catalogs, and assembles a fixed component list.
    Raises ``ValueError`` on an unreadable input so the caller can fail closed.
    """
    version = _read_version(root)
    constraint = _read_dependency_constraint(root, RUNTIME_DEPENDENCY)
    skills = _vendored_skills(root)
    catalogs = [_role_catalog(root, role) for role in ROLE_CATALOGS]

    components = [_component(RUNTIME_DEPENDENCY, constraint=constraint)]
    components += [_skill_component(skill) for skill in skills]
    components += [_role_component(catalog) for catalog in catalogs]
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
                "licenses": _license_choice(NOASSERTION),
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
                f"sparknet-sbom: {out} is stale — VERSION, requirements.txt, the "
                f"vendored skills or a role catalog changed without the SBOM being "
                f"regenerated. Run `make sbom`.",
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
