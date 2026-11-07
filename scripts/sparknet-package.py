#!/usr/bin/env python3
"""Build, verify and plan signed sparknet packages."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from sparknet_loader import load_shared

PACKAGE = load_shared("sparknet-package.py", "sparknet_package_cli")
SKIP_PARTS = {".git", ".state", "keys", "manifests", "__pycache__", ".pytest_cache", ".ruff_cache"}
SKIP_NAMES = {"secrets-index.json", "user-env-manifest.json", ".env"}


def _dep(value: str) -> dict[str, str]:
    package_id, sep, version = value.partition("@")
    if not sep or not package_id or not version:
        raise argparse.ArgumentTypeError("dependency must be id@version")
    return {"package_id": package_id, "version": version}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sparknet-package", description="Signed package manifests and install plans")
    sub = parser.add_subparsers(dest="command", required=True)

    manifest = sub.add_parser("manifest", help="build a package manifest from a directory")
    manifest.add_argument("--root", required=True)
    manifest.add_argument("--package-id", required=True)
    manifest.add_argument("--version", required=True)
    manifest.add_argument("--signer", required=True)
    manifest.add_argument("--description", default="")
    manifest.add_argument("--dep", action="append", type=_dep, default=[])
    manifest.add_argument("--out", required=True)

    index = sub.add_parser("index", help="build an index from package files")
    index.add_argument("--package", action="append", required=True)
    index.add_argument("--out", required=True)

    verify = sub.add_parser("verify", help="validate a package or index")
    verify.add_argument("--file", required=True)

    plan = sub.add_parser("plan", help="print a dependency-first install plan")
    plan.add_argument("--index", required=True)
    plan.add_argument("--root", action="append", type=_dep, required=True)
    return parser


def _artifacts(root: Path) -> list[dict]:
    rows = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.name in SKIP_NAMES:
            continue
        data = path.read_bytes()
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        )
    if not rows:
        raise PACKAGE.PackageError("bad-artifact", "root contains no artifacts")
    return rows


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "manifest":
            root = Path(args.root).resolve()
            if not root.is_dir():
                raise PACKAGE.PackageError("malformed-package", f"root is not a directory: {root}")
            package = PACKAGE.make_package(
                package_id=args.package_id,
                version=args.version,
                artifacts=_artifacts(root),
                dependencies=args.dep,
                description=args.description,
                signer_node_id=args.signer,
            )
            Path(args.out).write_text(json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps({"package": package["package_id"], "version": package["version"], "out": args.out}))
            return 0
        if args.command == "index":
            packages = [json.loads(Path(path).read_text(encoding="utf-8")) for path in args.package]
            index = PACKAGE.make_index(packages)
            Path(args.out).write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps({"packages": len(index["packages"]), "out": args.out}))
            return 0
        if args.command == "verify":
            value = json.loads(Path(args.file).read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("schema_version") == PACKAGE.INDEX_SCHEMA:
                normalised = PACKAGE.validate_index(value)
                print(json.dumps({"kind": "index", "packages": len(normalised["packages"])}, sort_keys=True))
            else:
                normalised = PACKAGE.validate_package(value)
                print(
                    json.dumps(
                        {"kind": "package", "package": normalised["package_id"], "version": normalised["version"]},
                        sort_keys=True,
                    )
                )
            return 0
        index = json.loads(Path(args.index).read_text(encoding="utf-8"))
        plan = PACKAGE.install_plan(index, args.root)
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    except (OSError, ValueError, PACKAGE.PackageError) as exc:
        print(f"sparknet-package: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
