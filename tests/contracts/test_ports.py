"""ports"""

from __future__ import annotations

import re

import pytest
from contract_helpers import (
    PEER,
    REPO_ROOT,
    guard_port,
)


def test_the_two_significant_ports_are_not_transposed(ports: dict):
    """9090 is the peer's guard; 8090 is the Master's peer-intake listener.

    Transposing them is invisible until a request is POSTed to a listener that
    either does not exist or does the wrong thing. 8090 was `master-instant-push`
    until fabric Step 69C re-scoped it (the instant-push purpose was superseded by
    Step 6's 9090 registry push); the anti-transposition invariant is unchanged —
    one peer-bound 9090, one master-bound 8090, never swapped.
    """
    guard_number, guard = guard_port(ports)
    assert guard["bound_by"] == "peer" and guard_number == 9090

    intake = [(int(p), s) for p, s in ports["ports"].items() if s["service"] == "master-peer-intake"]
    assert len(intake) == 1, f"expected exactly one master-peer-intake port, found {intake}"
    intake_number, intake_spec = intake[0]
    assert intake_spec["bound_by"] == "master" and intake_number == 8090


def test_guard_port_is_overlay_only_and_implemented(ports: dict):
    _, guard = guard_port(ports)
    assert guard["overlay_only"] is True, "the guard must be unreachable from the WAN by design"
    assert guard["implementation_state"] == "implemented"
    assert "own overlay address" in guard["binds_to"], "the guard must bind its own overlay address, never a wildcard"


PORT_STATES = {"implemented", "provisioned", "spec-only"}
PORT_RUNTIME = {"running", "not-listening", "not-verifiable-here"}


def test_every_port_declares_both_axes_with_known_values(ports: dict):
    """implementation_state and runtime answer different questions.

    Collapsing them into one boolean is what let a 110-line CLI be described as
    implemented, so both axes are now mandatory and enumerated.
    """
    for number, spec in ports["ports"].items():
        assert spec.get("implementation_state") in PORT_STATES, (
            f"port {number} ({spec['service']}) has an unknown or missing "
            f"implementation_state: {spec.get('implementation_state')!r}"
        )
        assert spec.get("runtime") in PORT_RUNTIME, (
            f"port {number} ({spec['service']}) has an unknown or missing runtime: {spec.get('runtime')!r}"
        )


def test_the_conflated_boolean_is_gone(ports: dict):
    """`implemented: true` is exactly the claim that was false. Do not restore it."""
    for number, spec in ports["ports"].items():
        assert "implemented" not in spec, (
            f"port {number} still uses the boolean 'implemented'; use implementation_state plus runtime"
        )


def test_running_requires_an_observed_listener(ports: dict):
    """A port may only claim `running` if it actually accepts a connection here.

    This is the test that would have caught 4096, 4097, 4098 and 4100 being
    called implemented while nothing was listening. It is deliberately narrow:
    overlay services whose interface is absent here are `not-verifiable-here`
    and are exempt, because their absence is not evidence of a fault.
    """
    import socket

    for number, spec in ports["ports"].items():
        if spec.get("runtime") != "running":
            continue
        sock = socket.socket()
        sock.settimeout(1.0)
        try:
            sock.connect(("127.0.0.1", int(number)))
        except OSError as exc:
            pytest.fail(
                f"port {number} ({spec['service']}) claims runtime=running but "
                f"nothing accepted a loopback connection: {exc}"
            )
        finally:
            sock.close()


def test_a_service_marked_implemented_must_name_a_bind_path(ports: dict):
    """`implemented` is a claim about a bind, so the evidence must be on record.

    The inverse is the part that bit us: `implemented: true` on a file with no
    bind code anywhere. Any port asserting `implemented` must therefore either
    carry runtime evidence or say in runtime_why why it could not be observed.
    """
    for number, spec in ports["ports"].items():
        if spec.get("implementation_state") != "implemented":
            continue
        assert spec.get("runtime_why") or spec.get("runtime") == "running", (
            f"port {number} ({spec['service']}) claims implementation_state="
            f"implemented with neither a running listener nor a recorded reason "
            f"it could not be observed"
        )


def test_ports_that_are_not_implemented_say_so_and_point_at_a_real_plan(ports: dict):
    """An unimplemented port must be flagged, not merely absent from code."""
    for number, spec in ports["ports"].items():
        if spec["implementation_state"] == "implemented":
            continue
        status = spec.get("status", "")
        assert re.search(r"SPEC ONLY|provisioned|PROVISIONED|no listener", status, re.I), (
            f"port {number} ({spec['service']}) is {spec['implementation_state']} "
            f"but its status does not say so: {status!r}"
        )
        referenced = re.findall(
            r"((?:\.\./)?peer-node/PLAN\.md|master-node/PLAN\.md|master-node/plans/MASTER_ADMIN_PLAN\.md)",
            status,
        )
        assert referenced, f"port {number} must point at the plan step that will build it"
        for ref in referenced:
            resolved = (REPO_ROOT / ref).resolve()
            assert resolved.is_file(), (
                f"port {number} points at {ref}, which does not resolve to a file from the repo root: {resolved}"
            )


def test_no_service_claims_two_ports(ports: dict):
    seen: dict[str, int] = {}
    for number, spec in ports["ports"].items():
        assert spec["service"] not in seen, f"{spec['service']} claims both {seen[spec['service']]} and {number}"
        seen[spec["service"]] = int(number)


def test_guard_daemon_uses_the_contract_port_and_binds_narrow(ports: dict):
    number, _ = guard_port(ports)
    source = (PEER / "services" / "sparknet-guard-d.py").read_text()
    assert str(number) in source, "the guard daemon does not use the port named in contracts/ports.json"
    assert "0.0.0.0" not in source, (
        "the guard must not bind a wildcard address — that would expose the approval endpoint on every interface"
    )
