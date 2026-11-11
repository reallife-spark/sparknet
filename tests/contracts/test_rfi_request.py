"""rfi request"""

from __future__ import annotations

from types import ModuleType


def _request(authz: ModuleType, **overrides) -> dict:
    from datetime import datetime, timezone

    params = {
        "request_id": "RFI-1",
        "peer_fingerprint": "a" * 64,
        "question": "what does the guard protect?",
        "scope": ["concepts", "references"],
        "now": datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc),
    }
    params.update(overrides)
    return authz.build_rfi_request(**params)


def test_rfi_request_envelope_matches_the_contract(authz: ModuleType, rfi_schema: dict) -> None:
    """The request field list is pinned like every other envelope's."""
    request = rfi_schema["request"]
    assert tuple(request["fields"]) == authz.RFI_REQUEST_FIELDS
    # Option B: attributed by the overlay, NOT signed. The contract must say so and
    # the code must not grow a signature nobody can verify.
    assert "signature_field" not in request
    assert "signed_by" not in request
    assert request["unsigned"].startswith("the request body carries no signature")
    assert not hasattr(authz, "sign_rfi_request"), "a request signature would be unverifiable theatre"
    assert hasattr(authz, "verify_rfi_request") and hasattr(authz, "build_rfi_request")


def test_rfi_request_round_trips(authz: ModuleType) -> None:
    from datetime import datetime, timezone

    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    req = _request(authz, now=now)
    assert "signature_b64" not in req
    assert authz.verify_rfi_request(req, expected_fingerprint="a" * 64, now=now) == (True, "")


def test_rfi_request_scope_is_normalised(authz: ModuleType) -> None:
    """Two orderings of one allow-list are one request, so scope is sorted+deduped."""
    req = _request(authz, scope=["references", "concepts", "references"])
    assert req["scope"] == ["concepts", "references"]


def test_rfi_request_attribution_is_the_overlay_fingerprint(authz: ModuleType) -> None:
    """A peer may not ask as another peer: the body's fingerprint must match the
    overlay-derived one the Master supplies."""
    from datetime import datetime, timezone

    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    req = _request(authz, now=now)
    ok, reason = authz.verify_rfi_request(req, expected_fingerprint="b" * 64, now=now)
    assert not ok and reason == authz.REASON_RFI_REQ_WRONG_PEER


def test_rfi_request_expires_and_cannot_be_replayed(authz: ModuleType) -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    req = _request(authz, now=now)
    # Fresh, unseen nonce: ok.
    assert authz.verify_rfi_request(req, expected_fingerprint="a" * 64, now=now)[0] is True
    # Past its window (default ttl 300s).
    late = authz.verify_rfi_request(req, expected_fingerprint="a" * 64, now=now + timedelta(seconds=301))
    assert late == (False, authz.REASON_RFI_REQ_EXPIRED)
    # A reused nonce is a replay.
    again = authz.verify_rfi_request(req, expected_fingerprint="a" * 64, now=now, seen_nonces=[req["nonce"]])
    assert again == (False, authz.REASON_RFI_REQ_REPLAYED)


def test_rfi_request_issued_in_the_future_is_refused(authz: ModuleType) -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    req = _request(authz, now=now + timedelta(seconds=3600))
    ok, reason = authz.verify_rfi_request(req, expected_fingerprint="a" * 64, now=now)
    assert not ok and reason == authz.REASON_RFI_REQ_NOT_YET_VALID


def test_rfi_request_malformed_shapes_are_refused(authz: ModuleType) -> None:
    from datetime import datetime, timezone

    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    good = _request(authz, now=now)
    kwargs = {"expected_fingerprint": "a" * 64, "now": now}
    # An extra field: a request carries exactly its declared shape.
    assert authz.verify_rfi_request({**good, "escalate": True}, **kwargs)[1] == authz.REASON_RFI_REQ_MALFORMED
    # A missing required field.
    missing = {k: v for k, v in good.items() if k != "question"}
    assert authz.verify_rfi_request(missing, **kwargs)[1] == authz.REASON_RFI_REQ_MALFORMED
    # An empty required string.
    assert authz.verify_rfi_request({**good, "request_id": ""}, **kwargs)[1] == authz.REASON_RFI_REQ_MALFORMED
    # scope of the wrong type.
    assert authz.verify_rfi_request({**good, "scope": "concepts"}, **kwargs)[1] == authz.REASON_RFI_REQ_MALFORMED
    assert authz.verify_rfi_request({**good, "scope": [1, 2]}, **kwargs)[1] == authz.REASON_RFI_REQ_MALFORMED


def test_rfi_request_verification_never_raises(authz: ModuleType) -> None:
    from datetime import datetime, timezone

    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    for junk in (None, "not-a-dict", 42, [], {}, {"peer_fingerprint": None}, {"nonce": "x"}):
        ok, reason = authz.verify_rfi_request(junk, expected_fingerprint="a" * 64, now=now)
        assert not ok and isinstance(reason, str) and reason


def test_rfi_request_builder_refuses_an_empty_question(authz: ModuleType) -> None:
    import pytest as _pytest

    for bad in ("", "   "):
        with _pytest.raises(authz.AuthzError):
            authz.build_rfi_request(request_id="R", peer_fingerprint="a" * 64, question=bad)
