#!/usr/bin/env python3
"""Render the machine-readable contract manifest from the contract SSOT.

Why this exists
~~~~~~~~~~~~~~~
``contracts/*.json`` is the single source of truth for the fabric's machine
vocabulary — the capability list, the port map, the overlay and the schemas.
Those facts are read by code (``shared/sparknet-authz.py``) and by tests, but
until now nothing put them in one place a reader (or a bundle) could check in a
single pass. This script renders that one place: ``contracts/manifest.json``, a
deterministic inventory that pins each JSON contract by hash and projects the
capability and port tables out of it.

Two consequences worth holding onto:

1. **It is generated, never hand-edited.** The manifest carries a ``do_not_edit``
   marker; ``--check`` fails when a contract changed without the manifest being
   regenerated. That is the drift gate: edit a contract, run ``make render``.
2. **Determinism is the contract.** Sorted keys, sorted tables, a hash of each
   input — the same contracts always render byte-identical output, so ``--check``
   compares text rather than trying to understand it.

Usage::

    scripts/sparknet-render.py            # write contracts/manifest.json
    scripts/sparknet-render.py --check    # fail if it is stale (no write)

Exit codes: 0 ok, 1 stale (``--check``) or an unreadable contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

#: The generated file. Never scanned as an input, never hand-edited.
MANIFEST_NAME = "manifest.json"

#: Bumped only if the manifest's own shape changes.
MANIFEST_SCHEMA_VERSION = "1.0"

_ROLE_ROOT = Path(__file__).resolve().parent.parent


def sha256_file(path: Path) -> str:
    """Return the hex sha256 of ``path`` (read in chunks, never all at once)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(contracts_dir: Path) -> dict:
    """Return the manifest dict rendered from ``contracts_dir``.

    Pure and deterministic: reads ``*.json`` (except the manifest), hashes each,
    and projects the capability and port tables. Raises ``ValueError`` on a
    malformed contract so the caller can fail closed.
    """
    inputs = sorted(p for p in contracts_dir.glob("*.json") if p.name != MANIFEST_NAME)
    if not inputs:
        raise ValueError(f"no JSON contracts under {contracts_dir}")

    contracts = []
    for path in inputs:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}: invalid JSON: {exc}") from exc
        contracts.append(
            {
                "file": path.name,
                "contract": data.get("contract", path.stem),
                "schema_version": data.get("schema_version"),
                "sha256": sha256_file(path),
            }
        )

    caps = json.loads((contracts_dir / "capabilities.json").read_text(encoding="utf-8"))
    known_capabilities = sorted(caps.get("known_capabilities", []))

    ports_src = json.loads((contracts_dir / "ports.json").read_text(encoding="utf-8"))
    ports: dict[str, dict] = {}
    for port, spec in ports_src.get("ports", {}).items():
        ports[port] = {
            "service": spec.get("service"),
            "bound_by": spec.get("bound_by"),
            "implementation_state": spec.get("implementation_state"),
            "runtime": spec.get("runtime"),
        }
    ports = dict(sorted(ports.items(), key=lambda kv: int(kv[0])))

    # The spark-node compose stack: a separate namespace from the fabric ports,
    # carried separately so a shared number (9090 guard/compute, 4222
    # nat-gateway/nats) is not collapsed.
    node_ports: dict[str, dict] = {}
    for port, spec in ports_src.get("node_ports", {}).items():
        node_ports[port] = {
            "service": spec.get("service"),
            "bound_by": spec.get("bound_by"),
            "host_published": spec.get("host_published"),
            "implementation_state": spec.get("implementation_state"),
            "runtime": spec.get("runtime"),
        }
    node_ports = dict(sorted(node_ports.items(), key=lambda kv: int(kv[0])))

    return {
        "contract": "sparknet-contract-manifest",
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_by": "scripts/sparknet-render.py",
        "do_not_edit": True,
        "note": "Generated from contracts/*.json. Regenerate with `make render`.",
        "contracts": contracts,
        "known_capabilities": known_capabilities,
        "ports": ports,
        "node_ports": node_ports,
    }


def render(manifest: dict) -> str:
    """Serialize ``manifest`` deterministically (sorted keys, 2-space, newline)."""
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    root = _ROLE_ROOT
    p = argparse.ArgumentParser(description="render contracts/manifest.json from the contract SSOT")
    p.add_argument(
        "--contracts",
        default=None,
        help="the contracts directory (default: <repo>/contracts)",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="report drift and exit 1 instead of writing",
    )
    args = p.parse_args(argv)

    contracts_dir = Path(args.contracts).expanduser() if args.contracts else root / "contracts"
    if not contracts_dir.is_dir():
        print(f"sparknet-render: not a directory: {contracts_dir}", file=sys.stderr)
        return 1

    try:
        text = render(build(contracts_dir))
    except ValueError as exc:
        print(f"sparknet-render: {exc}", file=sys.stderr)
        return 1

    out = contracts_dir / MANIFEST_NAME

    if args.check:
        if not out.is_file():
            print(f"sparknet-render: {out} is missing — run `make render`", file=sys.stderr)
            return 1
        if out.read_text(encoding="utf-8") != text:
            print(
                f"sparknet-render: {out} is stale — the contracts changed without "
                f"the manifest being regenerated. Run `make render`.",
                file=sys.stderr,
            )
            return 1
        print(f"sparknet-render: {out} is up to date")
        return 0

    out.write_text(text, encoding="utf-8")
    print(f"sparknet-render: wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
