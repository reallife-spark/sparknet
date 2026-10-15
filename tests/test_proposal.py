"""The proposal workflow, end to end: propose, review, decide, and refuse.

`shared/sparknet-proposal.py` is the implementation half of
`contracts/proposal-schema.json`. These tests build a throwaway vault, drive the
real API and CLI, and assert the lifecycle (draft → submitted → reviewed →
decided) plus every refusal the contract names.

Everything is offline and reads no key material from the repository: the vault
is generated per test, so a passing run proves nothing about any real node's keys
and cannot leak one.
"""

from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PROVENANCE_PATH = REPO_ROOT / "shared" / "sparknet-provenance.py"
PROPOSAL_PATH = REPO_ROOT / "shared" / "sparknet-proposal.py"
CONTRACT = json.loads((REPO_ROOT / "contracts" / "proposal-schema.json").read_text())
TRACKING = json.loads((REPO_ROOT / "contracts" / "tracking-schema.json").read_text())

OWNER_ID = "U-10421"


@pytest.fixture(scope="module")
def provenance() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sparknet_provenance_proposal_test", PROVENANCE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


@pytest.fixture(scope="module")
def proposal() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sparknet_proposal_under_test", PROPOSAL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


# The proposal id embeds the date (`PRO-<YYYY-MM-DD>-NNN`), so the suite would
# otherwise assert a different id every day. The module takes an injectable
# clock precisely for this; freeze the one the module actually calls.
FIXED_NOW = dt.datetime(2026, 10, 13, 12, 0, 0, tzinfo=dt.timezone.utc)


@pytest.fixture(autouse=True)
def frozen_clock(proposal: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    provenance = proposal._load_provenance()
    monkeypatch.setattr(provenance, "_now", lambda: FIXED_NOW)


def user_record_template() -> str:
    return (
        "---\n"
        "type: user-record\n"
        "schema: sparknet-user/1\n"
        "status: unfilled\n"
        'owner_id: ""\n'
        'owner_node: ""\n'
        "role: owner\n"
        "immutable: true\n"
        "authorised_senders: []\n"
        "key:\n"
        "  alg: ed25519\n"
        '  public_key_b64: ""\n'
        '  fingerprint: ""\n'
        '  key_ref: ""\n'
        '  created: ""\n'
        "---\n"
    )


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture()
def vault(tmp_path: Path, provenance: ModuleType, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A filled vault with a real user key at 0600, a node key, and a node identity."""
    root = tmp_path / "vault"
    (root / "00_System").mkdir(parents=True)
    (root / "01_Inbox").mkdir()
    (root / "blockchain").mkdir()
    (root / "manifests").mkdir()
    write(root / "00_System" / "user.md", user_record_template())
    write(root / "manifests" / "node-identity.json", json.dumps({"node_id": "sparknet-node-0009"}))
    state = tmp_path / "state"
    monkeypatch.setenv("SPARKNET_STATE_DIR", str(state))
    provenance.user_init(root, owner_id=OWNER_ID)

    authz = provenance._load_authz()
    private_b64, _ = authz.generate_keypair()
    node_key = state / "keys" / "ed25519-node.key.b64"
    node_key.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    node_key.write_text(private_b64 + "\n")
    node_key.chmod(0o600)
    return root


CONVERSATION = [
    {"id": "conv-1", "turn": 1, "agent": "plan", "model": "m-plan", "at": "2026-10-13T00:00:00Z"},
    {"id": "conv-1", "turn": 2, "agent": "build", "model": "m-build", "at": "2026-10-13T00:01:00Z"},
]


def drive_to_decided(proposal: ModuleType, vault: Path) -> dict:
    """The canonical round trip; returns the ids and the three records."""
    draft = proposal.build_proposal(
        vault,
        title="Adopt the proposal contract",
        summary="Introduce proposal/review/decision records.",
        agent="plan",
        model="m-plan",
        conversation=CONVERSATION,
    )
    submitted = proposal.submit_proposal(vault, draft)
    review = proposal.build_review(
        vault,
        proposal_id=submitted["proposal_id"],
        verdict="approve",
        reason="reads well",
        agent="vault",
        model="m-vault",
    )
    reviewed = proposal.review_proposal(vault, review)
    decision = proposal.build_decision(
        vault,
        proposal_id=submitted["proposal_id"],
        decision="approved",
        reason="ship it",
        agent="plan",
        model="m-plan",
    )
    decided = proposal.decide_proposal(vault, decision)
    return {"submitted": submitted, "reviewed": reviewed, "decided": decided}


def chain(proposal: ModuleType, vault: Path, proposal_id: str) -> list[dict]:
    return proposal.proposal_records(vault, proposal_id)


# --- the round trip -----------------------------------------------------------


def test_a_draft_is_local_and_unsigned(proposal: ModuleType, provenance: ModuleType, vault: Path):
    draft = proposal.build_proposal(
        vault, title="T", summary="S", agent="plan", model="m-plan", conversation=CONVERSATION
    )
    assert draft["event"] == "proposal"
    assert draft["stage"] == "draft"
    assert "proposal_id" not in draft and "signatures" not in draft
    assert draft["owner_id"] == OWNER_ID
    assert draft["owner_node"] == "sparknet-node-0009"
    # The conversation is committed by the Step 35 root, computed the one way.
    assert draft["conversation_root"] == provenance.build_conversation_root(CONVERSATION)


def test_the_round_trip_submits_reviews_and_decides(proposal: ModuleType, provenance: ModuleType, vault: Path):
    result = drive_to_decided(proposal, vault)
    pid = result["submitted"]["proposal_id"]
    assert pid == "PRO-2026-10-13-001"
    assert proposal.proposal_state(vault, pid) == "decided"

    records = chain(proposal, vault, pid)
    assert [r["event"] for r in records] == ["proposal", "review", "decision"]
    assert records[1]["verdict"] == "approve" and records[1]["agent"] == "vault"
    assert records[2]["decision"] == "approved" and records[2]["owner_id"] == OWNER_ID
    assert proposal.verify_proposal_chain(records) == []
    assert proposal.verify_vault_proposals(vault) == []

    # The proposal blocks are ordinary v2 ledger blocks: the chain still verifies.
    ok, detail = provenance.verify_chain(provenance.load_ledger(vault / "blockchain" / "ledger.json"))
    assert ok, detail


def test_state_is_derived_from_the_chain(proposal: ModuleType, vault: Path):
    assert proposal.proposal_state(vault, "PRO-2026-10-13-001") == "absent"
    draft = proposal.build_proposal(vault, title="T", summary="S", agent="plan", model="m")
    submitted = proposal.submit_proposal(vault, draft)
    assert proposal.proposal_state(vault, submitted["proposal_id"]) == "submitted"
    review = proposal.build_review(
        vault,
        proposal_id=submitted["proposal_id"],
        verdict="approve",
        reason="ok",
        agent="vault",
        model="m",
    )
    proposal.review_proposal(vault, review)
    assert proposal.proposal_state(vault, submitted["proposal_id"]) == "reviewed"


# --- fail-closed transitions --------------------------------------------------


def test_submit_refuses_a_non_draft(proposal: ModuleType, vault: Path):
    draft = proposal.build_proposal(vault, title="T", summary="S", agent="a", model="m")
    draft["stage"] = "submitted"
    with pytest.raises(proposal.ProposalError, match="draft"):
        proposal.submit_proposal(vault, draft)


def test_a_review_without_a_proposal_is_refused(proposal: ModuleType, vault: Path):
    review = proposal.build_review(
        vault,
        proposal_id="PRO-2026-10-13-999",
        verdict="approve",
        reason="ok",
        agent="vault",
        model="m",
    )
    with pytest.raises(proposal.ProposalError, match="no proposal"):
        proposal.review_proposal(vault, review)


def test_a_decision_without_a_review_is_refused(proposal: ModuleType, vault: Path):
    submitted = proposal.submit_proposal(
        vault, proposal.build_proposal(vault, title="T", summary="S", agent="a", model="m")
    )
    decision = proposal.build_decision(
        vault,
        proposal_id=submitted["proposal_id"],
        decision="approved",
        reason="ship",
        agent="a",
        model="m",
    )
    with pytest.raises(proposal.ProposalError, match="no review"):
        proposal.decide_proposal(vault, decision)


def test_a_second_decision_is_refused(proposal: ModuleType, vault: Path):
    result = drive_to_decided(proposal, vault)
    again = proposal.build_decision(
        vault,
        proposal_id=result["submitted"]["proposal_id"],
        decision="denied",
        reason="changed my mind",
        agent="a",
        model="m",
    )
    with pytest.raises(proposal.ProposalError, match="already decided"):
        proposal.decide_proposal(vault, again)


def test_a_review_after_the_decision_is_refused(proposal: ModuleType, vault: Path):
    result = drive_to_decided(proposal, vault)
    late = proposal.build_review(
        vault,
        proposal_id=result["submitted"]["proposal_id"],
        verdict="reject",
        reason="too late",
        agent="vault",
        model="m",
    )
    with pytest.raises(proposal.ProposalError, match="already decided"):
        proposal.review_proposal(vault, late)


def test_the_closed_vocabularies_are_enforced(proposal: ModuleType, vault: Path):
    with pytest.raises(proposal.ProposalError, match="verdict"):
        proposal.build_review(
            vault,
            proposal_id="PRO-2026-10-13-001",
            verdict="maybe",
            reason="?",
            agent="a",
            model="m",
        )
    with pytest.raises(proposal.ProposalError, match="decision"):
        proposal.build_decision(
            vault,
            proposal_id="PRO-2026-10-13-001",
            decision="maybe",
            reason="?",
            agent="a",
            model="m",
        )


# --- verify_proposal_chain refusals -------------------------------------------


def _decided_chain(proposal: ModuleType, vault: Path) -> list[dict]:
    result = drive_to_decided(proposal, vault)
    return chain(proposal, vault, result["submitted"]["proposal_id"])


def test_verify_refuses_a_forged_user_signature(proposal: ModuleType, vault: Path):
    records = copy.deepcopy(_decided_chain(proposal, vault))
    signature = records[0]["signatures"]["user"]
    records[0]["signatures"]["user"] = ("A" if signature[0] != "A" else "B") + signature[1:]
    problems = proposal.verify_proposal_chain(records)
    assert any("user signature does not verify" in p for p in problems)


def test_verify_refuses_a_forged_node_signature(proposal: ModuleType, vault: Path):
    records = copy.deepcopy(_decided_chain(proposal, vault))
    records[1]["signatures"]["node"] = ""
    problems = proposal.verify_proposal_chain(records)
    assert any("node signature does not verify" in p for p in problems)


def test_verify_refuses_a_swapped_key(proposal: ModuleType, provenance: ModuleType, vault: Path):
    records = copy.deepcopy(_decided_chain(proposal, vault))
    authz = provenance._load_authz()
    _, fresh_public = authz.generate_keypair()

    # Key swapped, fingerprint left alone: the mismatch is visible.
    records[0]["user_public_key_b64"] = fresh_public
    problems = proposal.verify_proposal_chain(records)
    assert any("fingerprint does not match" in p for p in problems)

    # Key and fingerprint swapped together: the fingerprint check passes but the
    # original signature no longer verifies under the new key.
    records = copy.deepcopy(_decided_chain(proposal, vault))
    records[0]["user_public_key_b64"] = fresh_public
    records[0]["user_key_fingerprint"] = provenance.fingerprint_label_of_public_b64(fresh_public)
    problems = proposal.verify_proposal_chain(records)
    assert any("user signature does not verify" in p for p in problems)


def test_verify_refuses_a_tampered_conversation(proposal: ModuleType, vault: Path):
    records = copy.deepcopy(_decided_chain(proposal, vault))
    records[0]["conversation"][1]["agent"] = "someone-else"
    problems = proposal.verify_proposal_chain(records)
    assert any("conversation_root does not match" in p for p in problems)


def test_verify_refuses_a_reordered_chain(proposal: ModuleType, vault: Path):
    records = _decided_chain(proposal, vault)
    reordered = [records[2], records[0], records[1]]  # decision first
    problems = proposal.verify_proposal_chain(reordered)
    assert any("not the first record" in p for p in problems)
    assert any("review follows the decision" in p for p in problems)
    assert any("decision precedes every review" in p for p in problems)


def test_verify_refuses_a_decision_before_any_review(proposal: ModuleType, vault: Path):
    records = _decided_chain(proposal, vault)
    problems = proposal.verify_proposal_chain([records[0], records[2]])
    assert any("decision precedes every review" in p for p in problems)


def test_verify_refuses_a_missing_proposal(proposal: ModuleType, vault: Path):
    records = _decided_chain(proposal, vault)
    problems = proposal.verify_proposal_chain(records[1:])
    assert "no proposal record" in problems


def test_verify_refuses_a_second_proposal_and_a_second_decision(proposal: ModuleType, vault: Path):
    records = _decided_chain(proposal, vault)
    problems = proposal.verify_proposal_chain([records[0], records[1], records[2], records[0]])
    assert "more than one proposal record" in problems

    problems = proposal.verify_proposal_chain([records[0], records[1], records[2], records[2]])
    assert "more than one decision record" in problems


def test_verify_refuses_a_review_that_names_a_different_proposal(proposal: ModuleType, vault: Path):
    records = copy.deepcopy(_decided_chain(proposal, vault))
    records[1]["proposal_id"] = "PRO-2026-10-13-404"
    problems = proposal.verify_proposal_chain(records)
    assert any("references proposal" in p for p in problems)


def test_verify_refuses_an_empty_chain(proposal: ModuleType):
    assert proposal.verify_proposal_chain([]) == ["no proposal records"]


# --- the chain is committed by the block signature ----------------------------


def test_editing_a_proposal_block_breaks_the_ledger_chain(proposal: ModuleType, provenance: ModuleType, vault: Path):
    result = drive_to_decided(proposal, vault)
    path = vault / "blockchain" / "ledger.json"
    ledger = provenance.load_ledger(path)
    ledger["blocks"][0]["data"]["title"] = "something else"
    ok, detail = provenance.verify_chain(ledger)
    assert not ok and "header signature does not verify" in detail
    assert proposal.proposal_state(vault, result["submitted"]["proposal_id"]) == "decided"


# --- the contract is the source of truth --------------------------------------


def test_the_contract_names_the_three_records(proposal: ModuleType):
    assert tuple(CONTRACT["records"].keys()) == proposal.PROPOSAL_EVENTS
    assert tuple(CONTRACT["vocabularies"]["verdicts"]) == proposal.REVIEW_VERDICTS
    assert tuple(CONTRACT["vocabularies"]["decisions"]) == proposal.DECISIONS
    assert tuple(CONTRACT["lifecycle"]["states"]) == proposal.LIFECYCLE_STATES


def test_the_peer_vocabulary_gains_the_three_events_and_master_does_not():
    peer = set(TRACKING["approval"]["event_vocabulary"]["peer"])
    master = set(TRACKING["approval"]["event_vocabulary"]["master"])
    assert {"proposal", "review", "decision"} <= peer
    assert not ({"proposal", "review", "decision"} & master)
    assert not (peer & master)


# --- the CLI ------------------------------------------------------------------


def test_the_cli_propose_submit_and_verify_round_trip(
    proposal: ModuleType, vault: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    draft_path = tmp_path / "draft.json"
    assert (
        proposal.main(
            [
                "--vault",
                str(vault),
                "propose",
                "--title",
                "CLI proposal",
                "--summary",
                "S",
                "--agent",
                "plan",
                "--model",
                "m",
                "--out",
                str(draft_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert proposal.main(["--vault", str(vault), "submit", str(draft_path)]) == 0
    submitted = json.loads(capsys.readouterr().out)
    pid = submitted["proposal_id"]

    assert (
        proposal.main(
            [
                "--vault",
                str(vault),
                "review",
                "--proposal-id",
                pid,
                "--verdict",
                "approve",
                "--reason",
                "ok",
                "--agent",
                "vault",
                "--model",
                "m",
            ]
        )
        == 0
    )
    capsys.readouterr()

    records = proposal.proposal_records(vault, pid)
    chain_path = tmp_path / "chain.json"
    chain_path.write_text(json.dumps(records))
    assert proposal.main(["verify", str(chain_path)]) == 0
    assert "proposal chain ok" in capsys.readouterr().out

    records[0]["title"] = "tampered"
    chain_path.write_text(json.dumps(records))
    assert proposal.main(["verify", str(chain_path)]) == 1
    assert "does not verify" in capsys.readouterr().out
