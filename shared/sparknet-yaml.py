#!/usr/bin/env python3
"""The fabric's frontmatter format: a documented YAML subset (parse + emit).

There is no YAML library in this fabric (third-party imports are
``cryptography`` only — ``peer-node/tests/test_services.py`` enforces it), and a
signature must be reproducible, so the parser cannot be a guess. This is a
deliberately small subset: nested mappings, sequences, quoted and plain
scalars, flow lists of scalars. Block scalars (``|``, ``>``) and tabs are
refused with a message rather than approximated. ``emit_yaml`` is the only
writer, so anything signed through it parses back to the same mapping.

This module is extracted from ``shared/sparknet-provenance.py`` (Step 40) so the
note format is one loadable unit. It is loaded *by path* — provenance finds it
through ``shared/sparknet_loader.py`` and re-exports the names it uses — because
the fabric carries exactly one implementation of the format and a plain import
would let a role end up with a private copy.

``ProvenanceError`` and ``FrontmatterError`` live here, not in provenance: this
is the lower layer, and ``FrontmatterError`` must subclass ``ProvenanceError``
(a malformed note is a provenance refusal, and many ``except ProvenanceError``
handlers in provenance must keep catching it). Defining the base here is what
lets this module load before provenance exists, without a cycle. Provenance
re-exports both, so ``provenance.ProvenanceError`` and
``provenance.FrontmatterError`` are unchanged for every caller.
"""

from __future__ import annotations

import json
import re
from typing import Any


class ProvenanceError(Exception):
    """A refusal with a message the caller can act on."""


class FrontmatterError(ProvenanceError):
    """The note is not in the frontmatter subset this tool can parse."""


class _Line:
    __slots__ = ("indent", "text")

    def __init__(self, indent: int, text: str) -> None:
        self.indent = indent
        self.text = text


def _split_frontmatter(raw: bytes) -> tuple[bytes, bytes]:
    """Split a note into (frontmatter_bytes, body_bytes)."""
    if not raw.startswith(b"---\n"):
        raise FrontmatterError("note does not start with a '---' frontmatter fence")
    end = raw.find(b"\n---\n", 3)
    if end == -1:
        raise FrontmatterError("frontmatter is not closed by a '---' fence")
    return raw[4:end], raw[end + 5 :]


#: `key: |`, `key: >-`, … — a block scalar. Expanded *before* the line filter
#: runs, because inside a block scalar a blank line is a blank line and a `#`
#: is content: the filter that drops both would otherwise silently change the
#: bytes every signature hashes.
_BLOCK_SCALAR = re.compile(r"^(?P<key>[^:#]+?):[ \t]*(?P<ind>[|>][+-]?)[ \t]*$")


def _fold_block(content: list[str], indicator: str) -> str:
    """Turn collected block-scalar lines into the scalar's string value."""
    style, chomp = indicator[0], indicator[1:]
    if style == "|":
        text = "\n".join(content)
    else:
        parts: list[str] = []
        for index, line in enumerate(content):
            if index == 0:
                parts.append(line)
            elif not line:
                parts.append("\n")
            elif not content[index - 1]:
                parts.append(line)
            else:
                parts.append(" " + line)
        text = "".join(parts)
    if chomp == "-":
        return text.rstrip("\n")
    if chomp == "+":
        return text
    return text.rstrip("\n") + ("\n" if text.strip() else "")


def _expand_block_scalars(text: str) -> str:
    """Replace `key: >-`/`|` blocks with one quoted line each.

    The rest of the parser only ever sees `key: "…"`, so a block scalar cannot
    smuggle in an indent the subset would reject. Content keeps its relative
    indentation (deeper lines stay deeper), which is what makes a literal
    block round-trip.
    """
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        match = _BLOCK_SCALAR.match(lines[i])
        if match is None:
            out.append(lines[i])
            i += 1
            continue
        key_indent = len(lines[i]) - len(lines[i].lstrip())
        content: list[str] = []
        pending_blanks: list[str] = []
        content_indent: int | None = None
        j = i + 1
        while j < len(lines):
            line = lines[j]
            if not line.strip():
                pending_blanks.append("")
                j += 1
                continue
            indent = len(line) - len(line.lstrip())
            if indent <= key_indent:
                break
            if content_indent is None:
                content_indent = indent
            content.extend(pending_blanks)
            pending_blanks = []
            content.append(line[content_indent:] if indent >= content_indent else line.lstrip())
            j += 1
        # Trailing blank lines belong to the block under `+` chomping; under
        # the default clip and under `-` they are stripped off again below.
        content.extend(pending_blanks)
        value = _fold_block(content, match.group("ind"))
        out.append(f"{match.group('key')}: {json.dumps(value, ensure_ascii=False)}")
        i = j
    return "\n".join(out)


def parse_yaml_subset(text: str) -> dict[str, Any]:
    lines: list[_Line] = []
    text = _expand_block_scalars(text)
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent_text = raw[: len(raw) - len(raw.lstrip())]
        if "\t" in indent_text:
            raise FrontmatterError(f"line {number}: tabs are not allowed in frontmatter")
        stripped = raw.strip()
        if stripped[:1] in ("|", ">") and stripped[:2] not in ("|-", ">-", "|+", ">+"):
            raise FrontmatterError(
                f"line {number}: block scalars are outside the frontmatter subset; use a quoted single-line string"
            )
        lines.append(_Line(len(indent_text), stripped))
    if not lines:
        return {}
    value, next_index = _parse_block(lines, 0, lines[0].indent)
    if next_index != len(lines):
        raise FrontmatterError(f"unparsed frontmatter at {lines[next_index].text!r}")
    if not isinstance(value, dict):
        raise FrontmatterError("frontmatter must be a mapping at the top level")
    return value


def _is_seq_item(text: str) -> bool:
    return text == "-" or text.startswith("- ")


def _split_entry(text: str) -> tuple[str, str] | None:
    """Split `key: value` / `key:` on the first colon YAML treats as an entry."""
    if text.startswith(('"', "'")):
        return None
    match = re.match(r"^([^:]+?):(\s.*|\s*)$", text)
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def _parse_block(lines: list[_Line], start: int, indent: int) -> tuple[Any, int]:
    if start >= len(lines):
        return None, start
    if lines[start].indent != indent:
        raise FrontmatterError(f"unexpected indent at {lines[start].text!r}")
    if _is_seq_item(lines[start].text):
        return _parse_seq(lines, start, indent)
    return _parse_map(lines, start, indent)


def _parse_seq(lines: list[_Line], start: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    i = start
    while i < len(lines) and lines[i].indent == indent and _is_seq_item(lines[i].text):
        content = lines[i].text[1:].lstrip()
        if not content:
            if i + 1 < len(lines) and lines[i + 1].indent > indent:
                value, i = _parse_block(lines, i + 1, lines[i + 1].indent)
                items.append(value)
            else:
                items.append(None)
                i += 1
            continue
        if _split_entry(content) is None:
            items.append(_scalar(content))
            i += 1
            continue
        # The item is itself a mapping: rewrite this line at the item's content
        # column, then parse the item as a map. Lines still indented deeper than
        # the sequence belong to this item and no further.
        item_lines = [_Line(indent + 2, content)]
        j = i + 1
        while j < len(lines) and lines[j].indent > indent:
            item_lines.append(lines[j])
            j += 1
        value, consumed = _parse_block(item_lines, 0, item_lines[0].indent)
        if consumed != len(item_lines):
            raise FrontmatterError(f"unparsed content in sequence item: {item_lines[consumed].text!r}")
        items.append(value)
        i = j
    return items, i


def _parse_map(lines: list[_Line], start: int, indent: int) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    i = start
    while i < len(lines) and lines[i].indent == indent:
        if _is_seq_item(lines[i].text):
            break
        entry = _split_entry(lines[i].text)
        if entry is None:
            raise FrontmatterError(f"expected 'key: value', got {lines[i].text!r}")
        key, rest = entry
        if rest:
            out[key] = _scalar(rest)
            i += 1
        elif i + 1 < len(lines) and lines[i + 1].indent > indent:
            value, i = _parse_block(lines, i + 1, lines[i + 1].indent)
            out[key] = value
        elif i + 1 < len(lines) and lines[i + 1].indent == indent and _is_seq_item(lines[i + 1].text):
            # YAML allows a sequence at the same indent as its key.
            value, i = _parse_seq(lines, i + 1, indent)
            out[key] = value
        else:
            out[key] = None
            i += 1
    if i < len(lines) and lines[i].indent > indent:
        raise FrontmatterError(f"unexpected indent at {lines[i].text!r}")
    return out, i


def _scalar(text: str) -> Any:
    if text.startswith('"'):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise FrontmatterError(f"unterminated quoted string: {text!r}") from exc
    if text.startswith("'"):
        if not text.endswith("'") or len(text) < 2:
            raise FrontmatterError(f"unterminated quoted string: {text!r}")
        return text[1:-1].replace("''", "'")
    if text == "{}":
        return {}
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        parts: list[str] = []
        depth = 0
        quote = ""
        current = ""
        escaped = False
        for char in inner:
            if quote:
                current += char
                if escaped:
                    escaped = False
                elif char == "\\" and quote == '"':
                    escaped = True
                elif char == quote:
                    quote = ""
                continue
            if char in "\"'":
                quote = char
                current += char
                continue
            if char in "[{":
                depth += 1
            elif char in "]}":
                depth -= 1
            if char == "," and depth == 0:
                parts.append(current.strip())
                current = ""
                continue
            current += char
        if current.strip():
            parts.append(current.strip())
        return [_scalar(part) for part in parts]
    lowered = text.lower()
    if lowered in ("null", "~"):
        return None
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text


#: Words the parser reads as something other than the string they spell.
_PLAIN_UNSAFE_WORDS = frozenset({"null", "~", "true", "false", "yes", "no", "on", "off"})

#: A scalar the parser would hand back as a number rather than as the string.
_PLAIN_UNSAFE_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")

#: Leading characters YAML reserves for indicators; a plain scalar may not start
#: with one without being read as a sequence item, a comment, a tag and so on.
_PLAIN_UNSAFE_LEAD = frozenset("-?:,[]{}#&*!|>'\"%@`")

#: Patterns that make a plain value ambiguous to a reader outside this subset:
#: a `key: value` pair hiding in a value, a trailing comment, or a stray quote.
_PLAIN_UNSAFE_INNER = (": ", " #", '"', "'", "\n", "\t", ",", "[", "]", "{", "}")


def _fmt_str(value: str) -> str:
    """Quote only what needs quoting.

    Quoting everything would be safe and unreadable — these files are knowledge
    pages a human opens, and `title: "the vault"` in every frontmatter is noise.
    The rule is therefore narrow: emit plain when re-parsing the plain form
    yields exactly this string and no YAML reader could take it otherwise.
    """
    needs_quotes = (
        value == ""
        or value.strip() != value
        or value.lower() in _PLAIN_UNSAFE_WORDS
        or _PLAIN_UNSAFE_NUMBER.fullmatch(value) is not None
        or value[0] in _PLAIN_UNSAFE_LEAD
        or any(pattern in value for pattern in _PLAIN_UNSAFE_INNER)
    )
    if needs_quotes:
        return json.dumps(value, ensure_ascii=False)
    return value


def _fmt_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int | float):
        return str(value)
    if isinstance(value, str):
        return _fmt_str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_fmt_scalar(item) for item in value) + "]"
    raise FrontmatterError(f"cannot emit value of type {type(value).__name__}")


def emit_yaml(data: dict[str, Any]) -> str:
    """Serialize back through the subset, so what is signed is what parses."""
    return "\n".join(_emit_map(data, 0)) + "\n"


def _emit_map(data: dict[str, Any], indent: int) -> list[str]:
    pad = "  " * indent
    out: list[str] = []
    for key, value in data.items():
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", str(key)):
            raise FrontmatterError(f"frontmatter key {key!r} is outside the subset")
        if isinstance(value, dict):
            if not value:
                out.append(f"{pad}{key}: {{}}")
            else:
                out.append(f"{pad}{key}:")
                out.extend(_emit_map(value, indent + 1))
        elif isinstance(value, list):
            if not value:
                out.append(f"{pad}{key}: []")
            elif any(isinstance(item, dict | list) for item in value):
                out.append(f"{pad}{key}:")
                for item in value:
                    if not isinstance(item, dict):
                        raise FrontmatterError("nested sequences are outside the frontmatter subset")
                    sub = _emit_map(item, indent + 2)
                    item_pad = "  " * (indent + 2)
                    out.append(f"{pad}  - {sub[0][len(item_pad) :]}")
                    out.extend(sub[1:])
            else:
                out.append(f"{pad}{key}: " + _fmt_scalar(value))
        else:
            out.append(f"{pad}{key}: {_fmt_scalar(value)}")
    return out
