#!/usr/bin/env python3
"""Bake the fabric's knowledge into the model's precontext.

Three jobs, all deterministic and all derived from the shipped bundle (nothing
here is hand-written knowledge, and nothing reads the vault's personal pages):

  digest    contracts/ -> a compact markdown digest of the closed vocabulary
            (capabilities, ports, overlay addressing, identity fields). Pure
            stdlib, safe at image build time.

  template  A model's own HuggingFace chat template, with a system precontext
            prepended. vLLM's `--chat-template` replaces the tokenizer's
            template; handing it back the *original* template wrapped in a
            preamble is the model-agnostic way to inject a system message on
            every completion without guessing a model's token convention. Used
            at container start (needs `transformers`, present in every vLLM
            base).

The precontext is the MASTERSPIKE format prompt (the llm-wiki format, generated
from .opencode/skills/llm-wiki/SKILL.md) plus the fabric digest. It carries a
*format* and a *vocabulary*, never a capability or a secret: authority stays
Ed25519 in the Master.

Usage:
    spark-precontext.py digest   --contracts DIR --out FILE
    spark-precontext.py template --model M --prompt-file P [--prompt-file P2]
                                 --out FILE [--max-bytes N]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _load(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build_digest(contracts: Path) -> str:
    lines: list[str] = [
        "# SparkNet fabric digest",
        "",
        "Generated from `contracts/`. This is the closed vocabulary the fabric",
        "reasons in; it is descriptive, and it grants nothing.",
        "",
    ]

    caps = _load(contracts / "capabilities.json") or {}
    names = caps.get("known_capabilities") or [] if isinstance(caps, dict) else []
    defs = caps.get("definitions") or {} if isinstance(caps, dict) else {}
    if names:
        lines += ["## Capabilities (the closed vocabulary)", ""]
        for name in names:
            meta = defs.get(name, {}) if isinstance(defs, dict) else {}
            holder = meta.get("holder", "?")
            flag = "sensitive" if meta.get("sensitive") else "not sensitive"
            lines.append(f"- `{name}` — holder: {holder}, {flag}")
        lines.append("")

    ports = _load(contracts / "ports.json") or {}
    port_map = ports.get("ports") or {} if isinstance(ports, dict) else {}
    if port_map:
        lines += ["## Ports", ""]
        for num in sorted(port_map, key=lambda k: int(k)):
            meta = port_map[num] if isinstance(port_map[num], dict) else {}
            lines.append(
                f"- {num}: {meta.get('service', '?')} "
                f"({meta.get('implementation_state', '?')}, "
                f"bound_by {meta.get('bound_by', '?')})"
            )
        lines.append("")

    overlay = _load(contracts / "overlay.json") or {}
    if isinstance(overlay, dict) and overlay:
        lines += [
            "## Overlay addressing",
            "",
            f"- overlay_cidr: {overlay.get('overlay_cidr', '?')}",
            f"- master_anchor_ipv4: {overlay.get('master_anchor_ipv4', '?')}",
            f"- peer_prefix: {overlay.get('peer_prefix', '?')}{overlay.get('peer_mask', '')}",
            "",
        ]

    ident = _load(contracts / "identity-schema.json") or {}
    fields = ident.get("identity_fields") if isinstance(ident, dict) else None
    if fields:
        lines += [
            "## Identity fields (canonical, sorted)",
            "",
            f"- {', '.join(fields)}",
            "",
        ]

    lines += [
        "## The one rule",
        "",
        "Authority comes from key possession, not a capability grant. The Master",
        "signs; a peer verifies. Holding a capability name without the private",
        "key grants nothing.",
        "",
    ]
    return "\n".join(lines)


# The wrapper: prepend one system message (merging with an existing one when it
# is plain text), then fall through to the model's own template verbatim.
_PREAMBLE = """{%- set sparknet_precontext = __SPARKNET_PRECONTEXT__ -%}
{%- if messages and messages[0]['role'] == 'system' -%}
  {%- set _c = messages[0]['content'] -%}
  {%- if _c is string -%}
    {%- set _merged = sparknet_precontext + '\\n\\n' + _c -%}
  {%- else -%}
    {%- set _merged = [{'type': 'text', 'text': sparknet_precontext}] + _c -%}
  {%- endif -%}
  {%- set messages = [{'role': 'system', 'content': _merged}] + messages[1:] -%}
{%- else -%}
  {%- set messages = [{'role': 'system', 'content': sparknet_precontext}] + messages -%}
{%- endif -%}
"""


def build_template(model: str, prompt_files: list[str], max_bytes: int) -> str:
    try:
        from transformers import AutoTokenizer
    except ImportError as exc:  # pragma: no cover - depends on base image
        raise SystemExit(
            "spark-precontext: transformers is required to build a chat template "
            f"({exc}). Use a vLLM base image, or run `digest` only."
        ) from None

    parts: list[str] = []
    for path in prompt_files:
        try:
            parts.append(Path(path).read_text(encoding="utf-8").strip())
        except OSError as exc:
            raise SystemExit(f"spark-precontext: cannot read prompt file {path}: {exc}") from None
    precontext = "\n\n---\n\n".join(p for p in parts if p)
    if not precontext:
        raise SystemExit("spark-precontext: precontext is empty; refusing to write a no-op template")
    if max_bytes > 0 and len(precontext.encode("utf-8")) > max_bytes:
        precontext = precontext.encode("utf-8")[:max_bytes].decode("utf-8", "ignore")

    try:
        tokenizer = AutoTokenizer.from_pretrained(model, trust_remote_code=True)
    except Exception:
        # The pinned tokenizers stack may refuse a model's regenerated
        # tokenizer.json (schema drift). The sentencepiece sidecar still
        # loads and carries the same chat template — losing the system
        # prompt to a parsing quirk is worse than a slow tokenizer here.
        tokenizer = AutoTokenizer.from_pretrained(model, trust_remote_code=True, use_fast=False)
    template = tokenizer.chat_template
    if isinstance(template, dict):
        template = template.get("default") or next(iter(template.values()))
    if not template:
        raise SystemExit(f"spark-precontext: model {model!r} ships no chat_template")

    preamble = _PREAMBLE.replace("__SPARKNET_PRECONTEXT__", json.dumps(precontext))
    return preamble + "\n" + template


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="bake the fabric's knowledge into a model's precontext")
    sub = parser.add_subparsers(dest="command", required=True)

    d = sub.add_parser("digest", help="contracts/ -> fabric digest markdown")
    d.add_argument("--contracts", required=True)
    d.add_argument("--out", required=True)

    t = sub.add_parser("template", help="model chat template with precontext prepended")
    t.add_argument("--model", required=True)
    t.add_argument("--prompt-file", action="append", default=[], dest="prompt_files")
    t.add_argument("--out", required=True)
    t.add_argument("--max-bytes", type=int, default=0, help="0 = no cap")

    args = parser.parse_args(argv)

    if args.command == "digest":
        contracts = Path(args.contracts)
        if not contracts.is_dir():
            print(f"spark-precontext: not a directory: {contracts}", file=sys.stderr)
            return 1
        Path(args.out).write_text(build_digest(contracts), encoding="utf-8")
        return 0

    if not args.prompt_files:
        print("spark-precontext: template needs at least one --prompt-file", file=sys.stderr)
        return 2
    Path(args.out).write_text(build_template(args.model, args.prompt_files, args.max_bytes), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
