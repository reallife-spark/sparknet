"""rfi transport"""

from __future__ import annotations

import pytest
from contract_helpers import (
    MASTER,
    PEER,
    REPO_ROOT,
    guard_port,
)

pytestmark = pytest.mark.contract


def test_the_rfi_route_is_the_guard_route_the_contract_names(rfi_schema: dict, ports: dict) -> None:
    """The listener the contract names is the one the guard serves, on 9090.

    Mirrors the registry route pin: a contract that names a route no daemon serves
    is a claim about a listener that does not exist, which is exactly what
    tracking-schema.json's phase_boundary rule forbids.
    """
    transport = rfi_schema["transport"]
    guard = (PEER / "services" / "sparknet-guard-d.py").read_text()
    assert transport["path"] == "/api/v1/rfi"
    assert transport["path"] in guard, "the guard does not serve the RFI route the contract names"
    assert "handle_rfi" in guard, "the guard has no RFI handler"
    assert transport["port"] == 9090
    number, guard_spec = guard_port(ports)
    assert number == 9090
    assert "/api/v1/rfi" in guard_spec["note"], "ports.json's 9090 entry must name the RFI route"


def test_the_guard_can_send_every_rfi_refusal_the_contract_names(rfi_schema: dict) -> None:
    """A documented refusal nobody can send is documentation, not a behaviour.

    `off_overlay` is the do_POST source gate; the rest are mapped to a status by
    the guard's RFI_REFUSAL_STATUS. Every one must be reachable from the guard.
    """
    guard = (PEER / "services" / "sparknet-guard-d.py").read_text()
    for code in rfi_schema["refusals"]:
        assert code in guard, f"the contract documents {code!r}, which the guard cannot send"


def test_the_rfi_implementation_state_matches_the_tree(rfi_schema: dict) -> None:
    """The contract's own status block agrees with what ships — in both directions.

    Built legs name files that exist and the route that serves them; a leg that is
    still deferred must stay honestly marked, so it cannot be silently dropped.
    """
    state = rfi_schema["implementation_state"]
    assert state["listener"].startswith("implemented")
    assert state["master_side_composer"].startswith("implemented")
    assert (PEER / "services" / "sparknet-guard-d.py").is_file()
    composer = MASTER / "scripts" / "sparknet-rfi-answer.sh"
    assert composer.is_file(), "the contract names a composer that does not exist"
    # The composer is wired to something, or the master's nothing-inert rule fails.
    assert "sparknet-rfi-answer.sh" in (MASTER / "Makefile").read_text()

    # 70B built the request leg. Its text must name the route and the service that
    # serves it, and keep the 68A reason there is no signature, so the contract
    # records *why* rather than only *that*.
    request_channel = state["request_channel"]
    assert request_channel.startswith("implemented")
    assert "/api/v1/rfi-request" in request_channel
    assert "sparknet-peer-intake.py" in request_channel
    assert "verify_rfi_request" in request_channel
    assert "fingerprint" in request_channel and "overlay" in request_channel
    assert "RFI_REQUEST_DESIGN.md" in request_channel
    assert (MASTER / "services" / "sparknet-peer-intake.py").is_file()


def test_the_signer_answers_the_rfi_op() -> None:
    """The isolated key holder signs answers the same way it signs publications."""
    signer = (MASTER / "services" / "sparknet-signer.py").read_text()
    assert "sign-rfi-answer" in signer
    assert "sign_rfi_answer" in signer, "the signer must build the answer via the one shared rule"


def test_inbox_arrival_notification_is_contracted_and_wired(tracking: dict) -> None:
    """67B: an arrived item must reach the human, and the contract must say how.

    The mechanism is named (one shared module, *not* the fabric-root plugin, which
    is deliberately unbundled) and the guard actually calls it — so the claim is
    wired rather than aspirational. A contract that says "arrival is notified"
    while no code notifies is the same failure 67A closed for inbox_acceptance.
    """
    dispatch = tracking["inbox_dispatch"]
    assert "notification" in dispatch, "inbox_dispatch no longer states how arrival reaches the human"
    note = dispatch["notification"]
    assert "sparknet-notify.py" in note
    assert "kde-notify.ts" in note, "the note must distinguish the node path from the unbundled fabric-root plugin"
    assert (REPO_ROOT / "shared" / "sparknet-notify.py").is_file()
    guard = (PEER / "services" / "sparknet-guard-d.py").read_text()
    assert "notify_inbox_arrival" in guard, "the guard installs an answer but never tells anyone it arrived"
    # The notification is built into the boundary as a built leg, not left implied.
    assert "notification on arrival" in " ".join(tracking["phase_boundary"]["built_here"])
