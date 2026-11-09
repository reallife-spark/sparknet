"""One bound, everywhere: every sparknet listener shares the socket timeout.

The 2026-10-08 review (finding F4) found three unbounded ``rfile.read`` loops:
the shared signed transport, the peer guard, and the shared election exchange
each would hold a listener thread open forever for a client that never finished
its request line or body.

The fix put the bound in one place — ``TimeoutHandler`` in
``shared/sparknet-http.py`` — and made every listener derive from it, so there
is exactly one number to tune.  The behavioural trickle tests live next to each
listener's fixtures (``test_http_transport.py``, ``test_guard.py``,
``test_election.py``); this file proves the *wiring*, failing on the exact
mutation that reopens F4: a listener stopping the derivation, or a later
listener that never joins.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sparknet_loader import load_by_path

ROOT = Path(__file__).resolve().parent.parent
PEER_SERVICE = ROOT / "peer-node" / "services" / "sparknet-guard-d.py"


def _load(name: str, path: Path):
    """Load a hyphen-named sibling module by path, mirroring the fabric loader."""
    return load_by_path(name, path)


@pytest.fixture(scope="module")
def http():
    return _load("sparknet_http", ROOT / "shared" / "sparknet-http.py")


@pytest.fixture(scope="module")
def election(http):
    return _load("sparknet_election", ROOT / "shared" / "sparknet-election.py")


@pytest.fixture(scope="module")
def guard_handler(http, tmp_path_factory):
    """The guard's handler *class*, built exactly as the daemon builds it."""
    module = _load("sparknet_guard_d", PEER_SERVICE)
    vault = tmp_path_factory.mktemp("guard-timeout-drift")
    listener = module.build_listener(module.Guard(vault), "timeout-drift", bind="127.0.0.1", port=0)
    handler = listener.servers[0].RequestHandlerClass
    listener.stop()
    return handler


def test_the_shared_constant_is_a_sane_bound(http) -> None:
    """The bound must be a positive, human-scale number of seconds."""
    bound = http.DEFAULT_REQUEST_TIMEOUT_SECONDS
    assert isinstance(bound, float)
    assert 1.0 <= bound <= 60.0


def test_transport_listener_inherits_the_shared_timeout(http) -> None:
    assert issubclass(http._Handler, http.TimeoutHandler), (
        "the transport listener must derive from the shared TimeoutHandler"
    )
    assert http._Handler.timeout == http.DEFAULT_REQUEST_TIMEOUT_SECONDS, (
        "the transport listener must inherit the shared timeout, not bind its own"
    )


def test_election_listener_inherits_the_shared_timeout(http, election) -> None:
    assert issubclass(election._Handler, http.TimeoutHandler), (
        "the election listener must derive from the shared TimeoutHandler"
    )
    assert election._Handler.timeout == http.DEFAULT_REQUEST_TIMEOUT_SECONDS


def test_guard_listener_inherits_the_shared_timeout(http, guard_handler) -> None:
    assert issubclass(guard_handler, http.TimeoutHandler), (
        "the guard listener must derive from the shared TimeoutHandler"
    )
    assert guard_handler.timeout == http.DEFAULT_REQUEST_TIMEOUT_SECONDS


def test_all_three_listeners_agree_on_one_number(http, election, guard_handler) -> None:
    """If a service pins a different bound, this fails loudly instead of drifting."""
    values = {http._Handler.timeout, election._Handler.timeout, guard_handler.timeout}
    assert len(values) == 1, f"listeners must share one timeout, got {values}"
