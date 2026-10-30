#!/usr/bin/env python3
"""Accept a registry publication on a peer: the one rule, stated once.

A registry reaches a peer as a *publication*: the Master's registry document
wrapped with a monotonic sequence and a publication time, with a signature over
that projection and over the document's digest
(``contracts/registry-publication.json``).

Two peer surfaces install publications: the guard's ``POST /api/v1/registry``
(the live channel) and ``peer-node/services/sparknet-registry-client.py`` (the
offline/operator path, for a node with no daemon running). They must accept and
refuse exactly the same things - the same reason the approval envelope lives in
``sparknet-authz.py`` instead of once per surface. A second copy of "what makes
a publication acceptable" is how the live path and the recovery path drift, and
the drift is invisible until the path that is wrong is the one you need.

What accepting means
~~~~~~~~~~~~~~~~~~~~

1. the artifact has exactly the publication fields plus its signature;
2. the signature verifies under the pinned Master key, over the canonical
   projection (``authz.registry_publication_message``);
3. the registry names the same Master key the node has pinned;
4. the registry conforms to ``contracts/registry-schema.json``, entries included
   (``sparknet-registry-schema.py``), so a peer never installs a shape no other
   node agrees with;
5. the sequence is not lower than the installed one. A lower sequence is a
   rollback - an older registry in which this node was not yet revoked is
   exactly what an attacker with write access to the channel would serve.
6. an *equal* sequence is only the same publication: it is accepted as a no-op
   (``REGISTRY_ALREADY_INSTALLED``, nothing written) when its digest matches the
   installed digest, and refused as ``stale_publication`` when it does not,
   because an equal sequence with different content is a fork, not a replay.
   Accepting the equal case is what makes the Master's 60 s re-delivery a
   success instead of a unit that is red on every tick.

The sequence record is written *after* the registry, so a crash between the two
writes leaves the new registry with the old record: re-delivery of the same
publication is then accepted (idempotent) rather than refused forever. The
window in which that is true is the only reason the order matters.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REGISTRY_FILE = "node-authorizations.json"
INSTALLATION_FILE = "registry-installation.json"
PINNED_KEY_FILE = "keys/master-ed25519.pub.b64"


class InstallError(Exception):
    """A refused publication. Carries the HTTP status the guard should send."""

    def __init__(self, status: int, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.status = status
        self.code = code
        self.detail = detail


def pinned_key_path(vault_root: Path) -> Path:
    return Path(vault_root) / "manifests" / PINNED_KEY_FILE


def load_pinned_key(vault_root: Path, authz: Any) -> Any | None:
    """The Master key this node trusts, or None when nothing is pinned."""
    path = pinned_key_path(vault_root)
    if not path.is_file():
        return None
    try:
        return authz.load_public_key(path)
    except Exception:
        return None


def installation_record(vault_root: Path) -> dict[str, Any]:
    path = Path(vault_root) / "manifests" / INSTALLATION_FILE
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def installed_sequence(vault_root: Path) -> int:
    try:
        return int(installation_record(vault_root).get("sequence") or 0)
    except (TypeError, ValueError):
        return 0


def verify_publication(publication: Any, public_key: Any, authz: Any, schema: Any) -> dict[str, Any]:
    """Check one publication; return what it says. Raises :class:`InstallError`."""
    if not isinstance(publication, dict):
        raise InstallError(400, "malformed_publication", "the publication must be an object")

    expected = set(authz.REGISTRY_PUBLICATION_FIELDS) | {"signature_b64"}
    if set(publication) != expected:
        raise InstallError(
            400,
            "malformed_publication",
            f"expected fields {sorted(expected)}, found {sorted(publication)}",
        )
    signature = publication.get("signature_b64")
    if not isinstance(signature, str) or not signature:
        raise InstallError(400, "malformed_publication", "no signature_b64")

    unsigned = {name: publication[name] for name in authz.REGISTRY_PUBLICATION_FIELDS}
    try:
        message = authz.registry_publication_message(unsigned)
    except Exception as exc:
        raise InstallError(400, "malformed_publication", str(exc)) from exc

    if not authz.verify_signature(public_key, signature, message):
        raise InstallError(403, "bad_signature", "the publication does not verify under the pinned Master key")

    registry = unsigned["registry"]
    if registry.get("master_public_key_b64") != authz.public_key_b64(public_key):
        raise InstallError(
            403,
            "wrong_master_key",
            "the registry names a Master key other than the one pinned on this node",
        )

    try:
        problems = schema.validate_document(registry, schema.load_schema(), authz)
    except Exception as exc:
        raise InstallError(503, "no_contract", f"the registry contract cannot be loaded: {exc}") from exc
    if problems:
        raise InstallError(400, "invalid_registry", "; ".join(problems[:5]))

    entries = registry.get("authorizations") or []
    return {
        "sequence": int(unsigned["sequence"]),
        "published_at": unsigned["published_at"],
        "registry_sha256": unsigned["registry_sha256"],
        "registry": registry,
        "entries": len(entries),
    }


def _atomic_write_text(path: Path, text: str) -> None:
    """Replace ``path`` with ``text`` in one step, readable by concurrent readers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False, encoding="utf-8"
        ) as handle:
            name = handle.name
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    except Exception:
        if name is not None:
            with contextlib.suppress(OSError):
                os.unlink(name)
        raise


def accept_publication(
    vault_root: Path,
    publication: Any,
    authz: Any,
    schema: Any,
    public_key: Any,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Verify and (unless ``dry_run``) install one publication.

    Returns ``{"status", "sequence", "registry_sha256", "entries", ...}``. In
    dry-run the status is ``REGISTRY_VERIFIED_DRY_RUN`` and nothing is written;
    a new publication is ``REGISTRY_INSTALLED``; re-delivering the publication
    that is already installed is ``REGISTRY_ALREADY_INSTALLED`` and writes
    nothing.

    Idempotent re-delivery matters because the Master re-pushes the current
    publication on a timer: without it every steady-state tick would be refused
    as a replay and the delivery unit would stay red. Equality is only accepted
    when the digest matches too — an equal sequence carrying a *different*
    registry is a fork, not a replay, and is refused.
    """
    verified = verify_publication(publication, public_key, authz, schema)
    previous = installation_record(vault_root)
    try:
        previous_sequence = int(previous.get("sequence") or 0)
    except (TypeError, ValueError):
        previous_sequence = 0
    result = {
        "sequence": verified["sequence"],
        "published_at": verified["published_at"],
        "registry_sha256": verified["registry_sha256"],
        "entries": verified["entries"],
    }

    if verified["sequence"] < previous_sequence:
        raise InstallError(
            409,
            "stale_publication",
            f"sequence {verified['sequence']} is lower than the installed sequence {previous_sequence}; "
            "a lower sequence is a rollback",
        )
    if verified["sequence"] == previous_sequence and previous_sequence:
        if previous.get("registry_sha256") == verified["registry_sha256"]:
            return {"status": "REGISTRY_ALREADY_INSTALLED", **result}
        raise InstallError(
            409,
            "stale_publication",
            f"sequence {verified['sequence']} is already installed with a different registry digest",
        )

    if dry_run:
        return {"status": "REGISTRY_VERIFIED_DRY_RUN", **result}

    manifests = Path(vault_root) / "manifests"
    # Registry first, record second: see the module docstring. A crash in
    # between makes the publication idempotent instead of permanently refusable.
    _atomic_write_text(manifests / REGISTRY_FILE, json.dumps(verified["registry"], indent=2) + "\n")
    record = {
        **result,
        "installed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    _atomic_write_text(manifests / INSTALLATION_FILE, json.dumps(record, indent=2) + "\n")
    return {"status": "REGISTRY_INSTALLED", **result}
