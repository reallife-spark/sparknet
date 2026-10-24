"""The Master reflex broker: overlay-only, pinned, fail-open, no authority.

The broker is the only holder of the TypeSafe credential, so these tests pin the
things that would turn a sensor into a liability: it refuses a non-overlay bind,
refuses a peer source in Phase 1, refuses a moving model tag and a credential
readable by anyone else, and abstains on timeout, error, missing credential or
budget exhaustion. The audit line must carry hashes, never state.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from urllib import error as urlerror
from urllib import request as urlrequest

import pytest

ROLE_ROOT = Path(__file__).resolve().parent.parent
BROKER_PATH = ROLE_ROOT / "services" / "sparknet-reflex-broker.py"
UNIT_PATH = ROLE_ROOT / "systemd" / "sparknet-reflex-broker.service"
PORTS = ROLE_ROOT.parent / "contracts" / "ports.json"


@pytest.fixture(scope="module")
def broker() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sparknet_reflex_broker", BROKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def _request(broker: ModuleType, model: str = "jev-1.13.0", node_id: str = "master") -> dict:
    return broker.reflex.make_request(
        "rag.relevance",
        "alpha",
        {"q": {"type": "noul", "instructions": "relevant?"}},
        model,
        "policy-1",
        node_id,
        "req-1",
    )


def test_the_contract_declares_4224_overlay_only() -> None:
    ports = json.loads(PORTS.read_text())
    spec = ports["ports"]["4224"]
    assert spec["service"] == "reflex-broker"
    assert spec["bound_by"] == "master"
    assert spec["overlay_only"] is True
    assert spec["binds_to"] == "10.100.0.1"
    assert spec["implementation_state"] == "implemented"


def test_the_unit_binds_the_overlay_and_names_the_credential() -> None:
    unit = UNIT_PATH.read_text()
    assert "10.100.0.1" in unit
    assert "4224" in unit
    assert "typesafe-api-key" in unit
    assert "0.0.0.0" not in unit


def test_model_must_be_an_exact_jev_tag(broker: ModuleType) -> None:
    assert broker.validate_model("jev-1.13.0") == "jev-1.13.0"
    for bad in ("", "jev-latest", "latest", "gpt-4o"):
        with pytest.raises(broker.BrokerError):
            broker.validate_model(bad)


def test_only_loopback_and_the_master_overlay_are_accepted(broker: ModuleType) -> None:
    assert broker.source_allowed("127.0.0.1") is True
    assert broker.source_allowed("10.100.0.1") is True
    assert broker.source_allowed("10.100.0.2") is False
    assert broker.source_allowed("0.0.0.0") is False


def test_credential_must_be_0600(broker: ModuleType, tmp_path: Path) -> None:
    key = tmp_path / "key"
    key.write_text("secret")
    key.chmod(0o600)
    assert broker.read_key(key) == "secret"
    key.chmod(0o644)
    with pytest.raises(broker.BrokerError, match="0600"):
        broker.read_key(key)
    with pytest.raises(broker.BrokerError, match="missing"):
        broker.read_key(tmp_path / "nope")


def test_vendor_payload_is_three_fields_and_redacted(broker: ModuleType) -> None:
    req = _request(broker)
    req["state"] = {"text": "api_key=supersecret", "ok": "visible"}
    payload = broker.vendor_payload(req)
    assert set(payload) == {"state", "model", "questions"}
    assert "supersecret" not in json.dumps(payload)
    assert "visible" in json.dumps(payload)


def test_decide_returns_a_decision_and_audits_hashes_only(broker: ModuleType, tmp_path: Path) -> None:
    req = _request(broker)
    req["state"] = "api_key=supersecret"
    audit = tmp_path / "reflex.jsonl"
    decision = broker.decide(
        req,
        call=lambda _r: {"type": "noul", "noul": 0.9},
        key="k",
        endpoint="https://example.invalid",
        timeout_s=1.0,
        budget=broker.BudgetLedger(per_node_per_day=10, global_per_day=10),
        audit_path=audit,
        model_pin="jev-1.13.0",
    )
    assert decision["verdict"] == "accept"
    line = audit.read_text()
    assert "supersecret" not in line
    assert "relevant?" not in line
    assert json.loads(line)["verdict"] == "accept"


def test_a_model_that_does_not_match_the_pin_is_refused(broker: ModuleType, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_REFLEX_BACKEND", "jev")
    monkeypatch.setenv("SPARKNET_REFLEX_ALLOW_EGRESS", "1")
    req = _request(broker, model="jev-1.14.0")
    with pytest.raises(broker.BrokerError, match="does not match"):
        broker.decide(
            req,
            call=lambda _r: {"type": "noul", "noul": 0.9},
            key="k",
            endpoint="https://example.invalid",
            timeout_s=1.0,
            budget=broker.BudgetLedger(),
            audit_path=tmp_path / "a.jsonl",
            model_pin="jev-1.13.0",
        )


def test_offline_abstains_without_calling_the_vendor(broker: ModuleType, tmp_path: Path) -> None:
    called = []

    def call(_r):
        called.append(1)
        return {"type": "noul", "noul": 0.9}

    decision = broker.decide(
        _request(broker),
        call=call,
        key=None,
        endpoint="https://example.invalid",
        timeout_s=1.0,
        budget=broker.BudgetLedger(),
        audit_path=tmp_path / "a.jsonl",
        offline=True,
    )
    assert decision["verdict"] == "abstain"
    assert decision["_reason"] == "offline"
    assert called == []


def test_budget_exhaustion_abstains(broker: ModuleType, tmp_path: Path) -> None:
    req = _request(broker, node_id="n1")
    budget = broker.BudgetLedger(per_node_per_day=1, global_per_day=10)
    budget.charge("n1")
    decision = broker.decide(
        req,
        call=lambda _r: {"type": "noul", "noul": 0.9},
        key="k",
        endpoint="https://example.invalid",
        timeout_s=1.0,
        budget=budget,
        audit_path=tmp_path / "a.jsonl",
    )
    assert decision["_reason"] == "budget-exhausted"


def test_missing_credential_abstains(broker: ModuleType, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_REFLEX_BACKEND", "jev")
    monkeypatch.setenv("SPARKNET_REFLEX_ALLOW_EGRESS", "1")
    decision = broker.decide(
        _request(broker),
        call=lambda _r: {"type": "noul", "noul": 0.9},
        key=None,
        endpoint="https://example.invalid",
        timeout_s=1.0,
        budget=broker.BudgetLedger(),
        audit_path=tmp_path / "a.jsonl",
    )
    assert decision["_reason"] == "no-credential"


def test_timeout_and_backend_error_abstain(broker: ModuleType, tmp_path: Path) -> None:
    def slow(_r):
        import time as _t

        _t.sleep(0.5)
        return {"type": "noul", "noul": 0.9}

    def boom(_r):
        raise RuntimeError("vendor down")

    common = {
        "key": "k",
        "endpoint": "https://example.invalid",
        "timeout_s": 0.05,
        "budget": broker.BudgetLedger(),
        "audit_path": tmp_path / "a.jsonl",
    }
    assert broker.decide(_request(broker), call=slow, **common)["_reason"] == "timeout"
    assert broker.decide(_request(broker), call=boom, **common)["_reason"] == "backend-error"


def test_check_posture_does_not_print_the_key(broker: ModuleType, capsys, tmp_path: Path) -> None:
    key = tmp_path / "key"
    key.write_text("supersecret")
    key.chmod(0o600)
    rc = broker.main(["--check", "--key-file", str(key), "--bind", "127.0.0.1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "supersecret" not in out
    assert '"credential": "present"' in out


def test_healthz_says_nothing_and_decide_serves(broker: ModuleType, tmp_path: Path) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), broker._Handler)
    server.key = None
    server.endpoint = "https://example.invalid"
    server.timeout_s = 1.0
    server.budget = broker.BudgetLedger()
    server.audit_path = tmp_path / "a.jsonl"
    server.model_pin = "jev-1.13.0"
    server.offline = True
    server.call = None
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlrequest.urlopen(base + "/healthz", timeout=2) as response:
            assert response.status == 200
            assert json.loads(response.read()) == {"ok": True}

        body = json.dumps(_request(broker)).encode()
        req = urlrequest.Request(
            base + "/v1/reflex/decide",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=2) as response:
            decision = json.loads(response.read())
        assert decision["verdict"] == "abstain"
        assert decision["_reason"] == "offline"

        with pytest.raises(urlerror.HTTPError) as exc:
            urlrequest.urlopen(base + "/nope", timeout=2)
        assert exc.value.code == 404
    finally:
        server.shutdown()
        server.server_close()


def test_local_mode_needs_no_credential(broker: ModuleType, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_REFLEX_BACKEND", "local")
    monkeypatch.setenv("SPARKNET_REFLEX_ALLOW_EGRESS", "0")
    decision = broker.decide(
        _request(broker, model="local"),
        call=lambda _r: {"type": "noul", "noul": 0.9},
        key=None,
        endpoint="https://example.invalid",
        timeout_s=1.0,
        budget=broker.BudgetLedger(),
        audit_path=tmp_path / "a.jsonl",
    )
    assert decision["verdict"] == "accept"
    assert decision["backend"] == "local-rerank"


def test_egress_without_credential_still_abstains(broker: ModuleType, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_REFLEX_BACKEND", "jev")
    monkeypatch.setenv("SPARKNET_REFLEX_ALLOW_EGRESS", "1")
    decision = broker.decide(
        _request(broker),
        call=lambda _r: {"type": "noul", "noul": 0.9},
        key=None,
        endpoint="https://example.invalid",
        timeout_s=1.0,
        budget=broker.BudgetLedger(),
        audit_path=tmp_path / "a.jsonl",
    )
    assert decision["verdict"] == "abstain"
    assert decision["_reason"] == "no-credential"


def _relevance(broker: ModuleType, state: object, model: str = "local") -> dict:
    return broker.reflex.make_request(
        "rag.relevance",
        state,
        {"relevant": {"type": "noul", "instructions": "relevant?"}},
        model,
        "policy-1",
        "master",
        "req-1",
    )


def _decide(broker: ModuleType, request: dict, tmp_path: Path) -> dict:
    return broker.decide(
        request,
        key=None,
        endpoint="https://example.invalid",
        timeout_s=1.0,
        budget=broker.BudgetLedger(),
        audit_path=tmp_path / "a.jsonl",
    )


def test_local_rerank_accepts_coverage_and_abstains_on_silence(broker: ModuleType, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_REFLEX_BACKEND", "local")
    monkeypatch.setenv("SPARKNET_REFLEX_ALLOW_EGRESS", "0")

    covering = _decide(
        broker, _relevance(broker, {"query": "guard nonce", "chunk": "the guard envelope nonce expired"}), tmp_path
    )
    assert covering["verdict"] == "accept"
    assert covering["backend"] == "local-rerank"

    silent = _decide(broker, _relevance(broker, {"query": "guard nonce", "chunk": "a recipe for soup"}), tmp_path)
    assert silent["verdict"] == "abstain"
    assert silent["_reason"] == "low-signal", "no coverage is no signal, never a confident reject"

    malformed = _decide(broker, _relevance(broker, "alpha"), tmp_path)
    assert malformed["verdict"] == "abstain"
    assert malformed["_reason"] == "low-signal"


def test_a_local_backend_failure_abstains_and_never_rejects(broker: ModuleType, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_REFLEX_BACKEND", "local-llm")
    monkeypatch.setenv("SPARKNET_REFLEX_ALLOW_EGRESS", "0")
    monkeypatch.delenv("SPARKNET_REFLEX_LOCAL_MODEL", raising=False)
    monkeypatch.delenv("SPARKNET_LOCAL_MODEL", raising=False)

    decision = _decide(broker, _request(broker, model="local"), tmp_path)
    assert decision["verdict"] == "abstain"
    assert decision["_reason"] == "backend-error"


def test_an_off_backend_abstains_without_calling_anything(broker: ModuleType, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SPARKNET_REFLEX_BACKEND", "off")
    monkeypatch.setattr(broker, "_local_backend", lambda _r: pytest.fail("an off backend must not be consulted"))
    decision = _decide(broker, _relevance(broker, {"query": "guard", "chunk": "guard"}), tmp_path)
    assert decision["verdict"] == "abstain"
    assert decision["_reason"] == "offline"


def test_main_accepts_a_local_model_in_local_mode(broker: ModuleType, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SPARKNET_REFLEX_BACKEND", "local")
    monkeypatch.setenv("SPARKNET_REFLEX_ALLOW_EGRESS", "0")
    monkeypatch.setenv("SPARKNET_REFLEX_MODEL", "local")
    assert broker.main(["--check"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["backend"] == "local"
    assert payload["model"] == "local"
    assert payload["credential"] == "absent"


def test_main_still_pins_an_exact_jev_tag_for_egress(broker: ModuleType, monkeypatch, capsys) -> None:
    monkeypatch.setenv("SPARKNET_REFLEX_BACKEND", "jev")
    monkeypatch.setenv("SPARKNET_REFLEX_ALLOW_EGRESS", "1")
    monkeypatch.setenv("SPARKNET_REFLEX_MODEL", "local")
    assert broker.main(["--check"]) == 2
    assert "jev-*" in capsys.readouterr().err
