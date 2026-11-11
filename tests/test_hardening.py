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

import pytest

pytestmark = pytest.mark.unit


REPO_ROOT = Path(__file__).resolve().parent.parent

SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "dist",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    ".opencode",
    # A local goSpark checkout is a separate repository, not fabric deployment config.
    "gospark",
    "peer-node",
    "master-node",
    "goagx",
}

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


# --- 3. rolling image tags -----------------------------------------------------

# A tag that names a moving target. Pulling one twice can yield two different
# filesystems, which is the opposite of what a node image exists to guarantee.
_ROLLING_TAGS = {"latest", "main", "master", "dev", "stable", "edge", "nightly"}

_IMAGE_LINE = re.compile(r"^\s*image:\s*(?P<image>\S+)\s*$", re.MULTILINE)
_TAG_DEFAULT = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*:-(?P<default>[^}]+)\}$")

# Built here rather than pulled, so their tag is whatever this build stamped.
# Still required to be overridable, so a deployment can pin what it ships.
_LOCAL_BUILD_IMAGES = {"sparknet-agx-node", "sparknet-spark-node"}

# Captured source material: a transcript quoting someone else's compose is a
# record of what was run, not a declaration of what this fabric deploys.
_IMMUTABLE_SOURCES = ("03_Sources", "_raw")


def _compose_files() -> list[Path]:
    roots = [
        REPO_ROOT,
        REPO_ROOT / "peer-node",
        REPO_ROOT / "master-node",
        REPO_ROOT / "goagx" / "goagx",
    ]
    out: list[Path] = []
    for base in roots:
        for path in base.rglob("*.y*ml"):
            local_skip = SKIP_DIRS - {"gospark", "peer-node", "master-node", "goagx"}
            if not path.is_file() or local_skip & set(path.parts):
                continue
            if base == REPO_ROOT and {"gospark", "peer-node", "master-node", "goagx"} & set(path.parts):
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            if any(part in rel.split("/") for part in _IMMUTABLE_SOURCES):
                continue
            if _IMAGE_LINE.search(path.read_text(encoding="utf-8", errors="replace")):
                out.append(path)
    return sorted(set(out))


def _effective_tag(image: str) -> str | None:
    """The tag an image reference resolves to, or None when it is digest-pinned.

    An overridable ``${VAR:-default}`` resolves to its default, because that is
    what a deployment which sets nothing actually pulls. The split is on the
    *first* colon of the last path segment: splitting on the last one lands
    inside the ``:-`` of an interpolation and silently yields garbage, which
    once made this resolver return ``'-v0.12.2}'`` — never a rolling tag, so the
    sweep below passed while proving nothing.
    """
    if "@sha256:" in image:
        return None
    ref = image.rsplit("/", 1)[-1]
    _name, sep, tag = ref.partition(":")
    if not sep or not tag:
        return "latest"  # an untagged reference *is* :latest
    overridable = _TAG_DEFAULT.match(tag)
    return overridable.group("default") if overridable else tag


def test_the_tag_resolver_reads_an_overridable_default() -> None:
    """Pin the resolver, because a resolver that returns junk fails open.

    Every branch the sweep depends on, including the two that a naive
    last-colon split gets wrong.
    """
    cases = {
        "ghcr.io/open-webui/open-webui:main": "main",
        "alpine:latest": "latest",
        "alpine": "latest",
        "alpine:3.20": "3.20",
        "ghcr.io/open-webui/open-webui:${WEBUI_TAG:-v0.12.2}": "v0.12.2",
        "ghcr.io/open-webui/open-webui:${WEBUI_TAG:-latest}": "latest",
        "nats:${NATS_IMAGE_TAG:-2.14.2-alpine}": "2.14.2-alpine",
        "sparknet-spark-node:${SPARKNET_IMAGE_TAG:-dev}": "dev",
        "localhost:5000/team/img:1.2.3": "1.2.3",
        "foo/bar@sha256:deadbeef": None,
    }
    for image, expected in cases.items():
        assert _effective_tag(image) == expected, f"{image} resolved to {_effective_tag(image)!r}"
    # The two that must be *caught*, not merely parsed.
    assert _effective_tag("ghcr.io/open-webui/open-webui:${WEBUI_TAG:-latest}") in _ROLLING_TAGS
    assert _effective_tag("ghcr.io/open-webui/open-webui:main") in _ROLLING_TAGS


def test_no_tracked_compose_deploys_a_rolling_image_tag() -> None:
    """Every image this fabric deploys names a fixed release.

    Two composes shipped ``open-webui:main`` and three shipped ``alpine:latest``
    while ``sparknet-node-setup.sh`` carried the rule in a comment ("WEBUI_TAG is
    a stable release, never main/latest") and a test enforced it for the two
    *node-stack* composes only. A rule one test applies to a hand-picked subset
    is a rule the other files can break silently, so this sweeps the tree instead
    of naming files.

    A rolling tag is not a style preference here: the node image is the
    reproducibility boundary, and ``:main`` means the thing that ran yesterday is
    not provably the thing that runs after a redeploy. Captured material under
    ``03_Sources``/``_raw`` is exempt because it is immutable evidence, not
    deployment config.
    """
    seen: list[str] = []
    for path in _compose_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        for match in _IMAGE_LINE.finditer(path.read_text(encoding="utf-8", errors="replace")):
            image = match.group("image")
            name = image.rsplit("/", 1)[-1].split(":", 1)[0]
            tag = _effective_tag(image)
            if tag is None:
                seen.append(f"{rel}: {image} (digest-pinned)")
                continue
            if name in _LOCAL_BUILD_IMAGES:
                assert "${" in image, (
                    f"{rel}: {image} is built here, so its tag must stay overridable "
                    f"(${{SPARKNET_IMAGE_TAG:-...}}) for a deployment to pin what it ships"
                )
                seen.append(f"{rel}: {image} (local build)")
                continue
            assert tag not in _ROLLING_TAGS, (
                f"{rel}: {image} resolves to the rolling tag {tag!r}; pin a release "
                f"(the repo's convention is an overridable default, e.g. ${{WEBUI_TAG:-v0.12.2}})"
            )
            seen.append(f"{rel}: {image}")

    # The sweep must actually sweep: a glob that silently matched nothing would
    # pass forever. Four composes carry the webui image alone.
    assert len(seen) >= 10, f"the compose sweep found only {len(seen)} images; the glob is broken"
    assert any("open-webui" in entry for entry in seen), "the sweep no longer sees the webui image"
    assert sum("open-webui" in entry for entry in seen) == 4, (
        "expected the four composes that deploy Open WebUI; a new one needs the same pin"
    )
