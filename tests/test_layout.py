"""Repository layout must match what the documentation claims.

Three ways this repository rots, all of them invisible in a normal test run:

1. **Phantom directories.** The split emptied `agents/`, `audit/`, `blockchain/`,
   `configs/`, `docs/`, `manifests/`, `plans/` and `systemd/` at the root but
   could not delete them. Git cannot track an empty directory, so they existed in
   one working tree and would have vanished on a fresh clone — two different
   repositories depending on when you looked.

2. **Dangling references.** Pages that moved into `peer-node/plans/` during the
   split kept pointing at the pre-split absolute path. A link that resolves in
   nobody's checkout is worse than a missing link, because it looks deliberate.

3. **Hard-coded absolute paths.** The whole design rests on the tree being
   relocatable — `make bundle-verify` extracts a bundle to a different directory
   on purpose. One absolute path in a live surface undoes that quietly.

Provenance is exempt: captured reference material and superseded plans may
legitimately record what was true, and what it was called, at the time.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Top-level entries the fabric is documented to have. Anything else at the root
# is either a phantomed leftover or undocumented clutter.
EXPECTED_TOP_LEVEL = {
    # the wiki category layout
    "concepts",
    "entities",
    "skills",
    "references",
    "synthesis",
    "journal",
    "projects",
    "sessions",
    "_raw",
    "_staging",
    "_archives",
    # the fabric itself
    "contracts",
    "shared",
    "peer-node",
    "master-node",
    "scripts",
    "tests",
    ".opencode",
    # project files
    "AGENTS.md",
    "MEMORY.md",
    "MISSION.md",
    "PLAN.md",
    "README.md",
    "log.md",
    "Makefile",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    ".env.example",
    ".gitignore",
    "opencode.json",
    ".vault-config",
    # the device entry for the standalone goagx distribution (fabric PLAN
    # Step 62): a shim symlink to goagx/bootstrap-agx.sh, so a clone of
    # reallife-spark/goagx has ./bootstrap-agx.sh at the top level
    "bootstrap-agx.sh",
    # the release surface (fabric PLAN Step 41): VERSION is the single source of
    # truth for the fabric version; sbom/ holds the generated CycloneDX SBOM.
    "VERSION",
    "sbom",
    # shellcheck options for the whole tree, read from the repo root by
    # `make shellcheck` (fabric PLAN Step 37, track A)
    ".shellcheckrc",
    # the node image build context is the repo root, so what the image may
    # receive is governed by a tracked .dockerignore (peer PLAN Step 2/Step 9)
    ".dockerignore",
    # design proposals that deliberately sit at the fabric root, NOT in
    # contracts/ (their status says so; see Step 17)
    "MCP_A2A_DESIGN.md",
    "COMPUTE_CAPABILITY_DESIGN.md",
    "CLUSTER_INFERENCE_DESIGN.md",
    "CLUSTER_JOB_REALIZATION_DESIGN.md",
    "PER_USER_VAULTS_DESIGN.md",
    "ADMIN_FEDERATION_DESIGN.md",
    "REFLEX_DECISION_DESIGN.md",
    "RFI_REQUEST_DESIGN.md",
    "MASTER_OBSERVABILITY_DESIGN.md",
    # the DGX Spark node image surface: the image Dockerfile, the one dispatcher
    # every service runs, the compose orchestration, the precontext baker, and
    # the host bring-up script. They sit at the fabric root because the image
    # build context IS the root (BuildKit named context gospark is separate).
    "spark.docker",
    "spark-entrypoint.sh",
    "spark.compose.yml",
    "spark.compose.cpu.yml",
    "spark-precontext.py",
    "sparknet-node-setup.sh",
    # the AGX Xavier twin of the node surface: image + compose + audio shim +
    # README, retargeted from GB10 to sm_72 with the same service contract.
    "goagx",
    # the L4T/r35 build-time patches for the AGX image. They sit at the root
    # because the image build context IS the root: the Dockerfile COPYs each
    # one in and gates it (torch.distributed single-rank compat, the
    # model_loader torch.device fix, the xformers GQA prefill fix).
    "torch-dist-l4t-compat.py",
    "spark-vllm-l4t-patch.py",
    "spark-vllm-xformers-gqa-patch.py",
    # per-clone hooks (activated by `make hooks`) — pre-commit runs keys-check
    ".githooks",
    # curated navigation + the daily-update cache. index.md is hand-maintained,
    # not generated, so deleting it loses real content.
    "index.md",
    "hot.md",
    # the standing convention page (fabric PLAN Step 46), derived from the
    # dsx/EleutherAI practice in references/nvidia-dsx-standard-practice.md
    "STYLE_GUIDE.md",
    # the governance surface (fabric PLAN Step 47): how to contribute, how to
    # report a vulnerability, who owns what, the agent-facing index, the
    # changelog, and GitHub's templates under .github/. Modeled on the dsx
    # repos' community files (same inventory reference).
    "CONTRIBUTING.md",
    "SECURITY.md",
    "CODEOWNERS",
    "llms.txt",
    "CHANGELOG.md",
    # the developer-facing manual for the whole fabric (fabric PLAN Step 63).
    # It is the master manual: the peer/master role manuals live in their own
    # subtrees and are published at the roots of sparknet-peer and
    # sparknet-master; the AGX manual lives in goagx/; the Go plane's manual
    # lives in the goSpark repository. This one is also published at the root
    # of the goagx distribution, so its links must resolve in BOTH trees.
    "USER_MANUAL.md",
    ".github",
}

# Machine-local or generated: never tracked, so never part of the design.
# `__pycache__` appears at the root whenever a test imports a root-level module
# (spark-precontext.py is one: the image build context is the root).
UNTRACKED_TOP_LEVEL = {
    ".venv",
    ".git",
    ".state",
    ".cache",
    "dist",
    ".env",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "__pycache__",
    # The editor's own config dir, created on first open of this tree as a vault.
    # It is machine-local state (the volatile files are gitignored, the rest is
    # never tracked), not part of the fabric's design.
    ".obsidian",
}

# Files that record what one machine looked like, rather than describing the
# system. A captured environment profile legitimately contains absolute host
# paths — that is what makes it a capture. Each entry must be justified here, and
# `test_exempted_capture_is_still_generated` proves it is regenerated on a real
# node rather than being a snapshot that quietly rots.
CAPTURED_ARTIFACTS = {
    # Generated by scripts/sparknet-identity-capture.sh on every node; the
    # tracked copy is a sample. It is also load-bearing: critical-manifest.json
    # declares /etc/sparknet/user-env-manifest.json as generated from it, so
    # untracking it would leave a protected /etc path without provenance.
    "peer-node/manifests/user-env-manifest.json",
}

VAULT_CATEGORY_DIRS = [
    "concepts",
    "entities",
    "skills",
    "references",
    "synthesis",
    "journal",
    "projects",
    "sessions",
    "_raw",
    "_staging",
    "_archives",
]

# Directories whose contents are history rather than current specification.
# The legacy names are the fabric root's; the numbered ones are the role
# subvaults' equivalents under the PARA layout (`peer-node/`), so a capture
# that legitimately records a host path stays exempt after the move.
PROVENANCE_DIRS = {
    "references",
    "plans",
    "sessions",
    "journal",
    "_raw",
    "_archives",
    "01_Inbox",
    "02_Daily",
    "03_Sources",
    "07_Archives",
}

SCAN_SUFFIXES = {".md", ".py", ".sh", ".json", ".template", ".conf", ".env.example"}
SKIP_DIR_PARTS = {"__pycache__", ".git", ".venv", "dist", "node_modules", ".pytest_cache", ".ruff_cache", ".opencode"}

# Generated committed artifacts whose body is a verbatim copy of a vendored,
# already-excluded source (.opencode/skills/llm-wiki/SKILL.md, produced by
# peer-node/scripts/sparknet-masterspike.py). Link-scanning the copy would only
# re-litigate the vendor's example paths; `make model-verify` proves the copy
# bytes are identical, which is the stronger guarantee. If the generator is
# changed so this artifact stops being a verbatim copy, remove it from here.
EXCLUDED_GENERATED = frozenset(
    {
        "peer-node/manifests/masterspike/vllm-system-prompt.md",
    }
)


def markdown_files() -> list[Path]:
    out = []
    for path in REPO_ROOT.rglob("*.md"):
        if SKIP_DIR_PARTS & set(path.parts):
            continue
        if path.parts[len(REPO_ROOT.parts) - 1] == ".opencode":
            continue
        if str(path.relative_to(REPO_ROOT)) in EXCLUDED_GENERATED:
            continue
        out.append(path)
    return out


def current_surfaces() -> list[Path]:
    """Files that describe the system now, as opposed to recording its history.

    Test suites are excluded on purpose. A hard-coded path in a test is the
    *subject* under test — asserting that the string "/mnt/knowledge/sparknet"
    is absent from some output is the whole point of that test. Including them
    would mean the scan flagged its own detectors and had to be weakened.
    """
    return [
        p
        for p in REPO_ROOT.rglob("*")
        if p.is_file()
        and not SKIP_DIR_PARTS & set(p.parts)
        and p.suffix in SCAN_SUFFIXES
        and "tests" not in p.relative_to(REPO_ROOT).parts
        and p.name != "log.md"
        and str(p.relative_to(REPO_ROOT)) not in CAPTURED_ARTIFACTS
        and not PROVENANCE_DIRS & set(p.relative_to(REPO_ROOT).parts)
    ]


# --- 1. no phantom directories -------------------------------------------------


def test_no_undocumented_top_level_entries():
    """Catches the emptied leftovers the split could not delete."""
    actual = {p.name for p in REPO_ROOT.iterdir() if p.name not in UNTRACKED_TOP_LEVEL}
    undocumented = sorted(actual - EXPECTED_TOP_LEVEL)
    assert not undocumented, (
        f"top-level entries exist that nothing documents: {undocumented}. "
        f"If these are phantomed leftovers from the split, delete them — git "
        f"cannot track an empty directory, so they exist in one working tree only."
    )


@pytest.mark.parametrize("name", VAULT_CATEGORY_DIRS)
def test_vault_category_dir_survives_a_fresh_clone(name: str):
    """`env-init` writes a .gitkeep so a clone is already a usable vault.

    Without it the directory exists in this working tree and not in anyone
    else's, which is exactly the phantom failure in its quietest form.
    """
    path = REPO_ROOT / name
    assert path.is_dir(), f"the charter documents {name}/ but it does not exist"
    assert (path / ".gitkeep").is_file(), f"{name}/ has no .gitkeep, so git will not carry it to a fresh clone"


def test_no_empty_directory_outside_the_vault_categories():
    """An empty dir is untracked by git, so it cannot be part of the design."""
    empties = [
        p
        for p in REPO_ROOT.rglob("*")
        if p.is_dir()
        and not any(
            part
            in {
                ".git",
                ".venv",
                ".state",
                ".cache",
                "dist",
                "node_modules",
                "__pycache__",
                ".opencode",
                ".obsidian",
            }
            for part in p.parts
        )
        and not any(p for p in p.iterdir())
    ]
    assert not empties, (
        f"empty directories, which git will not carry: {[str(p.relative_to(REPO_ROOT)) for p in empties]}"
    )


# --- 2. local markdown links resolve -------------------------------------------

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)")
# wiki links ([[Page]]) are resolved by the wiki suite, not the filesystem.
WIKI_LINK = re.compile(r"\[\[[^\]]*\]\]")


@pytest.mark.parametrize("page", markdown_files(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_local_markdown_links_resolve(page: Path):
    """A relative link to a file that is not there is a silent defect."""
    text = page.read_text(errors="replace")
    without_wikilinks = WIKI_LINK.sub("", text)
    missing = []
    for target in MD_LINK.findall(without_wikilinks):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        # Drop an anchor / query part.
        bare = target.split("#", 1)[0]
        if not bare:
            continue
        # Not every (x) in prose is a link — LaTeX and regex fragments appear as
        # well. Only check something shaped like a path to a file.
        looks_like_path = "/" in bare or re.search(r"\.\w+$", bare)
        if not looks_like_path or "\\" in bare:
            continue
        if bare.startswith("/"):
            # An absolute in-repo link would break on relocation; out-of-tree
            # absolute paths are handled by the relocation test.
            bare = bare.lstrip("/")
            resolved = REPO_ROOT / bare
        else:
            resolved = (page.parent / bare).resolve()
        if not resolved.exists():
            missing.append(target)
    assert not missing, f"{page.relative_to(REPO_ROOT)} links to nothing: {missing}"


# --- 3. no hard-coded host paths in current surfaces ---------------------------


def test_no_hard_coded_vault_path_in_current_surfaces():
    """The tree must be relocatable; bundle-verify proves it by extracting it."""
    offenders = []
    for path in current_surfaces():
        try:
            text = path.read_text()
        except (UnicodeDecodeError, OSError):
            continue
        for match in re.finditer(r"/mnt/knowledge/sparknet\S*", text):
            line = text[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{line}")
    assert not offenders, (
        f"these current files hard-code the development checkout path, so they "
        f"break the moment the tree moves: {offenders}"
    )


def test_env_example_uses_placeholders_not_real_paths():
    """`.env` may hold real paths; the tracked template must not."""
    for example in sorted(REPO_ROOT.rglob(".env.example")):
        if SKIP_DIR_PARTS & set(example.parts):
            continue
        text = example.read_text()
        assert not re.search(r"/mnt/knowledge/", text), (
            f"{example.relative_to(REPO_ROOT)} hard-codes a host path; a fresh checkout writes it verbatim into .env"
        )


def test_env_example_templates_share_one_key_set():
    """Every `.env.example` must expose the same knobs.

    `sparknet-env-init.sh` regenerates a vault's `.env` from its own example,
    and the wiki skills read one vocabulary (`VAULT_PATH`, `VAULT_CATEGORIES`,
    `WIKI_STAGED_WRITES` …) in every vault. If a role's template gains or loses
    a key, that role silently loses a knob the skills expect — a drift nothing
    else catches, because the *values* differ by design (each template names its
    own vault). This is the `env-changes` gate for a tree that regenerates its
    env rather than migrating it.
    """

    def keys(path):
        return {
            m.group(1)
            for line in path.read_text().splitlines()
            if (m := re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*=", line))
        }

    examples = sorted(p for p in REPO_ROOT.rglob(".env.example") if not (SKIP_DIR_PARTS & set(p.parts)))
    assert len(examples) >= 3, f"expected at least the root and both roles' templates, found: {examples}"
    reference = examples[0]
    ref_keys = keys(reference)
    for path in examples[1:]:
        assert keys(path) == ref_keys, (
            f"{path.relative_to(REPO_ROOT)} and "
            f"{reference.relative_to(REPO_ROOT)} disagree on env keys: "
            f"{sorted(keys(path) ^ ref_keys)}"
        )


# --- 4. the contract is where the charter says it is ---------------------------


def test_contract_and_shared_are_present_and_populated():
    for name in (
        "overlay.json",
        "capabilities.json",
        "identity-schema.json",
        "ports.json",
        "guard-protocol.md",
        "share-protocol.md",
        "consensus-protocol.md",
        "README.md",
    ):
        path = REPO_ROOT / "contracts" / name
        assert path.is_file(), f"contracts/{name} is missing"
        assert path.stat().st_size > 0, f"contracts/{name} is empty"
    shared = REPO_ROOT / "shared" / "sparknet-authz.py"
    assert shared.is_file() and shared.stat().st_size > 0


def test_the_fabric_entry_point_wires_the_roles():
    """`make test-all` must reach every suite, or "all" means something less."""
    makefile = (REPO_ROOT / "Makefile").read_text()
    for target in ("test-all", "contract-test", "wiki-verify", "bundle", "bundle-verify", "env-init", "validate"):
        assert re.search(rf"^{target}:", makefile, re.M), f"the fabric Makefile has no {target} target"
    for role in ("peer-node", "master-node"):
        assert f"-C {role}" in makefile, f"the fabric Makefile never delegates to {role}"
    assert (REPO_ROOT / role / "Makefile").is_file()


def test_exempted_capture_is_still_generated():
    """An exemption must not become a stale snapshot.

    `user-env-manifest.json` is allowed to hold absolute host paths only because
    a node regenerates it. If the generator disappeared, the tracked copy would
    quietly become the source of truth for a machine nobody has — which is worse
    than the hard-coded path it was exempted for.
    """
    capture = REPO_ROOT / "peer-node" / "scripts" / "sparknet-identity-capture.sh"
    assert capture.is_file(), (
        "the identity capture script is gone, so the exempted capture is now a stale snapshot rather than a sample"
    )
    text = capture.read_text()
    for artifact in CAPTURED_ARTIFACTS:
        assert Path(artifact).name in text, (
            f"{artifact} is exempted from the relocation scan, but nothing generates it any more"
        )
