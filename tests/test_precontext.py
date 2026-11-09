"""The precontext builder (`spark-precontext.py`).

Two jobs feed the model's system prompt from the shipped bundle, and nothing
else:

1. ``digest`` — ``contracts/`` into a compact, deterministic markdown digest.
   Pure stdlib, no network, no vault pages, safe at image build time.
2. ``template`` — the model's *own* HuggingFace chat template with a system
   precontext prepended. The precontext is JSON-embedded as a Jinja string
   literal, so it must survive arbitrary content — including the ``%`` and
   ``{}`` characters that appear both in prose and in the wrapper's own
   ``{%- ... -%}`` syntax.

The last test runs against this real repository's ``contracts/`` tree, so a
future contract file that breaks the digest surfaces here rather than on a DGX
Spark.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

from sparknet_loader import load_by_path  # shared/ comes from conftest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "spark-precontext.py"


def _load():
    return load_by_path("spark_precontext", SCRIPT)


pc = _load()


def _write(root: Path, rel: str, text: str = "x") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fake_transformers(chat_template: str) -> types.ModuleType:
    """A stand-in for `transformers` whose tokenizer ships a known template."""
    mod = types.ModuleType("transformers")

    class _Tokenizer:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            return cls()

    _Tokenizer.chat_template = chat_template
    mod.AutoTokenizer = _Tokenizer
    return mod


# --- digest -------------------------------------------------------------------


def test_digest_carries_the_closed_vocabulary(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "capabilities.json",
        json.dumps(
            {
                "known_capabilities": ["infer", "share"],
                "definitions": {
                    "infer": {"holder": "peer", "sensitive": False},
                    "share": {"holder": "master", "sensitive": True},
                },
            }
        ),
    )
    _write(tmp_path, "ports.json", json.dumps({"ports": {"8000": {"service": "vllm"}}}))
    _write(
        tmp_path,
        "overlay.json",
        json.dumps({"overlay_cidr": "10.100.0.0/24", "master_anchor_ipv4": "10.100.0.1"}),
    )
    _write(tmp_path, "identity-schema.json", json.dumps({"identity_fields": ["node_id", "role"]}))

    text = pc.build_digest(tmp_path)
    assert "`infer`" in text and "`share`" in text
    assert "8000: vllm" in text
    assert "10.100.0.0/24" in text
    assert "node_id, role" in text
    assert "The one rule" in text


def test_digest_is_deterministic_and_tolerates_missing_files(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert pc.build_digest(empty) == pc.build_digest(empty)
    assert "The one rule" in pc.build_digest(empty)


# --- template -----------------------------------------------------------------


def _model_only_tail(chat_template: str) -> str:
    return "\n" + chat_template


def test_template_prepends_precontext_and_keeps_the_model_template(tmp_path: Path, monkeypatch) -> None:
    # The precontext is adversarial on purpose: percent signs and braces are
    # exactly what broke a naive str-formatting implementation.
    prompt = tmp_path / "prompt.md"
    prompt.write_text("format 100% {ok} on %(x)s and {%- jinja -%}", encoding="utf-8")
    chat_template = "{{ messages }}"
    monkeypatch.setitem(sys.modules, "transformers", _fake_transformers(chat_template))

    out = pc.build_template("some/model", [str(prompt)], max_bytes=0)

    assert out.endswith(_model_only_tail(chat_template)), "model template must be appended verbatim"
    assert "sparknet_precontext" in out
    # The precontext is embedded as a JSON string literal, byte-for-byte.
    assert json.dumps(prompt.read_text(encoding="utf-8").strip()) in out


def test_template_joins_multiple_prompts_with_a_separator(tmp_path: Path, monkeypatch) -> None:
    a = tmp_path / "a.md"
    b = tmp_path / "b.md"
    a.write_text("ALPHA", encoding="utf-8")
    b.write_text("BETA", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "transformers", _fake_transformers("M"))

    out = pc.build_template("m", [str(a), str(b)], max_bytes=0)
    assert json.dumps("ALPHA\n\n---\n\nBETA") in out


def test_template_respects_the_byte_cap(tmp_path: Path, monkeypatch) -> None:
    big = tmp_path / "big.md"
    big.write_text("A" * 5000, encoding="utf-8")
    monkeypatch.setitem(sys.modules, "transformers", _fake_transformers("M"))

    out = pc.build_template("m", [str(big)], max_bytes=100)
    literal = json.loads(out.split("sparknet_precontext = ", 1)[1].split(" -%}", 1)[0])
    assert len(literal.encode("utf-8")) <= 100


def test_template_needs_at_least_one_prompt() -> None:
    assert pc.main(["template", "--model", "m", "--out", "/dev/null"]) == 2


# --- the real repository ------------------------------------------------------


def test_the_real_contract_tree_yields_a_useful_digest() -> None:
    text = pc.build_digest(REPO_ROOT / "contracts")
    assert text.startswith("# SparkNet fabric digest")
    assert "The one rule" in text
    # The fabric's defining invariant must survive into the model's precontext.
    assert "Authority comes from key possession" in text
