"""The resource-first helper, exercised without the network.

`make nv-search` talks to NVIDIA's live catalog; a test that did the same
would fail the suite whenever the network or the catalog changed, which is the
opposite of what a gate is for. So these tests pin the helper's own contract:
argument handling, the `--help`-does-nothing rule, the filter, and the two
response shapes that matter (200 live / 410 retired) — with a stub `curl` on
PATH standing in for the network.

One of these is a security assertion, not a convenience one: a key present in
the secrets file is passed to curl as a header and must never appear in the
helper's own output.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPER = REPO_ROOT / "scripts" / "sparknet-nv-search.sh"

STUB = """#!/usr/bin/env bash
args="$*"
body="${STUB_CURL_BODY:-}"
code="${STUB_CURL_CODE:-200}"
if [ -n "${STUB_CURL_ARGS_FILE:-}" ]; then
  printf '%s\\n' "$args" > "$STUB_CURL_ARGS_FILE"
fi
if [[ "$args" == *"%{http_code}"* ]]; then
  printf '%s\\n%s\\n' "$body" "$code"
else
  printf '%s\\n' "$body"
fi
exit 0
"""


def run_helper(
    tmp_path: Path,
    *args: str,
    body: str = "{}",
    code: int = 200,
    state_dir: Path | None = None,
    key: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "curl"
    stub.write_text(STUB)
    stub.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["STUB_CURL_BODY"] = body
    env["STUB_CURL_CODE"] = str(code)
    args_file = tmp_path / "curl-args.txt"
    env["STUB_CURL_ARGS_FILE"] = str(args_file)

    if state_dir is not None:
        env["SPARKNET_STATE_DIR"] = str(state_dir)
        if key is not None:
            secrets = state_dir / "secrets"
            secrets.mkdir(parents=True, mode=0o700, exist_ok=True)
            key_file = secrets / "build-nvidia.env"
            key_file.write_text(f"BUILD_NVIDIA_API_KEY={key}\n")
            key_file.chmod(0o600)

    result = subprocess.run(
        ["bash", str(HELPER), *args],
        capture_output=True,
        text=True,
        env=env,
    )
    return result, args_file.read_text() if args_file.exists() else ""


def test_help_answers_and_touches_nothing(tmp_path: Path):
    result, called = run_helper(tmp_path, "--help")
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert called == "", "--help must not reach the network"


def test_no_arguments_is_a_usage_error(tmp_path: Path):
    result, called = run_helper(tmp_path)
    assert result.returncode == 2
    assert called == ""


def test_an_unknown_command_is_a_usage_error(tmp_path: Path):
    result, _ = run_helper(tmp_path, "bogus")
    assert result.returncode == 2
    assert "unknown command" in result.stderr


def test_models_filters_the_catalog_list(tmp_path: Path):
    body = '{"data":[{"id":"meta/llama-3.1-8b"},{"id":"nvidia/nemotron-4-340b"}]}'
    result, _ = run_helper(tmp_path, "models", "llama", body=body)
    assert result.returncode == 0
    assert result.stdout.splitlines() == ["meta/llama-3.1-8b"]


def test_a_retired_model_reports_its_eol_date(tmp_path: Path):
    detail = '{"detail":"The model reached its end of life on 2026-08-26"}'
    result, _ = run_helper(
        tmp_path,
        "show",
        "meta/llama-3.1-8b",
        body=detail,
        code=410,
    )
    assert result.returncode == 1
    assert "is retired" in result.stderr
    assert "2026-08-26" in result.stderr


def test_a_live_model_prints_the_response(tmp_path: Path):
    result, _ = run_helper(
        tmp_path,
        "show",
        "nvidia/nemotron-4-340b",
        body='{"id":"nvidia/nemotron-4-340b"}',
    )
    assert result.returncode == 0
    assert "nemotron-4-340b" in result.stdout


def test_ngc_without_a_key_refuses_and_names_the_path(tmp_path: Path):
    result, called = run_helper(tmp_path, "ngc", "vllm")
    assert result.returncode == 2
    assert "build-nvidia.env" in result.stderr
    assert called == "", "no request should be made without a key"


def test_a_present_key_is_sent_but_never_printed(tmp_path: Path):
    state = tmp_path / "state"
    (state / "secrets").mkdir(parents=True, mode=0o700)
    result, called = run_helper(
        tmp_path,
        "ngc",
        "vllm",
        state_dir=state,
        key="nvapi-test-secret",
        body='{"results":[]}',
    )
    assert result.returncode == 0
    assert "Authorization: Bearer nvapi-test-secret" in called
    assert "nvapi-test-secret" not in result.stdout
    assert "nvapi-test-secret" not in result.stderr
