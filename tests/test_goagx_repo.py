"""The goagx distribution: a generated deployment repo, pinned here.

reallife-spark/goagx is EXPORTED from this fabric (PLAN Step 62) — the
monorepo layout a node needs plus the goagx/ image surface, so every
sparknet-node-setup.sh --platform agx code path runs unmodified from a clone.
The repo is never hand-edited; `scripts/sparknet-goagx-publish.sh` owns its
contents. This suite pins the export surface against the things that consume
it (the dockerfile's COPY sources, the compose build, the goSpark pin), the
generated manifest, and the verify contract the published workflow re-runs.
"""

import json
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBLISH = REPO_ROOT / "scripts" / "sparknet-goagx-publish.sh"
BOOTSTRAP = REPO_ROOT / "goagx" / "bootstrap-agx.sh"
PIN = REPO_ROOT / "goagx" / "GOSPARK_PIN"
AGX_DOCKER = REPO_ROOT / "goagx" / "sparknet.agx.docker"
AGX_COMPOSE = REPO_ROOT / "goagx" / "sparknet.agx.compose.yml"
SETUP = REPO_ROOT / "sparknet-node-setup.sh"
KEYS_CHECK = REPO_ROOT / "scripts" / "sparknet-keys-check.sh"
TEMPLATES = REPO_ROOT / "goagx" / "publish-templates"

#: The export surface, mirrored from scripts/sparknet-goagx-publish.sh and
#: asserted against it below — a change to either side must touch both.
SUBTREES = [
    "peer-node",
    "master-node",
    "contracts",
    "shared",
    "scripts",
    ".opencode/skills",
    ".opencode/agents",
    "goagx",
]
ROOT_FILES = [
    "spark-entrypoint.sh",
    "spark-precontext.py",
    "spark.compose.cpu.yml",
    "sparknet-node-setup.sh",
    "bootstrap-agx.sh",
    "spark.docker",
    "spark.compose.yml",
    ".env.example",
    ".dockerignore",
    ".gitignore",
    "opencode.json",
    "requirements.txt",
]
GENERATED = ["README.md", "VERSIONS.json", "SHA256SUMS", ".github/workflows/verify.yml"]


def _pin(key: str) -> str:
    for line in PIN.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def _dockerfile_arg(name: str) -> str:
    m = re.search(rf"^ARG {re.escape(name)}=(.*)$", AGX_DOCKER.read_text(), re.M)
    return m.group(1).strip().strip('"') if m else ""


@pytest.fixture(scope="module")
def staged(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A freshly staged distribution — the integration surface under test."""
    out = tmp_path_factory.mktemp("goagx-stage")
    proc = subprocess.run(
        [str(PUBLISH), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, f"--out failed:\n{proc.stdout}{proc.stderr}"
    return out


# --- pins ---------------------------------------------------------------------


def test_gospark_pin_is_a_full_sha() -> None:
    assert re.fullmatch(r"[0-9a-f]{40}", _pin("GOSPARK_SHA")), "GOSPARK_SHA must be a full 40-hex commit"
    assert _pin("GOSPARK_REPO").startswith("https://"), "GOSPARK_REPO must be a URL"


def test_bootstrap_reads_the_pin_and_hands_over_to_setup() -> None:
    text = BOOTSTRAP.read_text()
    assert "GOSPARK_PIN" in text
    assert "--platform agx" in text
    assert "build build-gpu" in text
    assert "sparknet-node-setup.sh" in text
    assert "/etc/nv_tegra_release" in text, "the bootstrap must preflight L4T r35"
    assert "MIN_SWAP_KB" in text, "the source-build swap floor must stay enforced"


def test_make_targets_exist() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert "goagx-publish:" in makefile
    assert "goagx-drift-check:" in makefile
    assert "goagx-drift-check" in makefile.split("drift-check:", 1)[1], (
        "the umbrella drift-check must include the goagx leg (self-skipping offline)"
    )


def test_publish_script_mirrors_the_declared_surface() -> None:
    text = PUBLISH.read_text()
    subtrees_block = re.search(r"^SUBTREES=\(([^)]*)\)", text, re.M)
    files_block = re.search(r"^ROOT_FILES=\(([^)]*)\)", text, re.M)
    assert subtrees_block and files_block
    for item in SUBTREES:
        assert item in subtrees_block.group(1), f"{item} missing from SUBTREES"
    for item in ROOT_FILES:
        assert item in files_block.group(1), f"{item} missing from ROOT_FILES"


def test_dockerfile_context_sources_are_exported() -> None:
    """Every build-context file the image COPYs must ride the export.

    The staged peer bundle is the one exception: it is DERIVED state the
    device builds (`make -C peer-node dist`) before the image build, never
    shipped in the repo.
    """
    bundle_default = "peer-node/container/context/sparknet-peer.tar.gz"
    for line in AGX_DOCKER.read_text().splitlines():
        m = re.match(r"^COPY\s+(?!--from)(.+)$", line.strip())
        if not m:
            continue
        tokens = m.group(1).split()
        for src in tokens[:-1]:  # last token is the destination
            if src == bundle_default or src.startswith("${"):
                continue
            rel = src.lstrip("./")
            assert rel in ROOT_FILES or any(rel.startswith(f"{s}/") for s in SUBTREES), (
                f"dockerfile COPYs {rel}, which the export does not carry"
            )


def test_compose_builds_against_the_exported_surface() -> None:
    text = AGX_COMPOSE.read_text()
    assert "dockerfile: goagx/sparknet.agx.docker" in text
    assert "context: .." in text, "the image build context is the repo root"


def test_key_check_patterns_match_the_fabric() -> None:
    """The staged-tree key scan must use the fabric's exact PEM regex.

    The character class is what keeps the check from matching the detection
    strings inside the checker scripts themselves (a naive `BEGIN .*PRIVATE
    KEY` grep fails exactly there).
    """
    fabric = KEYS_CHECK.read_text()
    publish = PUBLISH.read_text()
    m = re.search(r"'(-----BEGIN \[A-Z \]\*PRIVATE KEY-----)'", fabric)
    assert m, "sparknet-keys-check.sh no longer carries the anchored PEM regex"
    assert m.group(1) in publish, "the publish verify must reuse the fabric's PEM regex"


# --- staged distribution ------------------------------------------------------


def test_staged_layout_is_complete(staged: Path) -> None:
    for rel in [*SUBTREES, *ROOT_FILES, *GENERATED]:
        assert (staged / rel).exists(), f"staged tree is missing {rel}"
    assert (staged / "goagx" / "sparknet.agx.docker").is_file()
    assert (staged / "goagx" / "bootstrap-agx.sh").is_file()
    assert (staged / "bootstrap-agx.sh").is_symlink(), "the root entry is a shim symlink"


def test_staged_tree_excludes_local_state(staged: Path) -> None:
    assert not (staged / ".env").exists(), ".env is machine-local and must never ship"
    assert not (staged / "peer-node" / ".state").exists()
    assert not (staged / "peer-node" / "container" / "context").exists(), (
        "the staged bundle tarball is derived state, rebuilt on the device"
    )


def test_staged_manifest_records_every_pin(staged: Path) -> None:
    manifest = json.loads((staged / "VERSIONS.json").read_text())
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert manifest["name"] == "goagx"
    assert manifest["sparknet_sha"] == head
    assert manifest["gospark_sha"] == _pin("GOSPARK_SHA")
    assert manifest["gospark_repo"] == _pin("GOSPARK_REPO")
    assert manifest["vllm_git_ref"] == _dockerfile_arg("VLLM_GIT_REF")
    assert manifest["l4t_base"] == _dockerfile_arg("L4T_BASE")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", manifest["published"])


def test_staged_readme_is_rendered(staged: Path) -> None:
    readme = (staged / "README.md").read_text()
    assert "{{" not in readme, "template placeholders must all be substituted"
    assert _pin("GOSPARK_SHA") in readme
    assert "do not edit" in readme.lower()


def test_staged_sha256sums_verifies(staged: Path) -> None:
    proc = subprocess.run(
        ["sha256sum", "-c", "SHA256SUMS"],
        cwd=staged,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout


def test_staged_entry_scripts_answer_help(staged: Path) -> None:
    for rel in ("bootstrap-agx.sh", "sparknet-node-setup.sh", "scripts/sparknet-goagx-publish.sh"):
        proc = subprocess.run(
            ["bash", str(staged / rel), "--help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        assert proc.returncode == 0, f"{rel} --help exited {proc.returncode}"
        assert (proc.stdout + proc.stderr).strip(), f"{rel} --help printed nothing"


def test_staged_verify_mode_passes(staged: Path) -> None:
    proc = subprocess.run(
        [str(PUBLISH), "--verify", str(staged)],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    assert proc.returncode == 0, f"verify failed:\n{proc.stdout}{proc.stderr}"


def test_staged_publish_is_self_verifying(staged: Path) -> None:
    """The published repo carries its own verify entry — the workflow's command."""
    workflow = (staged / ".github" / "workflows" / "verify.yml").read_text()
    assert "scripts/sparknet-goagx-publish.sh --verify ." in workflow
    assert re.search(r"actions/checkout@[0-9a-f]{40}", workflow), "actions must be SHA-pinned"


# --- templates ----------------------------------------------------------------


def test_readme_template_carries_every_placeholder() -> None:
    text = (TEMPLATES / "README.md.tmpl").read_text()
    for key in ("SPARKNET_SHA", "GOSPARK_SHA", "GOSPARK_REPO", "PUBLISHED", "VLLM_REF", "L4T_BASE"):
        assert f"{{{{{key}}}}}" in text, f"README template is missing {{{{{key}}}}}"


def test_from_git_export_matches_the_ref(tmp_path: Path) -> None:
    committed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "cat-file", "-e", "HEAD:goagx/bootstrap-agx.sh"],
        capture_output=True,
        check=False,
    )
    if committed.returncode != 0:
        pytest.skip("publish surface not yet committed — release-grade export starts at the first commit")
    head = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    out = tmp_path / "from-git"
    proc = subprocess.run(
        [str(PUBLISH), "--out", str(out), "--from-git", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    assert proc.returncode == 0, f"--from-git HEAD failed:\n{proc.stdout}{proc.stderr}"
    manifest = json.loads((out / "VERSIONS.json").read_text())
    assert manifest["sparknet_sha"] == head
    assert manifest["sparknet_from_git"] == "HEAD"
