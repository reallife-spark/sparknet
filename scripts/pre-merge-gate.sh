#!/usr/bin/env bash
# The fabric's local pre-merge gate: every check a merge must pass, in one run.
#
# Why a script and not a CI workflow: sparknet is offline-first and is cloned
# onto nodes that have no forge and no hosted runner. The gate has to be
# something a person runs before they merge — and something `make ci` can wrap.
# A `.github/workflows/` mirror runs this same script on a hosted runner for a
# status check (fabric PLAN Step 48), but the LOCAL gate stays authoritative: a
# node has no forge, so a green badge there is never what authorizes a merge.
#
# It runs the same checks in the same order every time and reports every
# failure it finds rather than stopping at the first, because a merge blocked on
# one step that then reveals two more is three review cycles instead of one.
#
# Usage:
#   scripts/pre-merge-gate.sh [--quick] [--help]
#
# --quick runs the fast gates only and skips the full test suite (which takes
# minutes on a Spark node).
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

case "${1:-}" in
  -h|--help)
    printf '%s\n' \
      'pre-merge-gate.sh — run every fabric gate a merge must pass' \
      '' \
      'Usage:' \
      '  scripts/pre-merge-gate.sh [--quick] [--help]' \
      '' \
      '--quick   run the fast gates only (skip the full test suite)' \
      '' \
      'Runs keys-check, shims-check, context-check, governance-check, lint, format-check, shellcheck (provisioning' \
      'the pinned binary when it is absent), role-skills-check, validate,' \
      'contract-test, render-check, sbom-check, then' \
      'the full suite. Reports every failure it finds, and exits non-zero if' \
      'any step failed.'
    exit 0 ;;
esac

quick=0
for arg in "$@"; do
  case "$arg" in
    --quick|--no-tests) quick=1 ;;
    *) printf 'pre-merge-gate: unexpected argument: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

failures=0
failed_names=()

# run_step never lets a failing command abort the gate: it records the failure
# and returns 0 so the remaining steps still run and the report is complete.
run_step() {
  local name="$1"; shift
  printf '\n\033[36m== %s ==\033[0m\n' "$name"
  if "$@"; then
    printf '\033[32m    PASS\033[0m %s\n' "$name"
  else
    printf '\033[31m    FAIL\033[0m %s\n' "$name" >&2
    failures=$((failures + 1))
    failed_names+=("$name")
  fi
  return 0
}

run_step "context-check" make --no-print-directory -C "$ROOT" context-check
run_step "governance-check" make --no-print-directory -C "$ROOT" governance-check
run_step "phase8-check"    make --no-print-directory -C "$ROOT" phase8-check
run_step "keys-check"    make --no-print-directory -C "$ROOT" keys-check
run_step "shims-check"   make --no-print-directory -C "$ROOT" shims-check
run_step "lint"          make --no-print-directory -C "$ROOT" lint
run_step "format-check"  make --no-print-directory -C "$ROOT" format-check
run_step "shellcheck"    make --no-print-directory -C "$ROOT" shellcheck
run_step "role-skills-check" make --no-print-directory -C "$ROOT" role-skills-check
run_step "validate"      make --no-print-directory -C "$ROOT" validate
run_step "contract-test" make --no-print-directory -C "$ROOT" contract-test
run_step "render-check"  make --no-print-directory -C "$ROOT" render-check
run_step "sbom-check"    make --no-print-directory -C "$ROOT" sbom-check

if [ "$quick" -eq 1 ]; then
  printf '\n\033[33m== test-all ==\033[0m\n'
  printf '\033[33m    SKIP\033[0m full suite skipped (--quick)\n'
else
  run_step "test-all" make --no-print-directory -C "$ROOT" test-all
fi

printf '\n%s\n' '----------------------------------------'
if [ "$failures" -eq 0 ]; then
  printf '\033[32mpre-merge-gate: all steps passed\033[0m\n'
  exit 0
fi
printf '\033[31mpre-merge-gate: %d step(s) failed\033[0m\n' "$failures"
for name in "${failed_names[@]}"; do
  printf '  - %s\n' "$name"
done
exit 1
