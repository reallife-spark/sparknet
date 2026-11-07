"""O1→O2→O5: accepted notes become a daily append and a human-staged candidate."""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PIPELINE_PATH = REPO_ROOT / "shared" / "sparknet-pipeline.py"
PROVENANCE_PATH = REPO_ROOT / "shared" / "sparknet-provenance.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


provenance = _load("pipeline_provenance_test", PROVENANCE_PATH)
pipeline = _load("pipeline_test", PIPELINE_PATH)
FIXED = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
OWNER = "U-10421"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    (root / "00_System").mkdir(parents=True)
    (root / "01_Inbox").mkdir()
    (root / "blockchain").mkdir()
    _write(
        root / "00_System" / "user.md",
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
        "  key_ref: $SPARKNET_STATE_DIR/keys/user.ed25519\n"
        '  created: ""\n'
        "---\n\n"
        "# user record\n",
    )
    state = tmp_path / "state"
    monkeypatch.setenv("SPARKNET_STATE_DIR", str(state))
    provenance.user_init(root, owner_id=OWNER)
    return root


def _inbox(vault: Path, *, classification="internal", title="Pipeline item"):
    path = provenance.ingest_note(
        vault,
        b"# Pipeline item\n\nThe raw body.\n",
        source="peer-node",
        title=title,
        classification=classification,
        clock=lambda: FIXED,
    )
    path.write_bytes(provenance.sign_note(path.read_bytes(), vault, agent="test", model="none"))
    return path


def test_plan_and_apply_write_signed_o2_and_stage_o5(vault: Path):
    source = _inbox(vault)
    planned = pipeline.plan(vault, today="2026-11-07")
    entry = next(row for row in planned["entries"] if row["source"] == "01_Inbox/pipeline-item.md")
    assert entry["status"] == "ready"
    assert entry["o2_target"] == "02_Daily/2026-11-07.md"
    assert entry["o5_target"] == "_staging/o5/2026-11-07-pipeline-item.md"

    applied = pipeline.apply_plan(vault, planned["entries"], confirm=True)
    assert applied["applied"][0]["source"] == "01_Inbox/pipeline-item.md"
    assert source.exists(), "the O1 source is never deleted"
    o2 = vault / "02_Daily" / "2026-11-07.md"
    o5 = vault / "_staging" / "o5" / "2026-11-07-pipeline-item.md"
    assert o2.is_file() and o5.is_file()
    assert provenance.verify_note(o2, vault=vault)[0] == "valid"
    assert provenance.verify_note(o5, vault=vault)[0] == "valid"
    o5_meta, _ = provenance.split_note(o5.read_bytes())
    assert o5_meta["type"] == "o5-candidate"
    assert o5_meta["classification"] == "internal"
    assert o5_meta["source_sha256"] == entry["source_sha256"]

    again = pipeline.plan(vault, today="2026-11-07")
    row = next(row for row in again["entries"] if row["source"] == "01_Inbox/pipeline-item.md")
    assert row["status"] == "already-applied"


def test_apply_requires_confirmation_and_promotion_is_explicit(vault: Path):
    _inbox(vault)
    planned = pipeline.plan(vault, today="2026-11-07")
    with pytest.raises(pipeline.PipelineError) as refused:
        pipeline.apply_plan(vault, planned["entries"], confirm=False)
    assert refused.value.code == "confirmation-required"

    pipeline.apply_plan(vault, planned["entries"], confirm=True)
    candidate = "_staging/o5/2026-11-07-pipeline-item.md"
    with pytest.raises(pipeline.PipelineError) as promote_refused:
        pipeline.promote(vault, candidate, "concepts", confirm=False)
    assert promote_refused.value.code == "confirmation-required"
    promoted = pipeline.promote(vault, candidate, "concepts", confirm=True)
    assert promoted["target"] == "05_Knowledge/concepts/2026-11-07-pipeline-item.md"
    target = vault / promoted["target"]
    assert target.is_file()
    assert not (vault / candidate).exists()
    meta, _ = provenance.split_note(target.read_bytes())
    assert meta["type"] == "knowledge"
    assert meta["promoted_from"] == candidate


def test_untracked_daily_page_gets_a_companion_and_unsigned_source_is_skipped(vault: Path):
    _inbox(vault)
    _write(vault / "02_Daily" / "2026-11-07.md", "# human daily page\n")
    planned = pipeline.plan(vault, today="2026-11-07")
    entry = next(row for row in planned["entries"] if row["source"] == "01_Inbox/pipeline-item.md")
    assert entry["o2_target"] == "02_Daily/2026-11-07-o2.md"
    assert entry["o2_action"] == "create-companion"

    raw = provenance.ingest_note(vault, b"# pending\n", source="peer-node", title="Pending")
    planned = pipeline.plan(vault, today="2026-11-07")
    pending = next(row for row in planned["entries"] if row["source"] == raw.relative_to(vault).as_posix())
    assert pending["status"] == "skipped"
    assert pending["reason"] == "validity=unsigned"


def test_o5_conflict_is_refused_before_writing(vault: Path):
    _inbox(vault)
    conflict = vault / "_staging" / "o5" / "2026-11-07-pipeline-item.md"
    conflict.parent.mkdir(parents=True)
    _write(conflict, "---\ntitle: other\ntype: o5-candidate\nsource_sha256: " + "0" * 64 + "\n---\n\nother\n")
    planned = pipeline.plan(vault, today="2026-11-07")
    entry = next(row for row in planned["entries"] if row["source"] == "01_Inbox/pipeline-item.md")
    assert entry["status"] == "conflict"
    with pytest.raises(pipeline.PipelineError) as refused:
        pipeline.apply_plan(vault, planned["entries"], confirm=True)
    assert refused.value.code == "conflict"
