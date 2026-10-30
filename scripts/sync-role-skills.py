#!/usr/bin/env python3
"""Build the role-local skill catalogs for peer-node and master-node.

The base suite at `.opencode/skills/` is shared and stays untouched. This tool
builds the role-local additions:

    peer-node/.opencode/skills/     expanded engineering, sellable
    master-node/.opencode/skills/   every sellable unique skill

The master catalog is deliberately sellable. A skill is copied only when its
license is on the allowlist, its name is not in REMOVED_NAMES, and its source is
not a restricted family. The manifest records the license and provenance for
every skill so a bundle can be audited without mining thousands of files.

Usage:
    scripts/sync-role-skills.py --apply
    scripts/sync-role-skills.py --check
    scripts/sync-role-skills.py --apply --role peer
    scripts/sync-role-skills.py --report
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ROLE_DIRS = {
    "peer": REPO_ROOT / "peer-node" / ".opencode" / "skills",
    "master": REPO_ROOT / "master-node" / ".opencode" / "skills",
}
ROOT_SUITE = REPO_ROOT / ".opencode" / "skills"
GITHUB_ROOT = Path("/mnt/nvme/github")
FARM_ROOT = Path("/mnt/nvme/skills")
RAXXAR_ROOT = Path("/mnt/knowledge/raxxar/06_knowledge/sub-vaults")

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_FILE_BYTES = 2_000_000

REMOVED_NAMES = {
    "docx",
    "pdf",
    "pptx",
    "xlsx",
    "powerpoint",
    "kimi-docx",
    "kimi-pdf",
    "kimi-xlsx",
    "doc-coauthoring",
    "verify",
    "malware-analysis-static",
    "template",
}

OPTIONAL_NAMES = {"claude-api"}

SKIPPED_INVALID: set[str] = set()

ALLOWED_LICENSES = {
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "CC0-1.0",
    "Unlicense",
    "MIT OR Apache-2.0",
}

# Names that exist only in a local farm and have no upstream license to rely on.
LOCAL_UNKNOWN_NAMES = {
    "hid-keyboard-remote",
    "pdf-ocr-digest",
    "provision-engagement-skills",
    "multi-ai-planning",
    "planning-patterns",
    "rlspark-sourcewatch",
    "computer-user",
    "bypassing-mfa-and-otp-authentication",
    "detecting-account-takeover-attempts",
    "detecting-malicious-file-upload-attacks",
    "detecting-mfa-bypass-attempts",
    "exploiting-arbitrary-file-write-vulnerabilities",
    "exploiting-blind-css-exfiltration",
    "exploiting-command-injection-vulnerabilities",
    "exploiting-file-upload-vulnerabilities",
    "exploiting-memory-corruption-vulnerabilities",
    "exploiting-password-reset-poisoning",
    "exploiting-rce-vulnerabilities",
    "performing-crlf-injection-testing",
}

PEER_SKILLS = [
    "brainstorming",
    "writing-plans",
    "executing-plans",
    "test-driven-development",
    "systematic-debugging",
    "verification-before-completion",
    "requesting-code-review",
    "receiving-code-review",
    "dispatching-parallel-agents",
    "subagent-driven-development",
    "using-git-worktrees",
    "writing-skills",
    "python-code-style",
    "python-design-patterns",
    "python-error-handling",
    "python-testing-patterns",
    "python-type-safety",
    "python-configuration",
    "python-observability",
    "python-resilience",
    "python-resource-management",
    "python-performance-optimization",
    "python-packaging",
    "python-project-structure",
    "python-anti-patterns",
    "async-python-patterns",
    "python-background-jobs",
    "bash-defensive-patterns",
    "shellcheck-configuration",
    "bats-testing-patterns",
    "git-advanced-workflows",
    "code-reviewer",
    "debugging-wizard",
    "error-handling-patterns",
    "architecture-patterns",
    "api-design-principles",
    "architecture-decision-records",
    "changelog-automation",
    "hads",
    "auth-implementation-patterns",
    "secrets-management",
    "mtls-configuration",
    "security-requirement-extraction",
    "stride-analysis-patterns",
    "threat-mitigation-mapping",
    "prometheus-configuration",
    "grafana-dashboards",
    "slo-implementation",
    "distributed-tracing",
    "incident-runbook-templates",
    "postmortem-writing",
    "on-call-handoff-patterns",
    "deployment-pipeline-design",
    "github-actions-templates",
    "test-master",
    "monitoring-expert",
    "sre-engineer",
    "secure-code-guardian",
    "security-reviewer",
    "the-fool",
    "grill-me",
    "handoff",
    "prompt-engineer",
    "code-documenter",
    "architecture-designer",
    "api-designer",
    "cli-developer",
    "devops-engineer",
    "spark-environment-setup",
    "spark-memory-thermal-ops",
    "spark-training-gotchas",
    "vllm",
    "gguf",
    "llama-cpp",
    "huggingface-hub",
    "lm-evaluation-harness",
    "ocr-and-documents",
    "whisper",
    "pytorch-fsdp",
    "jupyter-live-kernel",
    "internal-comms",
    "go-concurrency-patterns",
    "uv-package-manager",
    "openapi-spec-generation",
    "karpathy-guidelines",
    "skill-template",
    "writing-for-agents",
    "nano-pdf",
    "file-conversion",
    "mcp-developer",
]

REPO_PRIORITY = {
    "superpowers": 10,
    "agents": 20,
    "Anthropic-Cybersecurity-Skills": 30,
    "AI-Skills-German-Law": 40,
    "hermes-agent": 50,
    "opencode-skills": 60,
    "skill": 65,
    "obsidian-wiki": 70,
    "chart-visualization-skills": 80,
    "obsidian-skills": 90,
    "skills": 100,
    "prime-agent": 110,
    "loop-engineering": 120,
    "run-ai": 130,
    "dify": 140,
    "OpenAlice": 150,
    "Shadowbroker": 160,
    "trufflehog": 170,
    "pymobiledevice3": 180,
    "openhuman": 190,
    "kimi-skills": 200,
    "german-technical-writing-skill": 210,
    "humanizer-de": 220,
    "andrej-karpathy-skills": 230,
    "ultraplan": 240,
    "DeepTutor": 250,
    "knowledge-catalog": 260,
    "raptor": 270,
    "prompts.chat": 280,
    "ai-hub-models": 290,
    "jetson-containers": 300,
    "flowsint": 310,
    "Maestro": 320,
    "vllm": 330,
    "spec-kit": 340,
    "gastown": 350,
    "PraisonAI": 360,
    "infra-controller": 370,
    "workload-map": 380,
    "opencode-obsidian": 390,
    "opencode_sidebar": 400,
    "codex": 410,
    "ALEAPP": 420,
    "iLEAPP": 430,
    "claude-code-source-build": 440,
    "malware-analysis-static": 450,
}

FAMILY_PRIORITY = {
    "opencode": 60,
    "agents": 65,
    "wiki": 70,
    "viz": 80,
    "docs": 200,
    "de": 220,
    "karpathy": 230,
    "cyber": 460,
}

REPO_SPECIAL_LICENSE = {
    "dify": "Apache-2.0-modified",
    "OpenAlice": "AGPL-3.0",
    "Shadowbroker": "AGPL-3.0",
    "trufflehog": "AGPL-3.0",
    "pymobiledevice3": "GPL-3.0",
    "openhuman": "GPL-3.0",
    "kimi-skills": "RESTRICTED",
    "german-technical-writing-skill": "CC-BY-SA-4.0",
    "humanizer-de": "CC-BY-SA-4.0",
    "claude-code-source-build": "UNKNOWN",
    "malware-analysis-static": "UNKNOWN",
    "andrej-karpathy-skills": "MIT",
    "jetson-containers": "MIT",
}

FAMILY_SPECIAL_LICENSE = {
    "docs": "RESTRICTED",
    "de": "CC-BY-SA-4.0",
}

NAME_SPECIAL_LICENSE = {
    "german-technical-writing": "CC-BY-SA-4.0",
    "humanizer-de": "CC-BY-SA-4.0",
}

REPO_ROOT_SKILLS = {
    GITHUB_ROOT / "DeepTutor",
    GITHUB_ROOT / "ultraplan",
    GITHUB_ROOT / "humanizer-de",
    GITHUB_ROOT / "malware-analysis-static",
}

EXCLUDED_PATH_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".cache",
    ".trash",
    "site-packages",
    "dist",
    "build",
}

EXCLUDED_PATH_RE = re.compile(
    r"/(test|tests|fixtures|skills-collision|goal-audit/test|references/merged)(/|$)",
    re.IGNORECASE,
)


@dataclass
class Entry:
    name: str
    path: Path
    source_repo: str
    license: str
    priority: int
    body_hash: str
    description: str = ""
    variants: list[Entry] = field(default_factory=list)

    @property
    def sellable(self) -> bool:
        return (
            self.license in ALLOWED_LICENSES and self.name not in REMOVED_NAMES and self.name not in LOCAL_UNKNOWN_NAMES
        )


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out: dict[str, str] = {}
    key = None
    for line in text[3:end].splitlines():
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s*(.*)$", line)
        if match:
            key = match.group(1)
            value = match.group(2).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            out[key] = value
        elif key and line.strip():
            out[key] += " " + line.strip()
    return out


def slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return cleaned[:MAX_NAME].strip("-")


def canonical_name(dirname: str, meta: dict[str, str]) -> str | None:
    if NAME_RE.match(dirname) and len(dirname) <= MAX_NAME:
        return dirname
    candidate = meta.get("name", "")
    if NAME_RE.match(candidate) and len(candidate) <= MAX_NAME:
        return candidate
    candidate = slug(candidate or dirname)
    if NAME_RE.match(candidate) and len(candidate) <= MAX_NAME:
        return candidate
    return None


def read_license(path: Path) -> str | None:
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING", "COPYING.md", "NOTICE"):
        candidate = path / name
        if not candidate.is_file():
            continue
        text = candidate.read_text(encoding="utf-8", errors="ignore")[:4000]
        upper = text.upper()
        if "ALL RIGHTS RESERVED" in upper or "PROPRIETARY" in upper:
            return "RESTRICTED"
        if "GNU AFFERO GENERAL PUBLIC LICENSE" in upper:
            return "AGPL-3.0"
        if "GNU GENERAL PUBLIC LICENSE" in upper:
            return "GPL-3.0"
        if "APACHE LICENSE" in upper:
            return "Apache-2.0"
        if "MIT LICENSE" in upper:
            return "MIT"
        if "BSD 2-CLAUSE" in upper:
            return "BSD-2-Clause"
        if "BSD 3-CLAUSE" in upper or "REDISTRIBUTION AND USE IN SOURCE AND BINARY FORMS" in upper:
            return "BSD-3-Clause"
        if "CC BY-SA" in upper or "CREATIVE COMMONS ATTRIBUTION-SHAREALIKE" in upper:
            return "CC-BY-SA-4.0"
        if "CC0" in upper:
            return "CC0-1.0"
    return None


def repo_license(repo: Path) -> str:
    if repo.name in REPO_SPECIAL_LICENSE:
        return REPO_SPECIAL_LICENSE[repo.name]
    license = read_license(repo)
    if license:
        return license
    if repo.name == "AI-Skills-German-Law":
        return "MIT OR Apache-2.0"
    return "UNKNOWN"


def skill_license(skill: Path, inherited: str) -> str:
    if skill.name in NAME_SPECIAL_LICENSE:
        return NAME_SPECIAL_LICENSE[skill.name]
    license = read_license(skill)
    if license:
        return license
    if skill in REPO_ROOT_SKILLS and skill.name == "malware-analysis-static":
        return "UNKNOWN"
    return inherited


def has_skill_ancestor(skill: Path, stop: Path) -> bool:
    parent = skill.parent
    while parent != stop.parent:
        if (parent / "SKILL.md").is_file():
            return True
        if parent == stop:
            break
        parent = parent.parent
    return False


def excluded_path(path: Path) -> bool:
    parts = set(path.parts)
    if parts & EXCLUDED_PATH_PARTS:
        return True
    return bool(EXCLUDED_PATH_RE.search(path.as_posix()))


def scan_github() -> list[Entry]:
    entries: list[Entry] = []
    if not GITHUB_ROOT.is_dir():
        return entries
    for index, repo in enumerate(sorted(GITHUB_ROOT.iterdir())):
        if not repo.is_dir() or repo.name.startswith("."):
            continue
        inherited = repo_license(repo)
        priority = REPO_PRIORITY.get(repo.name, 500 + index)
        for dirpath, dirnames, filenames in os.walk(repo):
            dirnames[:] = [
                name for name in dirnames if name not in EXCLUDED_PATH_PARTS and not (Path(dirpath) / name).is_symlink()
            ]
            if "SKILL.md" in filenames:
                skill = Path(dirpath)
                if excluded_path(skill) or has_skill_ancestor(skill, repo):
                    continue
                text = (skill / "SKILL.md").read_text(encoding="utf-8", errors="replace")
                meta = frontmatter(text)
                name = canonical_name(skill.name, meta)
                if not name:
                    continue
                license = skill_license(skill, inherited)
                description = meta.get("description", "")
                if not description:
                    SKIPPED_INVALID.add(name)
                    continue
                entries.append(
                    Entry(
                        name=name,
                        path=skill,
                        source_repo=repo.name,
                        license=license,
                        priority=priority,
                        body_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                        description=meta.get("description", ""),
                    )
                )
    return entries


def scan_farm() -> list[Entry]:
    entries: list[Entry] = []
    if not FARM_ROOT.is_dir():
        return entries
    upstream = {
        "opencode": GITHUB_ROOT / "opencode-skills" / "skills",
        "cyber": GITHUB_ROOT / "Anthropic-Cybersecurity-Skills" / "skills",
        "wiki": GITHUB_ROOT / "obsidian-wiki" / ".skills",
    }
    upstream_names: dict[str, set[str]] = {}
    for family, path in upstream.items():
        names: set[str] = set()
        if path.is_dir():
            for skill_md in path.rglob("SKILL.md"):
                names.add(skill_md.parent.name)
        upstream_names[family] = names
    for family_dir in sorted(FARM_ROOT.iterdir()):
        if not family_dir.is_dir():
            continue
        family = family_dir.name
        inherited = FAMILY_SPECIAL_LICENSE.get(family, "MIT")
        priority = FAMILY_PRIORITY.get(family, 600)
        for dirpath, dirnames, filenames in os.walk(family_dir):
            dirnames[:] = [
                name for name in dirnames if name not in EXCLUDED_PATH_PARTS and not (Path(dirpath) / name).is_symlink()
            ]
            if "SKILL.md" not in filenames:
                continue
            skill = Path(dirpath)
            if excluded_path(skill) or has_skill_ancestor(skill, family_dir):
                continue
            text = (skill / "SKILL.md").read_text(encoding="utf-8", errors="replace")
            meta = frontmatter(text)
            name = canonical_name(skill.name, meta)
            if not name:
                continue
            license = skill_license(skill, inherited)
            if family in upstream_names and name not in upstream_names[family]:
                license = "UNKNOWN"
            description = meta.get("description", "")
            if not description:
                SKIPPED_INVALID.add(name)
                continue
            entries.append(
                Entry(
                    name=name,
                    path=skill,
                    source_repo=f"farm:{family}",
                    license=license,
                    priority=priority,
                    body_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    description=meta.get("description", ""),
                )
            )
    return entries


def scan_raxxar() -> list[Entry]:
    entries: list[Entry] = []
    if not RAXXAR_ROOT.is_dir():
        return entries
    for vault in sorted(RAXXAR_ROOT.iterdir()):
        skills = vault / "skills"
        if not skills.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(skills):
            dirnames[:] = [name for name in dirnames if name not in EXCLUDED_PATH_PARTS]
            if "SKILL.md" not in filenames:
                continue
            skill = Path(dirpath)
            if excluded_path(skill) or has_skill_ancestor(skill, skills):
                continue
            text = (skill / "SKILL.md").read_text(encoding="utf-8", errors="replace")
            meta = frontmatter(text)
            name = canonical_name(skill.name, meta)
            if not name:
                continue
            description = meta.get("description", "")
            if not description:
                SKIPPED_INVALID.add(name)
                continue
            entries.append(
                Entry(
                    name=name,
                    path=skill,
                    source_repo=vault.name,
                    license="Apache-2.0",
                    priority=900,
                    body_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    description=meta.get("description", ""),
                )
            )
    return entries


def scan_root_suite() -> set[str]:
    if not ROOT_SUITE.is_dir():
        return set()
    return {path.parent.name for path in ROOT_SUITE.rglob("SKILL.md")}


def choose(entries: list[Entry], name: str) -> Entry | None:
    candidates = [entry for entry in entries if entry.name == name and entry.sellable]
    if not candidates:
        return None
    return min(candidates, key=lambda entry: (entry.priority, len(entry.path.as_posix())))


def all_sellable(entries: list[Entry], root_names: set[str]) -> dict[str, list[Entry]]:
    grouped: dict[str, list[Entry]] = {}
    for entry in entries:
        if not entry.sellable or entry.name in root_names:
            continue
        grouped.setdefault(entry.name, []).append(entry)
    return grouped


def copy_payload(src: Path, dest: Path, name: str) -> tuple[int, list[str]]:
    skipped: list[str] = []
    files = 0
    repo_root_skill = src in REPO_ROOT_SKILLS
    for dirpath, dirnames, filenames in os.walk(src):
        dirnames[:] = [
            entry for entry in dirnames if entry not in EXCLUDED_PATH_PARTS and not (Path(dirpath) / entry).is_symlink()
        ]
        for filename in filenames:
            source = Path(dirpath) / filename
            relative = source.relative_to(src)
            if source.is_symlink():
                skipped.append(str(relative))
                continue
            if repo_root_skill and relative != Path("SKILL.md"):
                continue
            if relative.name == "SKILL.md" and relative.parent != Path("."):
                skipped.append(f"nested:{relative}")
                continue
            if source.stat().st_size > MAX_FILE_BYTES:
                skipped.append(f"large:{relative}")
                continue
            target = dest / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            files += 1
    return files, skipped


def rewrite_name(skill_md: Path, name: str) -> None:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return
    end = text.find("\n---", 3)
    if end == -1:
        return
    block = text[3:end]
    lines = block.splitlines()
    replaced = False
    for index, line in enumerate(lines):
        if re.match(r"^name:\s*", line):
            lines[index] = f"name: {name}"
            replaced = True
            break
    if not replaced:
        lines.insert(0, f"name: {name}")
    skill_md.write_text("---" + "\n".join(lines) + text[end:], encoding="utf-8")


def truncate_description(skill_md: Path) -> bool:
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    if end == -1:
        return False
    lines = text[3:end].splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^description:\s*(.*)$", line)
        if not match:
            continue
        value = match.group(1).strip()
        continuation_end = index + 1
        if value.startswith((">", "|")):
            while continuation_end < len(lines) and lines[continuation_end][:1].isspace():
                continuation_end += 1
            full = " ".join(part.strip() for part in lines[index + 1 : continuation_end]).strip()
        else:
            full = value.strip('"').strip("'")
        if len(full) <= MAX_DESCRIPTION:
            return False
        full = full[: MAX_DESCRIPTION - 3] + "..."
        escaped = full.replace("\\", "\\\\").replace('"', '\\"')
        lines = [*lines[:index], f'description: "{escaped}"', *lines[continuation_end:]]
        skill_md.write_text("---" + "\n".join(lines) + text[end:], encoding="utf-8")
        return True
    return False


def variant_text(entry: Entry) -> str:
    source = entry.path / "SKILL.md"
    body = source.read_text(encoding="utf-8", errors="replace")
    return (
        f"# Variant of {entry.name}\n\n"
        f"Source: `{entry.path}`\n\n"
        f"Source repository: `{entry.source_repo}`\n\n"
        f"License: `{entry.license}`\n\n"
        "This file preserves an alternate body for provenance. It is not named\n"
        "`SKILL.md`, so opencode does not load it as a second skill.\n\n"
        "---\n\n" + body
    )


def portable_source(path: Path) -> str:
    """A stable, relocatable provenance label for a built skill."""
    text = path.as_posix()
    for prefix, label in (
        ("/mnt/nvme/github/", "github:"),
        ("/mnt/nvme/skills/", "farm:"),
        ("/mnt/knowledge/raxxar/", "raxxar:"),
    ):
        if text.startswith(prefix):
            return label + text[len(prefix) :]
    return "local:" + path.name


def copy_skill(entry: Entry, dest: Path) -> dict[str, object]:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    files, skipped = copy_payload(entry.path, dest, entry.name)
    rewrite_name(dest / "SKILL.md", entry.name)
    truncated = truncate_description(dest / "SKILL.md")
    variants = []
    for variant in entry.variants:
        if variant.body_hash == entry.body_hash:
            continue
        variant_dir = dest / "references" / "merged" / slug(variant.source_repo)
        variant_dir.mkdir(parents=True, exist_ok=True)
        (variant_dir / "VARIANT.md").write_text(variant_text(variant), encoding="utf-8")
        variants.append(
            {
                "source": portable_source(variant.path),
                "source_repo": variant.source_repo,
                "license": variant.license,
                "file": str((variant_dir / "VARIANT.md").relative_to(dest)),
            }
        )
    return {
        "source": portable_source(entry.path),
        "source_repo": entry.source_repo,
        "license": entry.license,
        "sellable": entry.sellable,
        "tier": "optional" if entry.name in OPTIONAL_NAMES else "standard",
        "sha256": digest(dest / "SKILL.md"),
        "files": files,
        "skipped": skipped,
        "description_truncated": truncated,
        "variants": variants,
    }


def license_file_for(license: str) -> Path | None:
    candidates = [
        ({"MIT", "MIT OR Apache-2.0"}, ROOT_SUITE / "LICENSE"),
        ({"Apache-2.0", "MIT OR Apache-2.0"}, GITHUB_ROOT / "skill" / "skills" / "claude-api" / "LICENSE.txt"),
        ({"BSD-3-Clause"}, GITHUB_ROOT / "ai-hub-models" / "LICENSE"),
    ]
    for licenses, path in candidates:
        if license in licenses and path.is_file():
            return path
    return None


def write_licenses(role_dir: Path, manifest: dict[str, object]) -> None:
    licenses = role_dir / "LICENSES"
    licenses.mkdir(exist_ok=True)
    seen: set[str] = set()
    for meta in manifest["skills"].values():
        license = meta["license"]
        if license in seen:
            continue
        seen.add(license)
        if license == "MIT OR Apache-2.0":
            (licenses / "mit-or-apache-2-0.txt").write_text(
                "Dual-licensed skills in this catalog are available under either\n"
                "the MIT license (mit.txt) or Apache-2.0 (apache-2-0.txt).\n",
                encoding="utf-8",
            )
            continue
        source = license_file_for(license)
        if source:
            shutil.copy2(source, licenses / f"{slug(license)}.txt")
    (licenses / "README.md").write_text(
        "# Role-local skill licenses\n\n"
        "Each file here corresponds to an SPDX identifier in `.inventory.json`.\n"
        "The manifest is the authoritative mapping from skill to license.\n",
        encoding="utf-8",
    )


def write_notices(role_dir: Path, manifest: dict[str, object], role: str) -> None:
    lines = [
        f"# Third-party notices — {role} role-local skills",
        "",
        "Every skill in this catalog is recorded in `.inventory.json` with its",
        "source path and license. The master catalog is restricted to the sellable",
        "license allowlist; the peer catalog is a curated subset of the same rule.",
        "",
        "| Skill | License | Source |",
        "|---|---|---|",
    ]
    for name, meta in sorted(manifest["skills"].items()):
        lines.append(f"| `{name}` | {meta['license']} | `{meta['source']}` |")
    lines.append("")
    (role_dir / "THIRD_PARTY_NOTICES.md").write_text("\n".join(lines), encoding="utf-8")


def write_readme(role_dir: Path, manifest: dict[str, object], role: str) -> None:
    counts = manifest["counts"]
    optional = counts.get("optional", 0)
    text = f"""# Role-local skill catalog — {role}

This directory is the **role-local** addition to the base suite at
`../../.opencode/skills/`. opencode discovers it when a session starts inside
`{role}-node/` (or a subdirectory), because config resolution walks up to the
nearest `.opencode/` directory.

- Role-local skills: **{counts["skills"]}**
- Optional / non-standard: **{optional}** (`claude-api`, master only)
- Base suite: **{counts["base_suite"]}** skills, shared at the fabric root
- Total visible in a role session: **{counts["total_visible"]}**

## License policy

The catalog is sellable by construction:

- Allowed: MIT, Apache-2.0, BSD-2-Clause, BSD-3-Clause, ISC, CC0-1.0,
  Unlicense, and the original dual `MIT OR Apache-2.0` skills.
- Excluded: proprietary/source-available, no-license/unclear, GPL/AGPL,
  CC BY-SA, and modified Apache terms.
- `claude-api` is kept only from the Apache-2.0 source and is marked
  `tier: optional`; it is not part of the peer set and is not a default skill.
- The only newly authored skill is `skill-template` (dual MIT/Apache-2.0).

## Provenance

`.inventory.json` records the source path, source repository, license, SHA-256
of `SKILL.md`, copied file count, skipped large/nested files, and variant
bodies. `THIRD_PARTY_NOTICES.md` is the human-readable companion. `LICENSES/`
holds the distinct license texts.

## Refresh and check

```bash
make -C {role}-node skills-sync
make -C {role}-node skills-check
```

The check fails on a missing skill, a name/frontmatter mismatch, a nested
`SKILL.md`, a symlink, a restricted license, or a manifest hash mismatch.
"""
    (role_dir / "README.md").write_text(text, encoding="utf-8")


def build_manifest(
    role: str,
    role_dir: Path,
    entries: dict[str, list[Entry]],
    base_count: int,
    original_names: set[str],
    valid_names: set[str],
) -> dict[str, object]:
    skills: dict[str, object] = {}
    for name in sorted(entries):
        if name in original_names:
            continue
        canonical = min(entries[name], key=lambda entry: (entry.priority, len(entry.path.as_posix())))
        canonical.variants = [entry for entry in entries[name] if entry is not canonical]
        skills[name] = copy_skill(canonical, role_dir / name)
    counts = {
        "skills": len(skills),
        "optional": sum(1 for meta in skills.values() if meta["tier"] == "optional"),
        "base_suite": base_count,
        "total_visible": len(skills) + base_count,
    }
    return {
        "role": role,
        "generated_by": "scripts/sync-role-skills.py",
        "license_policy": {
            "allowed": sorted(ALLOWED_LICENSES),
            "excluded": [
                "proprietary",
                "RESTRICTED",
                "UNKNOWN",
                "GPL-3.0",
                "AGPL-3.0",
                "CC-BY-SA-4.0",
                "Apache-2.0-modified",
            ],
        },
        "counts": counts,
        "removed": sorted(REMOVED_NAMES),
        "skipped_invalid": sorted(SKIPPED_INVALID - valid_names - original_names),
        "skills": skills,
    }


def apply(role: str) -> int:
    entries = scan_github() + scan_farm() + scan_raxxar()
    root_names = scan_root_suite()
    role_dir = ROLE_DIRS[role]
    role_dir.mkdir(parents=True, exist_ok=True)
    original = ROLE_DIRS["peer"] / "skill-template"
    if role == "master":
        if not original.is_dir():
            print("peer skill-template missing; author it first", file=sys.stderr)
            return 1
        if (role_dir / "skill-template").exists():
            shutil.rmtree(role_dir / "skill-template")
        shutil.copytree(original, role_dir / "skill-template")
    for child in sorted(role_dir.iterdir()):
        if child.is_dir() and child.name not in {"skill-template"}:
            shutil.rmtree(child)
        elif child.is_file() and child.name != ".inventory.json":
            child.unlink()
    if role == "peer":
        selected: dict[str, list[Entry]] = {}
        for name in PEER_SKILLS:
            if name == "skill-template":
                continue
            entry = choose(entries, name)
            if entry is None:
                print(f"peer skill missing or not sellable: {name}", file=sys.stderr)
                return 1
            selected[name] = [item for item in entries if item.name == name and item.sellable]
    else:
        grouped = all_sellable(entries, root_names)
        selected = {name: variants for name, variants in grouped.items()}
    original_names = {"skill-template"}
    manifest = build_manifest(
        role, role_dir, selected, len(root_names), original_names, {entry.name for entry in entries}
    )
    if role == "peer" and "skill-template" not in manifest["skills"]:
        manifest["skills"]["skill-template"] = {
            "source": "original",
            "source_repo": "sparknet",
            "license": "MIT OR Apache-2.0",
            "sellable": True,
            "tier": "original",
            "sha256": digest(role_dir / "skill-template" / "SKILL.md"),
            "files": len(list((role_dir / "skill-template").rglob("*"))),
            "skipped": [],
            "variants": [],
        }
        manifest["counts"]["skills"] += 1
        manifest["counts"]["total_visible"] += 1
    if role == "master":
        manifest["skills"]["skill-template"] = {
            "source": "original:peer-node/.opencode/skills/skill-template",
            "source_repo": "sparknet",
            "license": "MIT OR Apache-2.0",
            "sellable": True,
            "tier": "original",
            "sha256": digest(role_dir / "skill-template" / "SKILL.md"),
            "files": len(list((role_dir / "skill-template").rglob("*"))),
            "skipped": [],
            "variants": [],
        }
        manifest["counts"]["skills"] += 1
        manifest["counts"]["total_visible"] += 1
    (role_dir / ".inventory.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_readme(role_dir, manifest, role)
    write_licenses(role_dir, manifest)
    write_notices(role_dir, manifest, role)
    print(
        f"{role}: {manifest['counts']['skills']} role-local skills "
        f"({manifest['counts']['base_suite']} base, {manifest['counts']['total_visible']} visible)"
    )
    return 0


def check_role(role: str) -> list[str]:
    role_dir = ROLE_DIRS[role]
    manifest_path = role_dir / ".inventory.json"
    problems: list[str] = []
    if not manifest_path.is_file():
        return [f"{role}: .inventory.json is missing"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    skills = manifest.get("skills", {})
    present = {path.parent.name for path in role_dir.rglob("SKILL.md")}
    if present != set(skills):
        missing = sorted(set(skills) - present)
        extra = sorted(present - set(skills))
        problems.append(f"{role}: manifest/disk mismatch missing={missing} extra={extra}")
    if role == "peer":
        expected = set(PEER_SKILLS)
        if set(skills) != expected:
            problems.append(f"{role}: expected {len(expected)} peer skills, disk has {len(skills)}")
    for name, meta in sorted(skills.items()):
        skill_dir = role_dir / name
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            problems.append(f"{role}/{name}: SKILL.md missing")
            continue
        meta_fm = frontmatter(skill_md.read_text(encoding="utf-8", errors="replace"))
        if meta_fm.get("name") != name:
            problems.append(f"{role}/{name}: frontmatter name {meta_fm.get('name')!r}")
        if not NAME_RE.match(name) or len(name) > MAX_NAME:
            problems.append(f"{role}/{name}: invalid skill name")
        if not meta_fm.get("description"):
            problems.append(f"{role}/{name}: missing description")
        elif len(meta_fm["description"]) > MAX_DESCRIPTION:
            problems.append(f"{role}/{name}: description too long")
        if name in REMOVED_NAMES:
            problems.append(f"{role}/{name}: removed name is still present")
        if meta.get("license") not in ALLOWED_LICENSES:
            problems.append(f"{role}/{name}: non-sellable license {meta.get('license')!r}")
        if meta.get("sha256") != digest(skill_md):
            problems.append(f"{role}/{name}: SKILL.md hash mismatch")
        if any(path.is_symlink() for path in skill_dir.rglob("*")):
            problems.append(f"{role}/{name}: symlink present")
        nested = [path for path in skill_dir.rglob("SKILL.md") if path.parent != skill_dir]
        if nested:
            problems.append(f"{role}/{name}: nested SKILL.md present")
    template = role_dir / "skill-template" / "SKILL.md"
    other = ROLE_DIRS["peer"] / "skill-template" / "SKILL.md"
    if not template.is_file():
        problems.append(f"{role}: skill-template missing")
    elif role == "master" and other.is_file() and digest(template) != digest(other):
        problems.append("master: skill-template differs from peer copy")
    return problems


def report() -> int:
    entries = scan_github() + scan_farm() + scan_raxxar()
    root_names = scan_root_suite()
    grouped = all_sellable(entries, root_names)
    print(f"scanned entries: {len(entries)}")
    print(f"root base suite: {len(root_names)}")
    print(f"sellable role-local names: {len(grouped)}")
    print(f"removed names: {len(REMOVED_NAMES)}")
    print(f"peer names: {len(PEER_SKILLS)}")
    missing = [name for name in PEER_SKILLS if name != "skill-template" and choose(entries, name) is None]
    print(f"peer missing: {missing}")
    valid_names = {entry.name for entry in entries}
    skipped_invalid = SKIPPED_INVALID - valid_names
    print(f"skipped invalid: {len(skipped_invalid)} {sorted(skipped_invalid)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="build the role catalogs")
    parser.add_argument("--check", action="store_true", help="verify an existing catalog")
    parser.add_argument("--report", action="store_true", help="print classification counts")
    parser.add_argument("--role", choices=("peer", "master", "all"), default="all")
    args = parser.parse_args()
    if sum(bool(value) for value in (args.apply, args.check, args.report)) != 1:
        parser.error("choose exactly one of --apply, --check, --report")
    if args.report:
        return report()
    roles = ("peer", "master") if args.role == "all" else (args.role,)
    if args.apply:
        for role in roles:
            code = apply(role)
            if code:
                return code
        return 0
    problems: list[str] = []
    for role in roles:
        problems.extend(check_role(role))
    if problems:
        for problem in problems:
            print(f"role-skills: {problem}", file=sys.stderr)
        return 1
    print("role-skills: clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
