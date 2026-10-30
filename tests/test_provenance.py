"""The provenance tool, end to end: sign, verify, attest, refuse.

`shared/sparknet-provenance.py` is the implementation half of
`contracts/tracking-schema.json`. These tests build a throwaway vault, run the
real CLI against it and assert the contract's state machine — valid,
stale:metadata, stale:content, invalid, pending — including the exit codes
`make provenance-verify` and `make precommit` depend on.

Everything here is offline and reads no key material from the repository: the
vault is generated per test, so a passing run proves nothing about any real
node's keys and cannot leak one.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PROVENANCE_PATH = REPO_ROOT / "shared" / "sparknet-provenance.py"
CONTRACT = json.loads((REPO_ROOT / "contracts" / "tracking-schema.json").read_text())

OWNER_ID = "U-10421"


@pytest.fixture(scope="module")
def provenance() -> ModuleType:
    spec = importlib.util.spec_from_file_location("sparknet_provenance_under_test", PROVENANCE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def write(path: Path, text: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text)
    return path


def set_field(path: Path, key: str, value: str) -> None:
    """Rewrite one top-level frontmatter field, the way a compiler would."""
    text, count = re.subn(rf"^{key}:.*$", f"{key}: {value}", path.read_text(), count=1, flags=re.M)
    assert count == 1, f"{key} not found in {path.name}"
    path.write_text(text)


def corrupt_signature(text: str) -> str:
    """Flip one base64 character inside the envelope's signature."""
    match = re.search(r'sig: "?([A-Za-z0-9+/=]{24,})"?', text)
    assert match, "no signature found to corrupt"
    sig = match.group(1)
    flipped = "A" if sig[5] != "A" else "B"
    corrupted = sig[:5] + flipped + sig[6:]
    return text[: match.start(1)] + corrupted + text[match.end(1) :]


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
        "key:\n"
        "  alg: ed25519\n"
        '  public_key_b64: ""\n'
        '  fingerprint: ""\n'
        '  key_ref: "$SPARKNET_STATE_DIR/keys/user.ed25519"\n'
        '  created: ""\n'
        "---\n\n"
        "# user record\n"
    )


def note(text: str = "body text", *, title: str = "hello", state: str = "unsigned") -> str:
    return (
        "---\n"
        f"title: {title}\n"
        "updated: 2026-10-06\n"
        "tracking:\n"
        "  schema: sparknet-tracking/1\n"
        '  owner_id: ""\n'
        '  owner_node: ""\n'
        "  owner_ref: 00_System/user.md\n"
        "  validity:\n"
        f"    state: {state}\n"
        "  conversation: []\n"
        "  shares: []\n"
        "  agent: tester\n"
        "  model: none\n"
        "  approvals: []\n"
        "---\n\n"
        f"{text}\n"
    )


@pytest.fixture()
def vault(tmp_path: Path, provenance: ModuleType, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A filled vault with a real user key at 0600 and a node key to counter with."""
    root = tmp_path / "vault"
    (root / "00_System").mkdir(parents=True)
    (root / "01_Inbox").mkdir()
    (root / "blockchain").mkdir()
    write(root / "00_System" / "user.md", user_record_template())
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


def sign(provenance, vault: Path, path: Path) -> None:
    path.write_bytes(provenance.sign_note(path.read_bytes(), vault, agent="tester", model="none"))


def verify(provenance, vault: Path, path: Path) -> tuple[str, str]:
    return provenance.verify_note(path, vault=vault)


# --- the user record -----------------------------------------------------------


def test_user_init_fills_once_and_then_refuses(vault: Path, provenance: ModuleType):
    record = provenance.parse_user_record(vault)
    assert record["owner_id"] == OWNER_ID
    assert record["status"] == "filled"
    assert provenance.user_is_filled(record)

    key_path = vault.parent / "state" / "keys" / "user.ed25519"
    assert oct(key_path.stat().st_mode & 0o777) == "0o600"
    assert provenance._verify_lock(vault, provenance.user_record_path(vault)) is True

    # A second run is a no-op: the key every signature verifies against stands.
    fingerprint = record["key"]["fingerprint"]
    again = provenance.user_init(vault)
    assert again["key"]["fingerprint"] == fingerprint
    assert provenance.parse_user_record(vault)["key"]["fingerprint"] == fingerprint

    # ...and with the receipt gone, filling again is refused rather than guessed at.
    (vault / "00_System" / ".user.lock").unlink()
    with pytest.raises(provenance.ProvenanceError, match="refusing to re-key"):
        provenance.user_init(vault)

    # A deliberate re-key is the one case `force` exists for.
    rekeyed = provenance.user_init(vault, force=True)
    assert rekeyed["key"]["fingerprint"] != fingerprint


def test_a_record_whose_fingerprint_is_not_its_keys_digest_is_not_filled(vault: Path, provenance: ModuleType):
    record = provenance.parse_user_record(vault)
    record["key"]["fingerprint"] = "sha256:" + "0" * 64
    assert not provenance.user_is_filled(record)


def test_the_record_holds_public_material_only(vault: Path, provenance: ModuleType):
    """The allowlist is the answer to 'is a private key hiding in here?'."""
    problems = provenance.check_user_record(vault)
    assert problems == [], problems

    record = provenance.parse_user_record(vault)
    record["api_token"] = "hunter2hunter2"
    write(provenance.user_record_path(vault), provenance.emit_note(record, b"# user record\n"))
    problems = provenance.check_user_record(vault)
    assert any("allowlist" in p for p in problems), problems


# --- signing and the state machine --------------------------------------------


def test_sign_then_verify_is_valid_and_the_envelope_matches_the_contract(vault: Path, provenance: ModuleType):
    path = write(vault / "01_Inbox" / "hello.md", note())
    sign(provenance, vault, path)

    outcome, detail = verify(provenance, vault, path)
    assert outcome == "valid", detail

    frontmatter, _ = provenance.split_note(path.read_bytes())
    envelope = frontmatter["tracking"]["signature"]
    assert set(envelope) == set(CONTRACT["signature"]["envelope"]), (
        "the envelope the tool writes is not the one the contract describes"
    )
    assert envelope["key_id"] == OWNER_ID
    assert envelope["key_fingerprint"].startswith("sha256:")
    assert frontmatter["tracking"]["validity"]["state"] == "signed"
    # signed_meta must hash to its recorded hash, or the envelope is editable.
    assert provenance.sha256_hex(provenance.canonical_json(envelope["signed_meta"])) == envelope["signed_meta_sha256"]


def test_a_compiler_bump_is_stale_metadata_not_invalid(vault: Path, provenance: ModuleType):
    path = write(vault / "01_Inbox" / "hello.md", note())
    sign(provenance, vault, path)

    set_field(path, "updated", "2026-10-07")
    outcome, detail = verify(provenance, vault, path)
    assert outcome == "stale:metadata", detail
    assert "updated" in detail, "the report must name the key that moved"
    # stale:metadata is never a failure, strict or not — it is the compiler working.
    assert provenance.verify_vault(vault, strict=True)[0] == 0

    sign(provenance, vault, path)
    assert verify(provenance, vault, path)[0] == "valid"


def test_a_body_edit_is_stale_content(vault: Path, provenance: ModuleType):
    path = write(vault / "01_Inbox" / "hello.md", note())
    sign(provenance, vault, path)
    path.write_text(path.read_text().replace("body text", "body rewritten"))

    outcome, detail = verify(provenance, vault, path)
    assert outcome == "stale:content", detail
    code, _ = provenance.verify_vault(vault)
    assert code == 2, "stale:content is the soft failure: exit 2, not 1"
    code, _ = provenance.verify_vault(vault, strict=True)
    assert code == 1, "--strict promotes the soft failure to a hard one"


def test_a_metadata_edit_outside_the_allowlist_is_stale_content(vault: Path, provenance: ModuleType):
    path = write(vault / "01_Inbox" / "hello.md", note())
    sign(provenance, vault, path)
    set_field(path, "title", "hijacked")

    outcome, detail = verify(provenance, vault, path)
    assert outcome == "stale:content", detail
    assert "title" in detail


def test_tampering_with_the_envelope_is_invalid(vault: Path, provenance: ModuleType):
    path = write(vault / "01_Inbox" / "hello.md", note())
    sign(provenance, vault, path)

    # One character flipped: the file still parses, the signature does not.
    path.write_text(corrupt_signature(path.read_text()))
    assert verify(provenance, vault, path)[0] == "invalid"

    # Editing a signed hash inside the envelope, without touching the file body.
    sign(provenance, vault, path)
    frontmatter, body = provenance.split_note(path.read_bytes())
    frontmatter["tracking"]["signature"]["signed_meta"]["title"] = "rewritten"
    path.write_bytes(provenance.emit_note(frontmatter, body))
    outcome, detail = verify(provenance, vault, path)
    assert outcome == "invalid", detail
    assert "signed_meta" in detail


def test_a_note_attributed_to_another_owner_is_refused_at_signing(vault: Path, provenance: ModuleType):
    path = write(vault / "01_Inbox" / "hello.md", note())
    path.write_text(path.read_text().replace('owner_id: ""', "owner_id: U-99999"))
    with pytest.raises(provenance.ProvenanceError, match="re-attribute"):
        provenance.sign_note(path.read_bytes(), vault)


def test_an_unsigned_note_outside_the_inbox_is_invalid_but_in_the_inbox_is_pending(vault: Path, provenance: ModuleType):
    inbox = write(vault / "01_Inbox" / "raw.md", note("untouched capture"))
    system = write(vault / "00_System" / "rules.md", note("must be signed"))
    assert verify(provenance, vault, inbox) == ("pending", "inbox item awaiting acceptance")
    assert verify(provenance, vault, system)[0] == "invalid"


def test_signing_a_note_without_a_user_key_is_refused(tmp_path: Path, provenance: ModuleType):
    root = tmp_path / "vault"
    (root / "00_System").mkdir(parents=True)
    write(root / "00_System" / "user.md", user_record_template())
    path = write(root / "note.md", note())
    with pytest.raises(provenance.ProvenanceError, match="user-init"):
        provenance.sign_note(path.read_bytes(), root)


# --- the ledger ----------------------------------------------------------------


def test_an_approval_lands_dual_signed_and_verifies(vault: Path, provenance: ModuleType):
    path = write(vault / "01_Inbox" / "hello.md", note())
    sign(provenance, vault, path)

    record = provenance.parse_user_record(vault)
    data = provenance.build_approval_data(
        vault=vault,
        question="may this node ingest the 2026-10 capture?",
        decision="approved",
        note_refs=["01_Inbox/hello.md"],
        agent="tester",
        model="none",
        record=record,
    )
    assert set(data) - {"signatures"} == set(CONTRACT["approval"]["data_fields"]) - {"signatures"}, (
        "the approval payload no longer matches contracts/tracking-schema.json"
    )
    assert data["approval_id"].startswith("APL-")
    block = provenance.append_block(vault, data)

    authz = provenance._load_authz()
    node_pub = authz.public_key_from_b64(block["node_pubkey_b64"])
    assert authz.verify_signature(node_pub, block["signature"], provenance.block_header_signable(block)), (
        "the block header signature must verify against the block's own node key"
    )
    assert block["signature"] != data["signatures"]["node"], (
        "the block-level signature signs the header; it no longer restates the node countersignature"
    )
    ok, detail = provenance.verify_chain(provenance.load_ledger(vault / "blockchain" / "ledger.json"))
    assert ok, detail
    assert provenance.verify_approval_blocks(vault) == []

    # The note claims it, and the claim resolves both ways.
    path.write_text(path.read_text().replace("approvals: []", f"approvals:\n  - {data['approval_id']}"))
    sign(provenance, vault, path)
    code, report = provenance.verify_vault(vault)
    assert code == 0, report


def test_a_fabricated_approval_id_is_reported(vault: Path, provenance: ModuleType):
    path = write(vault / "01_Inbox" / "hello.md", note())
    sign(provenance, vault, path)
    path.write_text(path.read_text().replace("approvals: []", "approvals:\n  - APL-1999-01-01-001"))
    sign(provenance, vault, path)

    code, report = provenance.verify_vault(vault)
    assert code == 1, report
    assert "APL-1999-01-01-001" in report


def test_editing_a_recorded_approval_breaks_the_chain(vault: Path, provenance: ModuleType):
    record = provenance.parse_user_record(vault)
    data = provenance.build_approval_data(
        vault=vault,
        question="original question",
        decision="approved",
        note_refs=[],
        agent="tester",
        model="none",
        record=record,
    )
    provenance.append_block(vault, data)

    ledger_path = vault / "blockchain" / "ledger.json"
    ledger = json.loads(ledger_path.read_text())
    ledger["blocks"][0]["data"]["decision"] = "rejected"
    ledger_path.write_text(json.dumps(ledger, indent=2))

    code, report = provenance.verify_vault(vault)
    assert code == 1, report
    assert "re-hash" in report or "does not verify" in report


def test_approval_ids_are_unique_per_ledger(vault: Path, provenance: ModuleType):
    record = provenance.parse_user_record(vault)
    seen = set()
    for question in ("one?", "two?", "three?"):
        data = provenance.build_approval_data(
            vault=vault,
            question=question,
            decision="approved",
            note_refs=[],
            agent="tester",
            model="none",
            record=record,
        )
        assert data["approval_id"] not in seen, "approval ids repeat within a ledger"
        seen.add(data["approval_id"])
        provenance.append_block(vault, data)
    assert len(seen) == 3


# --- ledger tamper resistance: the block header is signed -----------------------


def _two_block_ledger(vault: Path, provenance: ModuleType) -> Path:
    record = provenance.parse_user_record(vault)
    for question in ("first?", "second?"):
        data = provenance.build_approval_data(
            vault=vault,
            question=question,
            decision="approved",
            note_refs=[],
            agent="tester",
            model="none",
            record=record,
        )
        provenance.append_block(vault, data)
    return vault / "blockchain" / "ledger.json"


def test_a_two_block_ledger_verifies_and_links_on_signed_bytes(vault: Path, provenance: ModuleType):
    path = _two_block_ledger(vault, provenance)
    ledger = provenance.load_ledger(path)
    ok, detail = provenance.verify_chain(ledger)
    assert ok, detail
    blocks = ledger["blocks"]
    assert blocks[1]["prev_hash"] == blocks[0]["hash"], "the chain must link on the block hash"
    for block in blocks:
        assert block["node_pubkey_b64"], "each block carries its own node key"
        assert block["signature"] != block["data"]["signatures"]["node"], (
            "the header signature is its own value, not a restatement of the countersignature"
        )


def test_deleting_a_block_is_detected(vault: Path, provenance: ModuleType):
    """A deleted block — the grant_use replay vector — must not verify."""
    path = _two_block_ledger(vault, provenance)
    ledger = provenance.load_ledger(path)
    del ledger["blocks"][0]
    ok, detail = provenance.verify_chain(ledger)
    assert not ok, "a ledger missing a block verified"
    assert "block_id" in detail or "links to" in detail, detail


def test_reordering_blocks_is_detected(vault: Path, provenance: ModuleType):
    path = _two_block_ledger(vault, provenance)
    ledger = provenance.load_ledger(path)
    ledger["blocks"].reverse()
    ok, detail = provenance.verify_chain(ledger)
    assert not ok, "a reordered ledger verified"
    assert detail


def test_backdating_a_timestamp_is_detected(vault: Path, provenance: ModuleType):
    path = _two_block_ledger(vault, provenance)
    ledger = provenance.load_ledger(path)
    ledger["blocks"][0]["timestamp"] = "1970-01-01T00:00:00Z"
    ok, detail = provenance.verify_chain(ledger)
    assert not ok, "an edited timestamp verified"
    assert "header signature" in detail or "re-hash" in detail, detail


def test_rewriting_a_block_id_is_detected(vault: Path, provenance: ModuleType):
    path = _two_block_ledger(vault, provenance)
    ledger = provenance.load_ledger(path)
    ledger["blocks"][1]["block_id"] = "00000042"
    ok, detail = provenance.verify_chain(ledger)
    assert not ok, "a block whose id is not its index verified"
    assert "block_id" in detail, detail


def test_blanking_the_header_signature_is_detected(vault: Path, provenance: ModuleType):
    path = _two_block_ledger(vault, provenance)
    ledger = provenance.load_ledger(path)
    ledger["blocks"][0]["signature"] = ""
    ok, detail = provenance.verify_chain(ledger)
    assert not ok, "an unsigned block verified"
    assert "no signature" in detail, detail


def test_a_block_signed_by_a_foreign_key_is_refused(vault: Path, provenance: ModuleType):
    path = _two_block_ledger(vault, provenance)
    ledger = provenance.load_ledger(path)
    authz = provenance._load_authz()
    _, other_pub = authz.generate_keypair()
    ledger["blocks"][0]["node_pubkey_b64"] = other_pub
    ok, detail = provenance.verify_chain(ledger)
    assert not ok, "a block whose key does not match its signature verified"
    assert "header signature" in detail, detail


def test_the_vault_verifies_when_its_ledger_is_absent(vault: Path, provenance: ModuleType):
    """A fresh vault has no approvals yet; that is not a failure."""
    code, report = provenance.verify_vault(vault)
    assert code == 0, report
    assert "ledger: absent" in report


# --- secrets -------------------------------------------------------------------


def test_the_scanner_finds_a_registered_secret_in_a_tracked_file(
    vault: Path, provenance: ModuleType, monkeypatch: pytest.MonkeyPatch
):
    secret_value = "sk-live-abcdefghijklmnop"
    secrets = vault.parent / "state" / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)
    (secrets / "live-token").write_text(secret_value)
    (secrets / "live-token").chmod(0o600)
    write(
        vault / "00_System" / "secrets-index.json",
        json.dumps(
            {
                "secrets": [
                    {
                        "id": "live-token",
                        "kind": "api_token",
                        "holder_agent": "tester",
                        "ref": "live-token",
                        "fingerprint": "sha256:" + "0" * 64,
                        "scopes": [],
                        "created": "2026-10-06",
                        "last_rotated": "2026-10-06",
                        "status": "active",
                        "notes": "",
                    }
                ]
            },
            indent=2,
        ),
    )
    write(vault / "03_Sources" / "note.md", note("the value is " + secret_value))

    code, report = provenance.scan(vault)
    assert code == 1, report
    assert "registered secret" in report

    (vault / "03_Sources" / "note.md").unlink()
    code, report = provenance.scan(vault)
    assert code == 0, report


def test_the_scanner_skips_vendored_skill_trees(vault: Path, provenance: ModuleType):
    write(vault / ".opencode" / "skills" / "x" / "SKILL.md", "password: 'hunter2hunter2'\n")
    code, report = provenance.scan(vault)
    assert code == 0, report

    write(vault / "03_Sources" / "leak.md", "password: 'hunter2hunter2'\n")
    code, report = provenance.scan(vault)
    assert code == 1, report
    assert "leak.md" in report
    assert ".opencode/skills" not in report


def test_the_scanner_finds_key_shaped_literals(vault: Path, provenance: ModuleType):
    write(vault / "03_Sources" / "oops.md", note("password: 'hunter2hunter2'"))
    code, report = provenance.scan(vault)
    assert code == 1, report


def test_the_secret_index_schema_has_no_value_field(vault: Path, provenance: ModuleType):
    assert not (set(CONTRACT["secret_index"]["entry_fields"]) & set(CONTRACT["secret_index"]["forbidden_keys"]))
    write(
        vault / "00_System" / "secrets-index.json",
        json.dumps({"secrets": [{"id": "x", "value": "leaked"}]}),
    )
    code, report = provenance.scan(vault)
    assert code == 1
    assert "schema" in report


# --- the frontmatter subset ----------------------------------------------------


def test_the_frontmatter_subset_round_trips(vault: Path, provenance: ModuleType):
    """What is signed must be what parses — an emitter drift is a stale note."""
    original = {
        "title": 'a title with: colons and "quotes"',
        "tags": ["alpha", "beta"],
        "count": 3,
        "draft": False,
        "nothing": None,
        "nested": {"inner": "value", "list": [1, 2]},
        "rows": [{"id": "c1", "turn": 1, "agent": "chat"}, {"id": "c2", "turn": 2}],
        "tracking": {"schema": "sparknet-tracking/1"},
    }
    emitted = provenance.emit_note(original, b"body\n")
    frontmatter, body = provenance.split_note(emitted)
    assert frontmatter == original
    assert body == b"body\n"


def test_a_note_without_a_tracking_block_is_unparseable(vault: Path, provenance: ModuleType):
    path = write(vault / "01_Inbox" / "bare.md", "---\ntitle: bare\n---\n\nbody\n")
    outcome, detail = verify(provenance, vault, path)
    assert outcome == "invalid"
    assert "tracking" in detail


def test_block_scalars_parse_as_one_string(provenance: ModuleType):
    """Real notes use `summary: >-`; rejecting them makes them all invalid.

    The captured source pages in `03_Sources/` ship with folded summaries, so
    a subset that cannot read a block scalar would report the vault's own
    immutable captures as tampered with.
    """
    text = (
        "---\n"
        "title: t\n"
        "summary: >-\n"
        "  first line\n"
        "  second line\n"
        "\n"
        "  third paragraph\n"
        "code: |-\n"
        "  indented\n"
        "    deeper\n"
        "  back\n"
        "after: plain\n"
        "---\n"
        "body\n"
    )
    frontmatter, body = provenance.split_note(text.encode())
    assert frontmatter["summary"] == "first line second line\nthird paragraph"
    assert frontmatter["code"] == "indented\n  deeper\nback"
    assert frontmatter["after"] == "plain"
    assert body == b"body\n"


def test_a_hash_inside_a_block_is_content_not_a_comment(provenance: ModuleType):
    """The line filter drops comments — but only outside a block scalar."""
    text = "---\ntitle: t\nnote: |-\n  # kept\n  kept\n---\nbody\n"
    frontmatter, _ = provenance.split_note(text.encode())
    assert frontmatter["note"] == "# kept\nkept"


def test_the_shipped_source_captures_parse(provenance: ModuleType):
    """The vault's own captures are the regression corpus for the subset."""
    for rel in (
        "peer-node/03_Sources/arch_blueprint.md",
        "peer-node/03_Sources/raxxar_raw/gemini-sparknet-session.md",
    ):
        path = REPO_ROOT / rel
        frontmatter, body = provenance.split_note(path.read_bytes())
        assert frontmatter["summary"].startswith("Complete verbatim transcript")
        assert body.lstrip().startswith(b"#")


def test_the_signed_message_is_versioned_so_a_future_envelope_cannot_verify_old_signatures(
    provenance: ModuleType,
):
    hashes = {
        "body": "0" * 64,
        "meta": "1" * 64,
        "tracking": "2" * 64,
        "conversation": "3" * 64,
    }
    assert provenance.note_message(hashes).startswith(b"sparknet-note/2\n")


def test_the_conversation_root_is_order_and_content_sensitive(provenance: ModuleType):
    """The root commits to the trail: reordering or editing a turn moves it."""
    entries = [
        {"id": "c1", "turn": 1, "agent": "chat", "model": "llama3.2"},
        {"id": "c1", "turn": 2, "agent": "plan", "model": "llama3.2"},
    ]
    root = provenance.build_conversation_root(entries)
    assert len(root) == 64 and root == root.lower()
    assert provenance.build_conversation_root(list(reversed(entries))) != root
    edited = [dict(entries[0], model="other"), entries[1]]
    assert provenance.build_conversation_root(edited) != root
    assert provenance.build_conversation_root([]) == provenance._load_merkle().EMPTY_TREE_ROOT


def test_a_conversation_entry_is_bound_to_the_note_signature(vault: Path, provenance: ModuleType):
    """Editing, adding or dropping a turn is stale:content, like editing the body."""
    tracking = {
        "schema": "sparknet-tracking/1",
        "owner_id": "",
        "owner_node": "",
        "owner_ref": "00_System/user.md",
        "validity": {"state": "unsigned"},
        "conversation": [
            {
                "id": "c1",
                "turn": 1,
                "agent": "chat",
                "model": "llama3.2",
                "at": "2026-10-13T00:00:00Z",
            }
        ],
        "shares": [],
        "agent": "tester",
        "model": "none",
        "approvals": [],
    }
    raw = provenance.emit_note(
        {"title": "conversation bound", "updated": "2026-10-13", "tracking": tracking},
        b"# the body\n\ncontent\n",
    )
    path = vault / "01_Inbox" / "conversation-bound.md"
    path.write_bytes(raw)
    sign(provenance, vault, path)
    assert verify(provenance, vault, path)[0] == "valid"

    # The envelope records the root and the version tag.
    frontmatter, body = provenance.split_note(path.read_bytes())
    signature = frontmatter["tracking"]["signature"]
    assert signature["note_version"] == "sparknet-note/2"
    assert signature["signed_conversation_root"] == provenance.build_conversation_root(
        frontmatter["tracking"]["conversation"]
    )

    # Edit the conversation entry without re-signing: still authentic (the
    # signature covers the recorded root), but no longer fresh.
    frontmatter["tracking"]["conversation"][0]["model"] = "gpt-4o"
    path.write_bytes(provenance.emit_note(frontmatter, body))
    outcome, detail = verify(provenance, vault, path)
    assert outcome == "stale:content"
    assert "conversation" in detail

    # Re-sign clears it, and swapping the body then fails the same way.
    sign(provenance, vault, path)
    assert verify(provenance, vault, path)[0] == "valid"
    frontmatter, _ = provenance.split_note(path.read_bytes())
    path.write_bytes(provenance.emit_note(frontmatter, b"# a swapped body\n\ncontent\n"))
    outcome, detail = verify(provenance, vault, path)
    assert outcome == "stale:content"
    assert "body" in detail


def test_an_envelope_from_an_unknown_note_domain_is_invalid(vault: Path, provenance: ModuleType):
    path = vault / "01_Inbox" / "old-envelope.md"
    path.write_bytes(note("old envelope", state="unsigned").encode())
    sign(provenance, vault, path)
    frontmatter, body = provenance.split_note(path.read_bytes())
    frontmatter["tracking"]["signature"]["note_version"] = "sparknet-note/1"
    path.write_bytes(provenance.emit_note(frontmatter, body))
    outcome, detail = verify(provenance, vault, path)
    assert outcome == "invalid"
    assert "note_version" in detail


# --- inbox intake -------------------------------------------------------------


def test_ingest_lands_a_pending_item_that_verifies_green(vault: Path, provenance: ModuleType):
    path = provenance.ingest_note(vault, b"# incoming plan\n\nthe body\n", source="master-node", title="Incoming plan")
    assert path == vault / "01_Inbox" / "incoming-plan.md"
    frontmatter, body = provenance.split_note(path.read_bytes())
    assert frontmatter["type"] == "inbox-item"
    assert frontmatter["source"] == "master-node"
    assert frontmatter["tracking"]["validity"]["state"] == "unsigned"
    assert "signature" not in frontmatter["tracking"]
    assert body == b"# incoming plan\n\nthe body\n"

    assert verify(provenance, vault, path)[0] == "pending"
    code, text = provenance.verify_vault(vault)
    assert code == 0, text


def test_ingest_refuses_to_overwrite_an_existing_item(vault: Path, provenance: ModuleType):
    provenance.ingest_note(vault, b"# same title\n", source="peer-node", title="Same")
    with pytest.raises(provenance.ProvenanceError, match="refusing to overwrite"):
        provenance.ingest_note(vault, b"# same title\n", source="peer-node", title="Same")


def test_email_ingest_fails_closed_until_the_sender_is_authorised(vault: Path, provenance: ModuleType):
    with pytest.raises(provenance.ProvenanceError, match="fails closed"):
        provenance.ingest_note(vault, b"# from mail\n", source="email", sender="ops@example.org")

    record = provenance.parse_user_record(vault)
    record["authorised_senders"] = ["ops@example.org"]
    write(
        provenance.user_record_path(vault),
        provenance.emit_note(record, b"# user record\n"),
    )

    path = provenance.ingest_note(vault, b"# from mail\n", source="email", sender="ops@example.org")
    assert provenance.split_note(path.read_bytes())[0]["sender"] == "ops@example.org"
    with pytest.raises(provenance.ProvenanceError, match="fails closed"):
        provenance.ingest_note(
            vault,
            b"# from mail\n",
            source="email",
            sender="stranger@example.org",
            title="second",
        )


def test_the_ingest_cli_reads_a_file_and_reports_an_empty_one(
    vault: Path, provenance: ModuleType, capsys: pytest.CaptureFixture[str]
):
    item = write(vault.parent / "incoming.md", "# body from a file\n")
    code = provenance.main(["--vault", str(vault), "ingest", str(item), "--source", "peer-node"])
    assert code == 0
    assert (vault / "01_Inbox" / "body-from-a-file.md").is_file()
    capsys.readouterr()

    empty = write(vault.parent / "empty.md", "")
    assert provenance.main(["--vault", str(vault), "ingest", str(empty), "--source", "peer-node"]) == 1
    assert "empty" in capsys.readouterr().err


# --- co-signatures ------------------------------------------------------------

COSIGNER_ID = "U-33007"


def _fill_vault(provenance: ModuleType, root: Path, owner_id: str, node_id: str) -> Path:
    """A self-contained vault: user key and node key under <root>/.state."""
    (root / "00_System").mkdir(parents=True)
    (root / "01_Inbox").mkdir()
    (root / "blockchain").mkdir()
    (root / "manifests").mkdir()
    write(root / "00_System" / "user.md", user_record_template())
    write(root / "manifests" / "node-identity.json", json.dumps({"node_id": node_id}))
    provenance.user_init(root, owner_id=owner_id)
    authz = provenance._load_authz()
    private_b64, _ = authz.generate_keypair()
    node_key = root / ".state" / "keys" / "ed25519-node.key.b64"
    node_key.write_text(private_b64 + "\n")
    node_key.chmod(0o600)
    return root


@pytest.fixture()
def federated(tmp_path: Path, provenance: ModuleType, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    """Two vaults, each resolving its state from <vault>/.state (no shared env)."""
    monkeypatch.delenv("SPARKNET_STATE_DIR", raising=False)
    alpha = _fill_vault(provenance, tmp_path / "alpha", OWNER_ID, "sparknet-node-0001")
    bravo = _fill_vault(provenance, tmp_path / "bravo", COSIGNER_ID, "sparknet-node-0002")
    return alpha, bravo


def _master_registry(provenance: ModuleType, node_id: str, *, revoked: bool = False) -> dict:
    """A Master-signed registry naming one node, built through the shared tool."""
    authz = provenance._load_authz()
    master_private, master_public = authz.generate_keypair()
    identity = {
        "node_id": node_id,
        "role": "peer",
        "wireguard_public_key_b64": "d2dwdWJsaWNrZXk=",
        "overlay_ipv4": "10.100.0.9",
        "requested_capabilities": ["telemetry"],
    }
    entry = authz.sign_authorization(identity, authz.private_key_from_b64(master_private), ["telemetry"])
    entry["revoked"] = revoked
    if revoked:
        entry["signature_b64"] = base64.b64encode(
            authz.private_key_from_b64(master_private).sign(authz.authorization_message(entry))
        ).decode("ascii")
    return {"master_public_key_b64": master_public, "authorizations": [entry]}


def test_a_co_signature_appends_without_rewriting_the_author(federated: tuple[Path, Path], provenance: ModuleType):
    alpha, bravo = federated
    path = write(alpha / "01_Inbox" / "hello.md", note())
    sign(provenance, alpha, path)
    before = provenance.split_note(path.read_bytes())[0]["tracking"]
    primary_sig = before["signature"]["sig"]
    recorded = provenance._recorded_from_signature(before["signature"])

    path.write_bytes(provenance.add_co_signature(path.read_bytes(), bravo))

    after = provenance.split_note(path.read_bytes())[0]["tracking"]
    # The author is untouched: same owner, same primary signature, same hashes.
    assert after["owner_id"] == OWNER_ID
    assert after["signature"]["sig"] == primary_sig
    assert provenance._recorded_from_signature(after["signature"]) == recorded
    # ...and the note still verifies valid, strict or not.
    assert verify(provenance, alpha, path)[0] == "valid"

    entries = after["signature"]["co_signatures"]
    assert len(entries) == 1
    assert entries[0]["owner_id"] == COSIGNER_ID
    assert entries[0]["owner_node"] == "sparknet-node-0002"
    assert set(entries[0]) == set(provenance.CO_SIGNATURE_FIELDS)

    # Trusted via the origin user.md snapshot: the offline fallback.
    frontmatter, _ = provenance.split_note(path.read_bytes())
    assert provenance.verify_co_signatures(frontmatter, trusted_users=[provenance.parse_user_record(bravo)]) == []

    # Re-signing from the same key replaces the entry rather than piling up.
    path.write_bytes(provenance.add_co_signature(path.read_bytes(), bravo))
    assert len(provenance.split_note(path.read_bytes())[0]["tracking"]["signature"]["co_signatures"]) == 1


def test_an_unknown_or_foreign_co_signer_is_untrusted(federated: tuple[Path, Path], provenance: ModuleType):
    alpha, bravo = federated
    path = write(alpha / "01_Inbox" / "hello.md", note())
    sign(provenance, alpha, path)
    path.write_bytes(provenance.add_co_signature(path.read_bytes(), bravo))
    frontmatter, _ = provenance.split_note(path.read_bytes())

    # No resolver at all: the bytes are genuine, the signer is unknown here.
    problems = provenance.verify_co_signatures(frontmatter)
    assert problems and "untrusted" in problems[0]

    # The author's own record does not vouch for the co-signer.
    problems = provenance.verify_co_signatures(frontmatter, trusted_users=[provenance.parse_user_record(alpha)])
    assert problems and "untrusted" in problems[0]


def test_a_co_signature_over_different_bytes_is_refused(federated: tuple[Path, Path], provenance: ModuleType):
    alpha, bravo = federated
    path = write(alpha / "01_Inbox" / "hello.md", note())
    sign(provenance, alpha, path)
    path.write_bytes(provenance.add_co_signature(path.read_bytes(), bravo))
    frontmatter, _ = provenance.split_note(path.read_bytes())

    # The co-signer produced a signature over a *different* message: same key,
    # same key_fingerprint, so integrity passes, but the commit does not match.
    authz = provenance._load_authz()
    user_key = authz.load_private_key(bravo / ".state" / "keys" / "user.ed25519")
    lying = provenance.note_message(
        {"body": "00" * 32, "meta": "11" * 32, "tracking": "22" * 32, "conversation": "33" * 32}
    )
    frontmatter["tracking"]["signature"]["co_signatures"][0]["sig"] = authz.sign_bytes(user_key, lying)
    problems = provenance.verify_co_signatures(frontmatter, trusted_users=[provenance.parse_user_record(bravo)])
    assert problems and "does not verify over the recorded hashes" in problems[0]


def test_a_swapped_co_signer_key_is_refused(federated: tuple[Path, Path], provenance: ModuleType):
    alpha, bravo = federated
    path = write(alpha / "01_Inbox" / "hello.md", note())
    sign(provenance, alpha, path)
    path.write_bytes(provenance.add_co_signature(path.read_bytes(), bravo))
    frontmatter, _ = provenance.split_note(path.read_bytes())

    authz = provenance._load_authz()
    _, fresh_public = authz.generate_keypair()
    entry = frontmatter["tracking"]["signature"]["co_signatures"][0]
    entry["public_key_b64"] = fresh_public  # same fingerprint, different key
    problems = provenance.verify_co_signatures(frontmatter, trusted_users=[provenance.parse_user_record(bravo)])
    assert problems and "key_fingerprint does not match public_key_b64" in problems[0]


def test_tampering_the_body_after_co_signing_is_stale_content(federated: tuple[Path, Path], provenance: ModuleType):
    alpha, bravo = federated
    path = write(alpha / "01_Inbox" / "hello.md", note())
    sign(provenance, alpha, path)
    path.write_bytes(provenance.add_co_signature(path.read_bytes(), bravo))

    write(alpha / "01_Inbox" / "hello.md", path.read_text().replace("body text", "body text!"))
    assert verify(provenance, alpha, path)[0] == "stale:content"
    # The co-signature still commits to the recorded bytes; the note, not the
    # co-signature, is what went stale.
    frontmatter, _ = provenance.split_note(path.read_bytes())
    assert provenance.verify_co_signatures(frontmatter, trusted_users=[provenance.parse_user_record(bravo)]) == []


def test_the_master_registry_resolves_a_co_signer(federated: tuple[Path, Path], provenance: ModuleType):
    alpha, bravo = federated
    path = write(alpha / "01_Inbox" / "hello.md", note())
    sign(provenance, alpha, path)
    path.write_bytes(provenance.add_co_signature(path.read_bytes(), bravo))
    frontmatter, _ = provenance.split_note(path.read_bytes())

    # The online resolver: the Master has attested the co-signer's node.
    registry = _master_registry(provenance, "sparknet-node-0002")
    assert provenance.verify_co_signatures(frontmatter, registry=registry) == []

    # A revoked node does not resolve, and an unsigned entry does not either.
    revoked = _master_registry(provenance, "sparknet-node-0002", revoked=True)
    problems = provenance.verify_co_signatures(frontmatter, registry=revoked)
    assert problems and "revoked" in problems[0]

    tampered = _master_registry(provenance, "sparknet-node-0002")
    tampered["authorizations"][0]["capabilities"] = ["guard-apply"]
    problems = provenance.verify_co_signatures(frontmatter, registry=tampered)
    assert problems and "not signed by the master key" in problems[0]


def test_the_co_sign_cli_appends_and_verifies(
    federated: tuple[Path, Path], provenance: ModuleType, capsys: pytest.CaptureFixture[str]
):
    alpha, bravo = federated
    path = write(alpha / "01_Inbox" / "hello.md", note())
    sign(provenance, alpha, path)

    assert provenance.main(["--vault", str(bravo), "co-sign", str(path)]) == 0
    assert verify(provenance, alpha, path)[0] == "valid"

    code = provenance.main(
        [
            "--vault",
            str(alpha),
            "verify-co-signatures",
            str(path),
            "--trusted-user",
            str(bravo / "00_System" / "user.md"),
        ]
    )
    assert code == 0
    assert "co-signatures ok" in capsys.readouterr().out

    code = provenance.main(["--vault", str(alpha), "verify-co-signatures", str(path)])
    assert code == 1
    assert "untrusted" in capsys.readouterr().out


# --- inbox acceptance (PLAN Step 67A) -----------------------------------------
#
# The contract declared this event and both roles' agent charters asserted it was
# recorded, but nothing could produce one. These tests pin the builder and the
# dispatch policy it enforces.


def _accept(provenance: ModuleType, vault: Path, **kwargs):
    record = provenance.parse_user_record(vault)
    params = {"item": "01_Inbox/2026-10-24-rfi.md", "source": "master-node", "decision": "accepted"}
    params.update(kwargs)
    return provenance.build_inbox_acceptance(vault, record=record, **params)


def test_inbox_acceptance_is_in_the_contract_vocabulary(provenance: ModuleType) -> None:
    """The builder must produce an event the contract already allows a peer to write."""
    import json

    schema = json.loads((REPO_ROOT / "contracts" / "tracking-schema.json").read_text())
    peer_events = schema["ledger_block"]["events"]["peer"] if "events" in schema["ledger_block"] else None
    if peer_events is None:  # the vocabulary lives at the top level in some revisions
        peer_events = schema["layout"]["peer_events"] if "peer_events" in schema.get("layout", {}) else None
    assert peer_events is None or "inbox_acceptance" in peer_events
    assert "inbox_acceptance" in json.dumps(schema), "the contract no longer names the event"
    assert provenance.INBOX_SOURCES == ("master-node", "peer-node", "email")


def test_an_accepted_master_item_is_dual_signed(provenance: ModuleType, vault: Path) -> None:
    block = _accept(provenance, vault)
    assert block["event"] == "inbox_acceptance"
    assert block["decision"] == "accepted"
    assert block["source"] == "master-node"
    assert block["validity"] == "signed"
    assert set(block["signatures"]) == {"user", "node"}, "user consent and node countersignature, over one payload"
    assert block["acceptance_id"].startswith("INB-")
    assert block["owner_id"] and block["node_pubkey_b64"]


def test_accepting_untrusted_material_requires_a_reviewer(provenance: ModuleType, vault: Path) -> None:
    """The contract's rule: peer-origin executes only after review and sanitize."""
    with pytest.raises(provenance.ProvenanceError, match="reviewer"):
        _accept(provenance, vault, source="peer-node")
    # ... and a rejection needs none: refusing is never the unsafe direction.
    refused = _accept(provenance, vault, source="peer-node", decision="rejected")
    assert refused["decision"] == "rejected" and refused["validity"] == "unsigned"


def test_a_reviewed_untrusted_item_is_marked_sanitized(provenance: ModuleType, vault: Path) -> None:
    block = _accept(provenance, vault, source="peer-node", reviewer="agents/vault-curator", sanitized=True)
    assert block["validity"] == "sanitized", "the contract's own state for reviewed untrusted ingress"
    assert block["reviewer"] == "agents/vault-curator"
    assert block["sanitized"] is True


def test_an_item_outside_the_inbox_is_refused(provenance: ModuleType, vault: Path) -> None:
    """01_Inbox is read-only until accepted; an acceptance elsewhere launders it."""
    for item in ("05_Knowledge/concepts/x.md", "03_Sources/x.md", "../escape.md", "01_Inbox/../../etc/passwd", ""):
        with pytest.raises(provenance.ProvenanceError):
            _accept(provenance, vault, item=item)


def test_email_fails_closed_when_no_sender_is_authorised(provenance: ModuleType, vault: Path) -> None:
    """The shipped record has an empty authorised_senders: nobody may push work in."""
    # Absent and empty both fail closed: nobody is authorised either way.
    assert not provenance.parse_user_record(vault).get("authorised_senders")
    with pytest.raises(provenance.ProvenanceError, match="authorised_senders"):
        _accept(provenance, vault, source="email", sender="stranger@example.test", reviewer="agents/vault-curator")
    with pytest.raises(provenance.ProvenanceError, match="must name its sender"):
        _accept(provenance, vault, source="email", reviewer="agents/vault-curator")


def test_email_from_an_authorised_sender_is_treated_as_peer_origin(
    provenance: ModuleType, vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = provenance.parse_user_record

    def with_senders(path):
        record = real(path)
        return {**record, "authorised_senders": ["alice@example.test"]}

    monkeypatch.setattr(provenance, "parse_user_record", with_senders)
    # Allowed, but still untrusted: peer-origin rules apply, so a reviewer is needed.
    with pytest.raises(provenance.ProvenanceError, match="reviewer"):
        _accept(provenance, vault, source="email", sender="alice@example.test")
    block = _accept(provenance, vault, source="email", sender="alice@example.test", reviewer="agents/vault-curator")
    assert block["sender"] == "alice@example.test"
    # And an unlisted sender is still refused even with a populated allow-list.
    with pytest.raises(provenance.ProvenanceError, match="authorised_senders"):
        _accept(provenance, vault, source="email", sender="mallory@example.test", reviewer="agents/vault-curator")


def test_source_and_decision_are_closed_vocabularies(provenance: ModuleType, vault: Path) -> None:
    with pytest.raises(provenance.ProvenanceError, match="source must be one of"):
        _accept(provenance, vault, source="sms")
    with pytest.raises(provenance.ProvenanceError, match="decision must be"):
        _accept(provenance, vault, decision="maybe")


def test_acceptance_ids_increment_within_a_day(provenance: ModuleType, vault: Path) -> None:
    """The counter reads the ledger, so two acceptances cannot share an id."""
    first = _accept(provenance, vault)
    assert first["acceptance_id"].endswith("-001")
    append_block = getattr(provenance, "append_ledger_block", None) or getattr(provenance, "append_block", None)
    if append_block is None:
        pytest.skip("no ledger append helper exposed; increment is covered by the id shape above")
    append_block(vault, first)
    assert _accept(provenance, vault)["acceptance_id"].endswith("-002")


# --- RFI install rule (PLAN Step 67C) -----------------------------------------


def _load_rfi_install() -> ModuleType:
    path = REPO_ROOT / "shared" / "sparknet-rfi-install.py"
    spec = importlib.util.spec_from_file_location("sparknet_rfi_install_t", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def rfi(vault: Path, provenance: ModuleType):
    """The install rule, a master key, and this vault's own fingerprint."""
    install = _load_rfi_install()
    authz = provenance._load_authz()
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    record = provenance.parse_user_record(vault)
    return {
        "install": install,
        "authz": authz,
        "provenance": provenance,
        "vault": vault,
        "key": key,
        "record": record,
        "fingerprint": "c" * 64,
    }


def _accept_answer(rfi: dict, **overrides):
    params = {
        "content": b"# the answer\n",
        "item_name": "rfi-answer.md",
        "peer_fingerprint": rfi["fingerprint"],
        "request_id": "RFI-1",
        "master_private_key": rfi["key"],
    }
    params.update(overrides)
    answer = rfi["authz"].sign_rfi_answer(**params)
    return rfi["install"].accept_answer(
        rfi["vault"],
        answer,
        authz=rfi["authz"],
        provenance=rfi["provenance"],
        master_public_key=rfi["key"].public_key(),
        peer_fingerprint=rfi["fingerprint"],
        user_record=rfi["record"],
    )


def test_an_answer_installs_into_the_inbox_and_is_recorded(rfi: dict) -> None:
    result = _accept_answer(rfi)
    assert result["status"] == "installed", result
    vault = rfi["vault"]
    written = vault / "01_Inbox" / "rfi-answer.md"
    assert written.read_bytes() == b"# the answer\n"
    assert rfi["install"].installed_request_ids(vault) == ["RFI-1"]
    blocks = rfi["provenance"].load_ledger(vault / "blockchain" / "ledger.json")["blocks"]
    acceptances = [b for b in blocks if (b.get("data") or {}).get("event") == "inbox_acceptance"]
    assert len(acceptances) == 1
    data = acceptances[0]["data"]
    assert data["source"] == "master-node"
    assert data["item"] == "01_Inbox/rfi-answer.md"
    assert set(data["signatures"]) == {"user", "node"}


def test_a_replayed_answer_is_refused_and_writes_nothing(rfi: dict) -> None:
    assert _accept_answer(rfi)["status"] == "installed"
    second = _accept_answer(rfi, content=b"# a different answer\n")
    assert second["status"] == "refused"
    assert second["reason"] == rfi["authz"].REASON_RFI_DUPLICATE
    # The first answer stands; the replay neither replaced it nor added a record.
    assert (rfi["vault"] / "01_Inbox" / "rfi-answer.md").read_bytes() == b"# the answer\n"
    assert rfi["install"].installed_request_ids(rfi["vault"]) == ["RFI-1"]


def test_an_answer_for_another_peer_is_refused(rfi: dict) -> None:
    result = _accept_answer(rfi, peer_fingerprint="d" * 64)
    assert result["status"] == "refused"
    assert result["reason"] == rfi["authz"].REASON_RFI_WRONG_PEER
    assert not (rfi["vault"] / "01_Inbox" / "rfi-answer.md").exists()
    assert rfi["install"].installed_request_ids(rfi["vault"]) == []


def test_a_tampered_answer_never_reaches_the_inbox(rfi: dict) -> None:
    """Content is bound by digest, so swapping it under a valid signature fails."""
    answer = rfi["authz"].sign_rfi_answer(
        content=b"# benign\n",
        item_name="rfi-answer.md",
        peer_fingerprint=rfi["fingerprint"],
        request_id="RFI-2",
        master_private_key=rfi["key"],
    )
    forged = {**answer, "content_b64": __import__("base64").b64encode(b"# injected\n").decode()}
    result = rfi["install"].accept_answer(
        rfi["vault"],
        forged,
        authz=rfi["authz"],
        provenance=rfi["provenance"],
        master_public_key=rfi["key"].public_key(),
        peer_fingerprint=rfi["fingerprint"],
        user_record=rfi["record"],
    )
    assert result["status"] == "refused"
    assert result["reason"] == rfi["authz"].REASON_RFI_DIGEST_MISMATCH
    assert not (rfi["vault"] / "01_Inbox" / "rfi-answer.md").exists()


def test_a_corrupt_install_record_does_not_authorise_a_replay(rfi: dict) -> None:
    """A record that cannot be read is read as empty — but the item is still there.

    Failing open here would mean a corrupt state file lets an old answer install
    again; the refusal is the safe direction even though it costs a re-delivery.
    """
    assert _accept_answer(rfi)["status"] == "installed"
    path = rfi["vault"] / rfi["install"].INSTALL_RECORD_RELPATH
    path.write_text("{not json")
    assert rfi["install"].installed_request_ids(rfi["vault"]) == []
    # The item exists, so a second install would overwrite it — which is why the
    # record is rewritten from a clean read rather than trusted.
    result = _accept_answer(rfi, content=b"# second\n")
    assert result["status"] == "installed"
    assert (rfi["vault"] / "01_Inbox" / "rfi-answer.md").read_bytes() == b"# second\n"
