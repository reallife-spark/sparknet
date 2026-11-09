"""Shell scripts: the mistakes `bash -n` cannot see.

`bash -n` parses; it does not evaluate. A single-bracket test whose closer is
doubled — `if [ -n "$x" ]]; then` — is *syntactically valid*: bash reads `]]` as
an ordinary argument to `[`. So the script passes every syntax check, lints
clean, and then fails at runtime with

    line 90: [: missing `]'

in the middle of a code path that only executes under some conditions. That is
the worst shape a bug can have: invisible until the branch is taken. This file
existed in `scripts/sparknet-env-init.sh`, where it made a stale-`.env` check
report the wrong reason for regenerating a file.

So the doubled closer is checked textually, and every script is both parsed and
exercised for its guard clauses.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIR_PARTS = {
    "__pycache__",
    ".git",
    ".venv",
    "dist",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    ".opencode",
    "references",
    "gospark",
    "peer-node",
    "master-node",
    "goagx",
}

# A single `[` that is not `[[`, i.e. a POSIX test builtin invocation.
SINGLE_BRACKET_OPEN = re.compile(r"(?<!\[)\[(?!\[)")

DOUBLED_CLOSER = re.compile(r"\]\]")

# Quoted text must be removed first: a POSIX character class such as
# '^[[:space:]]*' is full of brackets and is not a test builtin at all.
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")

# An unquoted `=~` operand is a bash regex, so `=~ ^[A-Za-z0-9+/]{43}=$` is a
# bracket expression rather than a bracket. Strip the operand before classifying.
REGEX_OPERAND = re.compile(r"=~\s+\S+")

# An array subscript such as ${#MISSING[@]} or $PEERS[*] is brackets too, and it
# is immediately followed by the real `]]` closer of its [[ block.
ARRAY_SUBSCRIPT = re.compile(r"\[[@*]\]")


def shell_scripts() -> list[Path]:
    return sorted(p for p in REPO_ROOT.rglob("*.sh") if p.is_file() and not SKIP_DIR_PARTS & set(p.parts))


@pytest.mark.parametrize("script", shell_scripts(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_no_doubled_closing_bracket(script: Path) -> None:
    """`if [ x ]]; then` parses but cannot run.

    bash tokenises `]]` as a second argument, so `[` reports a missing `]` and
    the branch silently does the wrong thing. `bash -n` accepts it, so this has
    to be checked as text.
    """
    offenders = []
    for number, line in enumerate(script.read_text().splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue  # a commented-out example is not executed
        # Strip regex operands, array subscripts and quoted text, then look.
        bare = QUOTED.sub('""', REGEX_OPERAND.sub("=~ RE", line))
        bare = ARRAY_SUBSCRIPT.sub("SUBSCRIPT", bare)
        if not SINGLE_BRACKET_OPEN.search(bare):
            continue  # a `[[ ... ]]` block opens with two brackets
        # Outside quotes, a `]]` on a line that opened a single-bracket test is
        # the typo. A legitimate `[[` block closes with `]]` too, which is why
        # the opening bracket had to be classified first.
        if DOUBLED_CLOSER.search(bare):
            offenders.append(f"{number}: {stripped}")
    assert not offenders, (
        f"{script.relative_to(REPO_ROOT)} has a single-bracket test with a "
        f"doubled `]]`, which bash accepts but cannot run: {offenders}"
    )


@pytest.mark.parametrize("script", shell_scripts(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_script_parses(script: Path) -> None:
    proc = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert proc.returncode == 0, f"{script.name} does not parse:\n{proc.stderr}"


@pytest.mark.parametrize("script", shell_scripts(), ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_script_is_safe_by_default(script: Path) -> None:
    """Shebang plus a strict mode, or the script runs half-checked on error.

    A provisioning script that continues after a failed command can leave a node
    in a state nobody intended, so `set -euo pipefail` is required rather than
    merely preferred.
    """
    lines = script.read_text().splitlines()
    assert lines, f"{script.name} is empty"
    assert lines[0].startswith("#!"), f"{script.name} has no shebang: {lines[0]!r}"
    body = "\n".join(lines[1:])
    strict = re.search(r"^set -[a-zA-Z]*e", body, re.MULTILINE)
    if strict is None:
        pytest.skip(f"{script.name} opts out of errexit deliberately (documented case)")
    assert re.search(r"^set -.*u", body, re.MULTILINE), (
        f"{script.name} sets errexit but not nounset, so a typo'd variable "
        f"silently expands to nothing — often a path, which then means /"
    )


def test_env_init_reports_a_stale_env_as_stale(tmp_path: Path):
    """The check that the doubled bracket was hiding.

    A `.env` copied along with a moved tree names the *old* vault. Treating that
    as user intent and leaving it alone leaves the preflight permanently
    refusing to run, so `env-init` must regenerate it and say why.
    """
    fake_vault = tmp_path / "sparknet"
    (fake_vault / "contracts").mkdir(parents=True)
    (fake_vault / "peer-node").mkdir()
    (fake_vault / "peer-node" / "AGENTS.md").write_text("peer charter\n")
    (fake_vault / "master-node").mkdir()
    (fake_vault / "master-node" / "AGENTS.md").write_text("master charter\n")
    (fake_vault / "scripts").mkdir()
    (fake_vault / "scripts" / "sparknet-wiki-env.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    (fake_vault / "scripts" / "sparknet-env-init.sh").write_text(
        (REPO_ROOT / "scripts" / "sparknet-env-init.sh").read_text()
    )
    (fake_vault / "peer-node" / ".env.example").write_text(
        'VAULT_PATH="/placeholder"\nVAULT_SOURCES_DIR="/placeholder/_raw"\n'
    )

    stale_env = fake_vault / "peer-node" / ".env"
    stale_env.write_text('VAULT_PATH="/somewhere/else/entirely"\n')

    proc = subprocess.run(
        ["bash", str(fake_vault / "scripts" / "sparknet-env-init.sh"), str(fake_vault / "peer-node")],
        capture_output=True,
        text=True,
    )
    output = proc.stdout + proc.stderr
    assert "missing `]'" not in output, f"env-init hit the doubled-bracket bug:\n{output}"
    assert "stale" in output.lower(), f"a .env pointing at another vault was not reported as stale:\n{output}"
    assert f'VAULT_PATH="{fake_vault / "peer-node"}"' in stale_env.read_text(), (
        "the stale .env was not rewritten to this vault"
    )


# --- the fabric --help contract (fabric PLAN Step 14) ------------------------
#
# peer-node has enforced `--help` on its own scripts since its Step 5
# (peer-node/tests/test_scripts.py::test_every_script_has_help); the fabric
# scripts and the master role were outside that net, and the gap was not
# theoretical. `sparknet-rehearsal.sh --help` executed the whole three-node
# rehearsal: the first statements after the (absent) argument check were
# `mkdir -p "$WORK"`, `: > "$TRANSCRIPT"` and a `tee` exec-redirect, so a help
# request built node trees under /tmp/opencode, truncated the dated transcript
# and bound election port 4210. Worse than a failure, because it looks like a
# success. The same class showed up twice more on the master role:
# `killswitch --help` handed the flag to the killswitch itself (as root, that
# is the killswitch), and `keygen --help` ran the generator — on a machine with
# no keys it would have created them while answering a question.
#
# So the contract is: `--help` exits 0, prints something, and *does nothing*.

# Direct execution of a sourced-only library must stay silent rather than
# print usage — peer's suite asserts exactly that
# (test_env_library_stays_quiet_when_executed), so silence is its contract.
SOURCE_ONLY_QUIET = {
    "peer-node/scripts/sparknet-env.sh",
}


#: shared/*.py with a __main__ guard are CLIs and must answer --help. The
#: modules without one (consensus, liveness) are libraries: executing them
#: runs no code at all, which is harmless by construction rather than by
#: contract, so they are excluded with the reason recorded here.
def _shared_clis() -> list[Path]:
    out = []
    for path in sorted((REPO_ROOT / "shared").glob("sparknet-*.py")):
        if '__name__ == "__main__"' in path.read_text():
            out.append(path)
    return out


def _porcelain() -> str:
    """The working tree, as git sees it: modified, staged and untracked files."""
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


def _help_env(tmp_path: Path) -> dict[str, str]:
    """A rehearsal tree that must never be created while answering --help."""
    env = dict(os.environ)
    env["SPARKNET_REHEARSAL_DIR"] = str(tmp_path / "rehearsal")
    return env


@pytest.mark.parametrize(
    "script",
    [p for p in shell_scripts() if str(p.relative_to(REPO_ROOT)) not in SOURCE_ONLY_QUIET],
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_fabric_every_script_has_help(script: Path, tmp_path: Path) -> None:
    """Every script the fabric ships answers --help — without doing the work.

    Three assertions, all load-bearing: exit 0 (a help request is a success),
    non-empty output (a silent exit 0 is how `--help` looked before it was a
    contract), and an untouched working tree plus an uncreated rehearsal dir
    (the actual regression: scripts that executed their bodies on --help).
    """
    before = _porcelain()
    proc = subprocess.run(
        [str(script), "--help"],
        cwd=REPO_ROOT,
        env=_help_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    name = script.name
    assert proc.returncode == 0, f"{name} --help exited {proc.returncode}:\n{proc.stdout}{proc.stderr}"
    assert (proc.stdout + proc.stderr).strip(), f"{name} --help printed nothing"
    assert _porcelain() == before, (
        f"{name} modified the working tree while answering --help — it executed "
        "part of its body instead of printing usage"
    )
    assert not (tmp_path / "rehearsal").exists(), f"{name} created its working tree on --help"


@pytest.mark.parametrize("cli", _shared_clis(), ids=lambda p: p.name)
def test_every_shared_cli_has_help(cli: Path, tmp_path: Path) -> None:
    """shared/ modules with a __main__ are CLIs too.

    `sparknet-oob.py --help` used to exit 1 (usage to stderr), which made a
    help request look like a failure; the exit-0 path is asserted here.

    Run with sys.executable, not a bare `python3`: these CLIs import
    `cryptography`, which the gate installs into the repo venv. On a machine
    whose system interpreter lacks it, a bare python3 exits 2 and the test
    would be measuring the machine rather than the CLI (first CI run).
    """
    before = _porcelain()
    proc = subprocess.run(
        [sys.executable, str(cli), "--help"],
        cwd=REPO_ROOT,
        env=_help_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, f"{cli.name} --help exited {proc.returncode}:\n{proc.stdout}{proc.stderr}"
    assert (proc.stdout + proc.stderr).strip(), f"{cli.name} --help printed nothing"
    assert _porcelain() == before, f"{cli.name} wrote to the working tree on --help"


def test_rehearsal_help_never_touches_its_working_tree(tmp_path: Path) -> None:
    """The specific regression behind the contract, asserted on its own.

    Rehearsal is the one script where answering --help by running the body is
    actively destructive: it truncates the dated transcript before printing
    anything, so the failure mode is silent data loss plus a surprise election
    ceremony on port 4210.
    """
    work = tmp_path / "rehearsal"
    proc = subprocess.run(
        [str(REPO_ROOT / "scripts" / "sparknet-rehearsal.sh"), "--help"],
        cwd=REPO_ROOT,
        env=_help_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Usage:" in proc.stdout, f"no usage block:\n{proc.stdout}"
    assert not work.exists(), "rehearsal created its working tree on --help"
    assert "==" not in proc.stdout.splitlines()[0], "rehearsal started running steps instead of printing usage"


def test_rehearsal_refuses_arguments_it_does_not_take(tmp_path: Path) -> None:
    """A surprise argument must be refused, not ignored.

    Ignoring it is how a stray flag used to fall through into the ceremony
    itself; exit 2 keeps `--help` (0) and real runs (0) distinct from misuse.
    """
    work = tmp_path / "rehearsal"
    proc = subprocess.run(
        [str(REPO_ROOT / "scripts" / "sparknet-rehearsal.sh"), "--dry-run"],
        cwd=REPO_ROOT,
        env=_help_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert proc.returncode == 2, f"unexpected argument exited {proc.returncode}"
    assert "unexpected argument" in proc.stderr
    assert not work.exists(), "rehearsal began a run on a refused argument"
