#!/usr/bin/env bash
# Machine-readable test reports for the fabric.
#
# `make test-all` prints to a terminal, which is right for a person and useless
# for anything else: there is no artifact to attach to a review, no per-suite
# count to diff across runs, and nothing a later tool can read. This wraps the
# suite so each run leaves a JUnit XML per scope under `.state/reports/` and one
# aggregated `summary.json` beside it.
#
# Coverage is included only when `pytest-cov` is importable: sparknet's dev
# tooling deliberately installs pytest and ruff and nothing else, so a coverage
# gate that hard-depended on pytest-cov would fail on a clean node.
#
# Usage:
#   scripts/sparknet-test-report.sh [fabric|peer|master|all] [--help]
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
REPORTS="$ROOT/.state/reports"

case "${1:-}" in
  -h|--help)
    printf '%s\n' \
      'sparknet-test-report.sh — write JUnit XML + summary.json for a suite' \
      '' \
      'Usage:' \
      '  scripts/sparknet-test-report.sh [fabric|peer|master|all] [--help]' \
      '' \
      'scope defaults to "fabric". Reports land in .state/reports/:' \
      '  <scope>.xml    JUnit XML for that scope' \
      '  summary.json   aggregated counts for every scope run' \
      '' \
      'Coverage is added only if pytest-cov is installed.'
    exit 0 ;;
esac

scope="fabric"
for arg in "$@"; do
  case "$arg" in
    fabric|peer|master|all) scope="$arg" ;;
    *) printf 'sparknet-test-report: unexpected argument: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

VENV_PY="$ROOT/.venv/bin/python"
if [ -x "$VENV_PY" ]; then PY="$VENV_PY"; else PY="python3"; fi

# `.state` holds machine-local state and `keys-check` requires it to be 0700, so
# create it at that mode rather than letting the umask pick 0755 — otherwise a
# report run that happens to create `.state` first breaks the key gate.
install -d -m 0700 "$ROOT/.state"
mkdir -p "$REPORTS"

have_cov=0
if "$PY" -c 'import pytest_cov' >/dev/null 2>&1; then have_cov=1; fi

overall=0
run_scope() {
  local name="$1"; shift
  local workdir="$1"; shift
  local target="$1"; shift
  local junit="$REPORTS/${name}.xml"
  local cov=()
  if [ "$have_cov" -eq 1 ]; then
    cov=("--cov" "--cov-report" "term-missing")
  fi
  printf '\n\033[36m== %s ==\033[0m\n' "$name"
  # A failing suite must still leave its JUnit XML behind: the report is most
  # valuable precisely when the run was red, so the failure is recorded rather
  # than aborting the script before it writes anything.
  if ( cd "$workdir" && "$PY" -m pytest "$target" -q --junitxml="$junit" "${cov[@]}" ); then
    :
  else
    overall=1
  fi
  return 0
}

case "$scope" in
  fabric) run_scope "fabric" "$ROOT"             "tests" ;;
  peer)   run_scope "peer"   "$ROOT/peer-node"   "tests" ;;
  master) run_scope "master" "$ROOT/master-node" "tests" ;;
  all)
    run_scope "fabric" "$ROOT"             "tests"
    run_scope "peer"   "$ROOT/peer-node"   "tests"
    run_scope "master" "$ROOT/master-node" "tests"
    ;;
esac

if [ "$have_cov" -eq 0 ]; then
  printf '\n\033[33mnote:\033[0m pytest-cov not installed — coverage omitted\n'
fi

# Aggregate every XML present under REPORTS into summary.json. Written in Python
# because the alternative is parsing XML in bash, which is how report tooling
# becomes its own bug.
"$PY" - "$REPORTS" <<'PY'
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

reports = Path(sys.argv[1])
summary = {"scopes": {}, "totals": {"tests": 0, "failures": 0, "errors": 0,
                                    "skipped": 0, "time": 0.0}}
for xml in sorted(reports.glob("*.xml")):
    try:
        root = ET.parse(xml).getroot()
    except ET.ParseError as exc:  # a crashed run can leave a truncated file
        summary["scopes"][xml.stem] = {"error": f"unparseable JUnit XML: {exc}"}
        continue
    # pytest writes a <testsuites> wrapper holding one <testsuite>; older tools
    # write <testsuite> as the root. Accept both.
    suites = root.findall("testsuite") or ([root] if root.tag == "testsuite" else [])
    if not suites:
        summary["scopes"][xml.stem] = {"error": "no <testsuite> element"}
        continue
    entry = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0, "time": 0.0}
    for suite in suites:
        entry["tests"] += int(suite.get("tests", 0))
        entry["failures"] += int(suite.get("failures", 0))
        entry["errors"] += int(suite.get("errors", 0))
        entry["skipped"] += int(suite.get("skipped", 0))
        entry["time"] += float(suite.get("time", 0.0))
    entry["time"] = round(entry["time"], 3)
    summary["scopes"][xml.stem] = entry
    for key in ("tests", "failures", "errors", "skipped"):
        summary["totals"][key] += entry[key]
    summary["totals"]["time"] += entry["time"]
summary["totals"]["time"] = round(summary["totals"]["time"], 3)

out = reports / "summary.json"
out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
print(f"\nwrote {out}")
for name, entry in summary["scopes"].items():
    if "error" in entry:
        print(f"  {name:<8} {entry['error']}")
    else:
        print(f"  {name:<8} {entry['tests']} tests, {entry['failures']} failed, "
              f"{entry['errors']} errors, {entry['skipped']} skipped")
PY

# Propagate the suite's result after the artifacts are written.
exit "$overall"
