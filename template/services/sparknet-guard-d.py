#!/usr/bin/env python3
# Master-Gated Immutable File Guard (minimal viable implementation)
import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

def log(level, msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"[{ts}] [{level}] {msg}")

def load_manifest(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        log("ERROR", f"Failed to load manifest {path}: {e}")
        raise

def sha256_file(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""

def main():
    p = argparse.ArgumentParser(description="Sparknet Critical File Guard (MVI)")
    p.add_argument("--dry-run", action="store_true", help="No mutations")
    p.add_argument("--check-manifest", action="store_true", help="Validate manifest only")
    args = p.parse_args()

    script_dir = Path(__file__).resolve().parent
    vault_root = Path(os.environ.get("SPARKNET_VAULT_ROOT", "/mnt/knowledge/sparknet"))
    manifest_path = vault_root / "manifests" / "critical-manifest.json"

    log("INFO", "sparknet-guard starting")
    log("INFO", f"Vault root: {vault_root}")
    log("INFO", f"Manifest: {manifest_path}")

    try:
        manifest = load_manifest(manifest_path)
    except Exception:
        sys.exit(1)

    protected = manifest.get("protected_paths", [])
    log("INFO", f"Protected paths: {len(protected)}")

    for pp in protected[:5]:
        log("INFO", f"  - {pp}")
    if len(protected) > 5:
        log("INFO", f"  ... (+{len(protected)-5} more)")

    if args.check_manifest:
        # Basic validation
        ok = isinstance(protected, list) and all(isinstance(x, str) for x in protected)
        if ok:
            log("INFO", "Manifest validation: PASSED")
            sys.exit(0)
        else:
            log("ERROR", "Manifest validation: FAILED")
            sys.exit(1)

    if args.dry_run:
        log("INFO", "DRY-RUN: No file mutations will be performed")
        log("INFO", "Would require Master-signed approvals (Ed25519) per Plan-Permission-Execute")
        log("INFO", "sparknet-guard completed (DRY-RUN)")
        sys.exit(0)

    log("INFO", "Template mode: no action taken")
    log("INFO", "sparknet-guard completed")
    sys.exit(0)

if __name__ == "__main__":
    main()
