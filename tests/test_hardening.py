"""Robustness invariants that are invisible in a normal functional run.

These are the "make it hard to get wrong again" gates for three weaknesses found
in a fail-safe review of the security surface:

1. **Base64 strictness drift.** CPython's tolerant base64 decoder accepts some
   malformed input (a stray padding byte, non-canonical length) on one version
   and raises on another with ``validate=True``. A signature decoded tolerantly on
   one node and strictly on another is a portability bug in the layer whose whole
   job is to be trusted about signatures, so every decode of a signature, key or
   wire body must go through the one strict helper (or pass ``validate=True``).

2. **Overlay-config pinning.** Both anchors must ``chattr +i`` *both* the
   authoritative state-dir config and the conventional ``/etc/wireguard`` copy.
   Pinning only one leaves the other as a mutable path to the live overlay, and
   the code and the docs drifted on exactly this once.

Files here read the source text; they prove a property of *this tree*, not of a
running node.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {"__pycache__", ".git", ".venv", "dist", "node_modules", ".pytest_cache", ".ruff_cache", ".opencode"}

# The one module allowed to call b64decode directly: the strict helper lives here,
# and load_private_key legitimately tries base64 *and* hex.
STRICT_HELPER_MODULE = "shared/sparknet-authz.py"


def _python_sources() -> list[Path]:
    roots = [REPO_ROOT / "shared", REPO_ROOT / "peer-node" / "services", REPO_ROOT / "master-node" / "services"]
    out: list[Path] = []
    for root in roots:
        out.extend(p for p in root.rglob("*.py") if p.is_file() and not SKIP_DIRS & set(p.parts))
    return sorted(out)


# Any base64 decode call: ``b64decode(...)`` or ``urlsafe_b64decode(...)``.
_B64_CALL = re.compile(r"\b(?:urlsafe_)?b64decode\s*\(")


def test_every_base64_decode_is_strict_or_uses_the_helper() -> None:
    """A tolerant base64 decode of a signature/key/body is a portability trap.

    A call is acceptable when it either passes ``validate=True`` or is the
    ``decode_b64_strict`` helper (whose body carries ``validate=True``). The
    helper module is exempt because that is where the one strict call lives.
    """
    offenders: list[str] = []
    for path in _python_sources():
        rel = str(path.relative_to(REPO_ROOT))
        if rel == STRICT_HELPER_MODULE:
            continue
        text = path.read_text()
        for line_no, line in enumerate(text.splitlines(), start=1):
            if "decode_b64_strict" in line:
                continue  # routed through the helper
            if not _B64_CALL.search(line):
                continue
            # The call may span lines; join forward until the parens balance.
            snippet = _balanced_call(text, line_no)
            if "validate=True" not in snippet:
                offenders.append(f"{rel}:{line_no}: {line.strip()}")
    assert not offenders, (
        "these base64 decodes are tolerant and can behave differently across "
        f"CPython versions; route them through decode_b64_strict or pass "
        f"validate=True: {offenders}"
    )


def _balanced_call(text: str, start_line: int) -> str:
    """Return the text of the call starting at ``start_line``, parens balanced."""
    lines = text.splitlines()
    chunk: list[str] = []
    depth = 0
    for line in lines[start_line - 1 :]:
        chunk.append(line)
        depth += line.count("(") - line.count(")")
        if depth <= 0 and chunk:
            break
    return "\n".join(chunk)


def test_the_one_strict_decode_helper_exists() -> None:
    src = (REPO_ROOT / STRICT_HELPER_MODULE).read_text()
    assert "def decode_b64_strict(" in src, "the single strict base64 entry point is gone"
    assert "validate=True" in src, "the helper must validate strictly"


# --- anchor pinning -----------------------------------------------------------


def _anchor_pair() -> dict[str, Path]:
    return {
        "peer": REPO_ROOT / "peer-node" / "scripts" / "sparknet-wireguard-anchor.sh",
        "master": REPO_ROOT / "master-node" / "scripts" / "sparknet-master-wireguard-anchor.sh",
    }


def test_both_anchors_pin_both_config_copies() -> None:
    """The Master anchor pins its overlay config, and the docs must agree.

    A Master is a peer that won an election; it runs the same overlay and the same
    anchor discipline. Pinning only the state-dir copy (or only ``/etc``) would
    leave the other as a writable path to the live overlay.
    """
    for role, path in _anchor_pair().items():
        text = path.read_text()
        assert 'chattr +i "$CONF"' in text, f"{role} anchor must pin the state-dir config"
        assert 'chattr +i "$ETC_CONF"' in text, f"{role} anchor must pin the /etc copy"


def test_master_anchor_documents_that_it_pins() -> None:
    """The Master anchor's own header must not claim it skips pinning.

    The code pins both copies; a comment that says the Master is exempt would make
    the next reader "fix" the code to match a stale note.
    """
    text = (REPO_ROOT / "master-node" / "scripts" / "sparknet-master-wireguard-anchor.sh").read_text()
    assert "pin" in text.lower(), "the Master anchor header must state the pinning behaviour"
    assert "skip" not in text.lower() or "does not skip" in text.lower(), (
        "the Master anchor must not claim it skips pinning while the code pins"
    )


def test_anchors_require_the_interface_instead_of_defaulting() -> None:
    """A default interface is a silent wrong-path risk.

    ``${SPARKNET_WG_INTERFACE:-wg0}`` would target ``wg0`` when the env file is
    missing, quietly creating a second overlay interface rather than failing. The
    interface must be explicit, sourced from the deployment env.
    """
    for role, path in _anchor_pair().items():
        text = path.read_text()
        assert "SPARKNET_WG_INTERFACE:-" not in text, (
            f"{role} anchor still defaults SPARKNET_WG_INTERFACE; a missing env file "
            f"must fail, not silently target another interface"
        )
