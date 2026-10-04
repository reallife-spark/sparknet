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

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIR_PARTS = {"__pycache__", ".git", ".venv", "dist", "node_modules",
                  ".pytest_cache", ".ruff_cache", ".opencode", "references"}

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
    return sorted(
        p for p in REPO_ROOT.rglob("*.sh")
        if p.is_file() and not SKIP_DIR_PARTS & set(p.parts)
    )


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
    (fake_vault / "scripts" / "sparknet-wiki-env.sh").write_text(
        "#!/usr/bin/env bash\nexit 0\n"
    )
    (fake_vault / "scripts" / "sparknet-env-init.sh").write_text(
        (REPO_ROOT / "scripts" / "sparknet-env-init.sh").read_text()
    )
    (fake_vault / "peer-node" / ".env.example").write_text(
        'VAULT_PATH="/placeholder"\nVAULT_SOURCES_DIR="/placeholder/_raw"\n'
    )

    stale_env = fake_vault / "peer-node" / ".env"
    stale_env.write_text('VAULT_PATH="/somewhere/else/entirely"\n')

    proc = subprocess.run(
        ["bash", str(fake_vault / "scripts" / "sparknet-env-init.sh"),
         str(fake_vault / "peer-node")],
        capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    assert "missing `]'" not in output, (
        f"env-init hit the doubled-bracket bug:\n{output}"
    )
    assert "stale" in output.lower(), (
        f"a .env pointing at another vault was not reported as stale:\n{output}"
    )
    assert f'VAULT_PATH="{fake_vault / "peer-node"}"' in stale_env.read_text(), (
        "the stale .env was not rewritten to this vault"
    )