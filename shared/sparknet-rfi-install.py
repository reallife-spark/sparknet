#!/usr/bin/env python3
"""Accept an RFI answer on a peer: the one rule, stated once.

Information reaches a node's ``01_Inbox/`` from the Master as a signed *answer*:
a digest-bound payload with a named destination, signed over a projection that
includes both (``contracts/rfi-schema.json``).

Two surfaces will install answers — the guard's ``POST /api/v1/rfi`` route (the
live channel, not built yet) and an operator carrying an artifact to a node whose
daemon is not running. They must accept and refuse exactly the same things, which
is why the rule lives here rather than in whichever surface was written first. A
second copy of "what makes an answer acceptable" is how the live path and the
recovery path drift, and the drift is invisible until the path that is wrong is
the one you need.

What accepting means
~~~~~~~~~~~~~~~~~~~~

1. the artifact carries exactly the declared fields plus its signature;
2. the signature verifies under the pinned Master key, over the canonical
   projection (``authz.rfi_answer_message``);
3. ``content_sha256`` is the digest of the decoded content — the payload is bound
   by digest rather than carried inside the projection, so this is the step that
   makes the content part of what the Master authorised;
4. ``peer_fingerprint`` is this peer's, so an answer prepared for another node
   cannot be installed here;
5. ``item_name`` is a single safe component, because it is a write destination;
6. the answer is within its window, and its ``request_id`` has not already been
   installed here.

The item is written *before* the request id is recorded, so a crash between the
two writes leaves the item with no record: re-delivery is then accepted rather
than refused forever. The reverse order would record an acceptance for an item
that never landed, and a ledger claiming a delivery that did not happen is worse
than a duplicate.

Installing also appends an ``inbox_acceptance`` block with source ``master-node``.
Master-origin material may be executed on notice per ``tracking-schema.json``
``inbox_dispatch``, but it is still recorded: the trail of what arrived is what
makes the arrival attributable to a signing role rather than to whoever could
write into the directory.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Where this node records the answers it has installed, so a re-delivery is a
#: duplicate rather than a second copy of the same information.
INSTALL_RECORD_RELPATH = Path("manifests") / "rfi-installation.json"


def installation_record(vault_root: Path) -> dict[str, Any]:
    path = vault_root / INSTALL_RECORD_RELPATH
    if not path.is_file():
        return {"schema": "sparknet-rfi-installation/1", "request_ids": []}
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # A corrupt record must not become a reason to accept a replay, so it is
        # read as empty and the next successful install rewrites it.
        return {"schema": "sparknet-rfi-installation/1", "request_ids": []}
    if not isinstance(record, dict) or not isinstance(record.get("request_ids"), list):
        return {"schema": "sparknet-rfi-installation/1", "request_ids": []}
    return record


def installed_request_ids(vault_root: Path) -> list[str]:
    return [str(x) for x in installation_record(vault_root).get("request_ids") or []]


def _atomic_write(path: Path, data: bytes) -> None:
    """Write via a temp file in the same directory, so a reader never sees half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp).unlink()
        raise


def accept_answer(
    vault_root: Path,
    artifact: Any,
    *,
    authz: Any,
    provenance: Any,
    master_public_key: Any,
    peer_fingerprint: str,
    user_record: dict[str, Any],
    now: datetime | None = None,
    ttl_seconds: int = 3600,
) -> dict[str, Any]:
    """Verify one RFI answer and install it, or refuse with the contract's reason.

    Returns ``{"status": "installed"|"refused", "reason": str, ...}`` and never
    raises for a refusal, so a caller cannot turn an unacceptable artifact into an
    unhandled error and thereby into a half-written inbox.
    """
    ok, reason, content = authz.verify_rfi_answer(
        artifact,
        master_public_key=master_public_key,
        peer_fingerprint=peer_fingerprint,
        now=now,
        ttl_seconds=ttl_seconds,
        installed_request_ids=installed_request_ids(vault_root),
    )
    if not ok:
        return {"status": "refused", "reason": reason, "item": None}

    item_name = str(artifact["item_name"])
    request_id = str(artifact["request_id"])
    target = vault_root / "01_Inbox" / item_name
    # The destination is re-checked here even though the verifier checked it: this
    # is the line that writes, and a write guarded by a check somewhere else is a
    # write guarded by nothing once that other code moves.
    authz.check_rfi_item_name(item_name)
    if target.resolve().parent != (vault_root / "01_Inbox").resolve():
        return {"status": "refused", "reason": authz.REASON_RFI_UNSAFE_ITEM_NAME, "item": None}

    _atomic_write(target, content)

    record = installation_record(vault_root)
    ids = [str(x) for x in record.get("request_ids") or []]
    if request_id not in ids:
        ids.append(request_id)
    record = {
        "schema": "sparknet-rfi-installation/1",
        "request_ids": ids,
        "last_installed": {
            "request_id": request_id,
            "item": f"01_Inbox/{item_name}",
            "content_sha256": str(artifact["content_sha256"]),
            "installed_at": (now or datetime.now(timezone.utc)).isoformat(),
        },
    }
    _atomic_write(
        vault_root / INSTALL_RECORD_RELPATH,
        (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )

    block = provenance.build_inbox_acceptance(
        vault_root,
        item=f"01_Inbox/{item_name}",
        source="master-node",
        decision="accepted",
        note_refs=[f"01_Inbox/{item_name}"],
        record=user_record,
        clock=(lambda: now) if now else None,
    )
    provenance.append_block(vault_root, block)
    return {
        "status": "installed",
        "reason": "",
        "item": f"01_Inbox/{item_name}",
        "request_id": request_id,
        "content_sha256": str(artifact["content_sha256"]),
        "acceptance_id": block.get("acceptance_id"),
    }
