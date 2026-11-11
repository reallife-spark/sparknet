"""telemetry"""

from __future__ import annotations

from types import ModuleType

import pytest
from contract_helpers import (
    load,
)


@pytest.fixture(scope="module")
def telemetry_schema() -> dict:
    return load("telemetry-schema.json")


def _report(authz: ModuleType, **overrides) -> dict:
    from datetime import datetime, timezone

    params = {
        "kind": "status",
        "peer_fingerprint": "a" * 64,
        "payload": {"alive": True},
        "now": datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc),
    }
    params.update(overrides)
    return authz.build_telemetry_report(**params)


def test_telemetry_envelope_matches_the_contract(authz: ModuleType, telemetry_schema: dict) -> None:
    report = telemetry_schema["report"]
    assert tuple(report["fields"]) == authz.TELEMETRY_REPORT_FIELDS
    assert tuple(report["kinds"]) == authz.TELEMETRY_KINDS
    # Overlay-attributed, not signed — the same Step 68A decision, generalised.
    assert "signature_field" not in report and "signed_by" not in report
    assert report["unsigned"].startswith("the report carries no signature")
    assert not hasattr(authz, "sign_telemetry_report"), "an unverifiable signature would be theatre"
    assert hasattr(authz, "build_telemetry_report") and hasattr(authz, "verify_telemetry_report")


def test_telemetry_carries_no_authority(authz: ModuleType, telemetry_schema: dict) -> None:
    """The kind vocabulary is observability only — no authority verb can ride it."""
    assert telemetry_schema["report"]["no_authority"].startswith("a telemetry report cannot grant")
    authority_verbs = {"grant", "revoke", "escalate", "approve", "widen", "sign"}
    assert not (authority_verbs & set(authz.TELEMETRY_KINDS))


def test_telemetry_report_round_trips(authz: ModuleType) -> None:
    from datetime import datetime, timezone

    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    report = _report(authz, now=now)
    assert "signature_b64" not in report
    assert authz.verify_telemetry_report(report, expected_fingerprint="a" * 64, now=now) == (True, "")
    # An empty payload is a legitimate heartbeat.
    beat = _report(authz, kind="liveness", payload={}, now=now)
    assert authz.verify_telemetry_report(beat, expected_fingerprint="a" * 64, now=now)[0] is True


def test_telemetry_attribution_is_the_overlay_fingerprint(authz: ModuleType) -> None:
    from datetime import datetime, timezone

    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    report = _report(authz, now=now)
    ok, reason = authz.verify_telemetry_report(report, expected_fingerprint="b" * 64, now=now)
    assert not ok and reason == authz.REASON_TELEMETRY_WRONG_PEER


def test_telemetry_expires_and_cannot_be_replayed(authz: ModuleType) -> None:
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    report = _report(authz, now=now)
    assert authz.verify_telemetry_report(report, expected_fingerprint="a" * 64, now=now)[0] is True
    late = authz.verify_telemetry_report(report, expected_fingerprint="a" * 64, now=now + timedelta(seconds=121))
    assert late == (False, authz.REASON_TELEMETRY_EXPIRED)
    again = authz.verify_telemetry_report(report, expected_fingerprint="a" * 64, now=now, seen_nonces=[report["nonce"]])
    assert again == (False, authz.REASON_TELEMETRY_REPLAYED)


def test_telemetry_malformed_shapes_are_refused(authz: ModuleType) -> None:
    from datetime import datetime, timezone

    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    good = _report(authz, now=now)
    kwargs = {"expected_fingerprint": "a" * 64, "now": now}
    assert authz.verify_telemetry_report({**good, "escalate": True}, **kwargs)[1] == authz.REASON_TELEMETRY_MALFORMED
    assert authz.verify_telemetry_report({**good, "kind": "grant"}, **kwargs)[1] == authz.REASON_TELEMETRY_MALFORMED
    assert authz.verify_telemetry_report({**good, "payload": "not-an-object"}, **kwargs)[1] == (
        authz.REASON_TELEMETRY_MALFORMED
    )
    missing = {k: v for k, v in good.items() if k != "kind"}
    assert authz.verify_telemetry_report(missing, **kwargs)[1] == authz.REASON_TELEMETRY_MALFORMED


def test_telemetry_verification_never_raises(authz: ModuleType) -> None:
    from datetime import datetime, timezone

    now = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    for junk in (None, "x", 42, [], {}, {"kind": None}, {"payload": None}):
        ok, reason = authz.verify_telemetry_report(junk, expected_fingerprint="a" * 64, now=now)
        assert not ok and isinstance(reason, str) and reason


def test_telemetry_builder_refuses_an_unknown_kind(authz: ModuleType) -> None:
    import pytest as _pytest

    with _pytest.raises(authz.AuthzError):
        authz.build_telemetry_report(kind="grant-capability", peer_fingerprint="a" * 64)


def test_every_telemetry_refusal_is_a_reason_the_verifier_or_gate_produces(
    authz: ModuleType, telemetry_schema: dict
) -> None:
    """off_overlay is the listener's source gate (69C); the rest are verifier returns."""
    produced = {
        value
        for value in vars(authz).values()
        if isinstance(value, str) and value.startswith(("malformed", "wrong_", "expired", "not_yet_valid", "replayed_"))
    }
    for code in telemetry_schema["refusals"]:
        assert code == "off_overlay" or code in produced, f"the contract names {code!r}, which nothing produces"
