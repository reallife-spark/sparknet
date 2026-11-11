"""roles"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from contract_helpers import (
    MASTER,
    PEER,
    REPO_ROOT,
)


def test_contract_declares_exactly_two_roles(identity_schema: dict):
    assert set(identity_schema["roles"]) == {"master", "peer"}, (
        f"role vocabulary is {sorted(identity_schema['roles'])} — adding a role is a "
        f"contract change both roles must adopt in the same commit"
    )


@pytest.mark.parametrize("role_dir", [PEER, MASTER], ids=["peer-node", "master-node"])
def test_a_node_declares_itself_peer_until_it_is_elected(role_dir: Path):
    """No deployment site may assert `role: master`.

    This replaced an assertion that `master-node/` must declare `role: master`,
    which encoded the pre-election model where the Master was a separate species
    with its own identity. Under the elected model a Master *is* a peer that won a
    unanimous election, so the honest manifest for a master-capable node says
    `peer` and carries no claim to authority.

    The direction matters: a node that claimed `master` because of where it was
    installed would be a node asserting authority it has not been granted, and
    the trust root is what grants it. Prose cannot confer it, and neither can the
    directory a bundle was extracted into.
    """
    manifests = role_dir / "manifests"
    if not manifests.is_dir():
        pytest.skip(f"{role_dir.name}/manifests does not exist")
    checked = 0
    for path in sorted(manifests.glob("*.json")):
        data = json.loads(path.read_text())
        if "role" in data:
            assert data["role"] == "peer", (
                f"{role_dir.name}/{path.name} claims {data['role']!r}. Authority "
                f"comes from a signed cluster trust root, not from deployment."
            )
            checked += 1
    assert checked, f"{role_dir.name}/manifests holds no role declaration to check"


def test_a_master_capable_node_is_eligible_and_claims_no_key():
    """The pre-election state must be explicit, not merely implied by the role.

    Fail-closed is the whole property: until a unanimous cluster trust root has
    been signed (every member of the pair or trio), this node must be recorded
    as eligible but unkeyed. A manifest
    that quietly carried an operational key, or omitted the election block, would
    let a freshly provisioned node be treated as if it already had authority.
    """
    path = MASTER / "manifests" / "node-identity.json"
    assert path.is_file(), "master-node/manifests/node-identity.json is missing"
    data = json.loads(path.read_text())

    election = data.get("election")
    assert isinstance(election, dict), "node-identity.json must state its election state"
    assert election.get("eligible") is True, "a node deployed from master-node/ is master-eligible by definition"
    assert election.get("elects_itself") is False, "a node may vote for itself but must not be able to install itself"

    operational = data.get("operational_key")
    assert isinstance(operational, dict), "node-identity.json must state its key state"
    assert operational.get("held") is False, (
        "the template must not claim the operational key; only a signed trust root confers it"
    )

    assert "cluster_pubkey_b64" in data, (
        "the node's cluster public key is what goes into the trust root and must have a slot here, even if unset"
    )


def test_no_role_manifest_asserts_current_master_state():
    """Nothing in a *template* may claim the node is already Master.

    Master state is runtime — it lives in the registry the operational key signs,
    not in a file shipped with a bundle.
    """
    for role_dir in (PEER, MASTER):
        manifests = role_dir / "manifests"
        if not manifests.is_dir():
            continue
        for path in sorted(manifests.glob("*.json")):
            text = path.read_text().lower()
            assert '"master": true' not in text, (
                f"{role_dir.name}/{path.name} asserts it is master; that state is "
                f"runtime and must come from a signed registry entry"
            )
            assert '"elected": true' not in text, f"{role_dir.name}/{path.name} asserts an election it has not run"


# Where the role vocabulary must be current. Provenance is deliberately excluded:
# `references/` holds captured external material and `plans/` holds superseded
# design documents, and both may legitimately record what things were called at
# the time. They are history, not specification.
VOCABULARY_SURFACES = (
    "contracts",
    "shared",
    "scripts",
    "tests",
    "master-node",
    "peer-node/manifests",
    "peer-node/configs",
    "peer-node/services",
    "peer-node/scripts",
    "peer-node/tests",
    "peer-node/docs",
    "peer-node/skills",
)
SCAN_SUFFIXES = {".json", ".md", ".py", ".sh", ".template", ".conf", ""}


def test_nothing_in_the_repo_still_says_worker():
    """`worker` was the pre-split name for the peer role.

    It must survive nowhere that a reader treats as current. A stale reference
    is how someone concludes there is a third role, or greps for a role the
    contract does not define.
    """
    offenders = []
    for surface in VOCABULARY_SURFACES:
        root = REPO_ROOT / surface
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            if {"__pycache__", ".pytest_cache", ".ruff_cache"} & set(path.parts):
                continue
            # Vendored role-local skills are third-party content, not current
            # sparknet vocabulary; upstream prose legitimately says "worker".
            if ".opencode" in path.parts:
                continue
            # Plans are provenance: they may record what things were called at
            # the time (see the VOCABULARY_SURFACES comment above).
            if "plans" in set(path.parts):
                continue
            # This file names the old vocabulary on purpose, to search for it.
            if path.resolve() == Path(__file__).resolve():
                continue
            # vLLM 0.2.7's package literally contains a `vllm/worker` path;
            # that is third-party layout, not the pre-split role vocabulary.
            if path.name == "sparknet-vllm-kv-patch.sh":
                continue
            try:
                text = path.read_text()
            except (UnicodeDecodeError, OSError):
                continue
            for match in re.finditer(r"\bworkers?\b", text, re.I):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}")
    assert not offenders, f"the pre-split 'worker' vocabulary survives at: {offenders}"


def test_master_documents_the_manifest_gap_instead_of_hiding_it():
    """No master identity manifest exists yet, and that is deliberate.

    A Master manifest needs a real signing key. Shipping one with a placeholder
    key would look authoritative and authorise nothing, so the directory is
    absent until build plan Step 1 — and the charter must say so rather than
    listing a `manifests/` row as though it were there.
    """
    manifests = MASTER / "manifests"
    if manifests.exists():
        pytest.skip("master-node/manifests exists — Step 1 may have landed")
    charter = (MASTER / "AGENTS.md").read_text()
    row = next((ln for ln in charter.splitlines() if "`manifests/`" in ln), None)
    assert row is not None, "the charter no longer mentions manifests/ at all"
    assert re.search(r"not present yet|does not exist|arrives with", row, re.I), (
        f"the charter lists `manifests/` as if it exists, but the directory is absent: {row!r}"
    )
