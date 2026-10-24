#!/usr/bin/env bash
# Run a build or install command with bounded parallelism and a wall-clock cap.
#
# Why this exists: on the small aarch64 node (Orange Pi 5 Plus, RK3588) an
# unbounded native build saturates all eight cores for minutes. The node's
# thermal envelope is narrow, and a build that pins every core is exactly the
# load profile that ends with a silent power-level reset — a failure mode with
# no kernel trace, no panic and no shutdown marker, so the only usable defence
# is to keep the load inside the envelope in the first place.
#
# The wrapper therefore does three things:
#   1. caps parallelism (MAKEFLAGS, CMAKE_BUILD_PARALLEL_LEVEL, OMP/BLAS/…),
#   2. caps wall-clock time, so a stuck build cannot run for hours,
#   3. prefers prebuilt wheels over source builds when asked to (`--pip`),
#      because a wheel is the cheapest possible native dependency.
#
# It does not mutate the repository, and it fails closed: a build that exceeds
# the timeout is killed and the non-zero exit is propagated.
#
# Usage:
#   scripts/sparknet-safe-build.sh [options] -- <command> [args...]
#
# Options:
#   --jobs N          max parallelism (default 2, env SAFE_BUILD_JOBS)
#   --timeout SEC     wall-clock cap in seconds (default 3600, 0 = no cap)
#   --nice N          niceness for the child (default 10)
#   --pip             pip mode: try binary wheels first, fall back to source
#   --dry-run         print the resolved command and environment, run nothing
#   -h, --help        print this text and exit 0
#
# Examples:
#   scripts/sparknet-safe-build.sh -- make chroma-index
#   scripts/sparknet-safe-build.sh --pip -- .venv/bin/pip install chromadb
set -euo pipefail

JOBS="${SAFE_BUILD_JOBS:-2}"
TIMEOUT_SECONDS="${SAFE_BUILD_TIMEOUT:-3600}"
NICE_LEVEL="${SAFE_BUILD_NICE:-10}"
PIP_MODE=0
DRY_RUN=0

usage() {
    cat <<'EOF'
sparknet-safe-build.sh - run a build/install command with bounded parallelism

Usage:
  scripts/sparknet-safe-build.sh [options] -- <command> [args...]

Options:
  --jobs N          max parallelism (default 2, env SAFE_BUILD_JOBS)
  --timeout SEC     wall-clock cap in seconds (default 3600, 0 = no cap)
  --nice N          niceness for the child (default 10)
  --pip             pip mode: try binary wheels first, fall back to source
  --dry-run         print the resolved command and environment, run nothing
  -h, --help        print this text and exit 0
EOF
}

die() {
    printf 'safe-build: %s\n' "$1" >&2
    exit 2
}

ORIGINAL_CMD=()
BINARY_CMD=()
SEEN_INSTALL=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
            ;;
        --jobs)
            [ "$#" -ge 2 ] || die "--jobs needs a value"
            JOBS="$2"
            shift 2
            ;;
        --timeout)
            [ "$#" -ge 2 ] || die "--timeout needs a value"
            TIMEOUT_SECONDS="$2"
            shift 2
            ;;
        --nice)
            [ "$#" -ge 2 ] || die "--nice needs a value"
            NICE_LEVEL="$2"
            shift 2
            ;;
        --pip)
            PIP_MODE=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --)
            shift
            break
            ;;
        *)
            ORIGINAL_CMD+=("$1")
            shift
            ;;
    esac
done

while [ "$#" -gt 0 ]; do
    ORIGINAL_CMD+=("$1")
    shift
done

if [ "${#ORIGINAL_CMD[@]}" -eq 0 ]; then
    usage >&2
    die "no command given"
fi

case "$JOBS" in
    ''|*[!0-9]*)
        die "--jobs must be a positive integer"
        ;;
esac
if [ "$JOBS" -lt 1 ]; then
    die "--jobs must be at least 1"
fi

case "$TIMEOUT_SECONDS" in
    ''|*[!0-9]*)
        die "--timeout must be a non-negative integer"
        ;;
esac

case "$NICE_LEVEL" in
    ''|*[!0-9]*)
        die "--nice must be a non-negative integer"
        ;;
esac

for arg in "${ORIGINAL_CMD[@]}"; do
    BINARY_CMD+=("$arg")
    if [ "$SEEN_INSTALL" -eq 0 ] && [ "$arg" = "install" ]; then
        SEEN_INSTALL=1
        BINARY_CMD+=("--only-binary=:all:")
    fi
done

export MAKEFLAGS="-j${JOBS}"
export CMAKE_BUILD_PARALLEL_LEVEL="$JOBS"
export OMP_NUM_THREADS="$JOBS"
export OPENBLAS_NUM_THREADS="$JOBS"
export MKL_NUM_THREADS="$JOBS"
export NUMEXPR_NUM_THREADS="$JOBS"
export VECLIB_MAXIMUM_THREADS="$JOBS"
export CARGO_BUILD_JOBS="$JOBS"
export GOMAXPROCS="$JOBS"
export NUMA="0"

printf 'safe-build: jobs=%s timeout=%ss nice=%s pip_mode=%s\n' \
    "$JOBS" "$TIMEOUT_SECONDS" "$NICE_LEVEL" "$PIP_MODE"
printf 'safe-build: cmd=%s\n' "${ORIGINAL_CMD[*]}"

if [ "$DRY_RUN" -eq 1 ]; then
    printf 'safe-build: MAKEFLAGS=%s CMAKE_BUILD_PARALLEL_LEVEL=%s OMP_NUM_THREADS=%s\n' \
        "$MAKEFLAGS" "$CMAKE_BUILD_PARALLEL_LEVEL" "$OMP_NUM_THREADS"
    exit 0
fi

run_cmd() {
    if [ "$TIMEOUT_SECONDS" -gt 0 ]; then
        timeout --signal=TERM --kill-after=30 "$TIMEOUT_SECONDS" \
            nice -n "$NICE_LEVEL" "${ORIGINAL_CMD[@]}"
    else
        nice -n "$NICE_LEVEL" "${ORIGINAL_CMD[@]}"
    fi
}

run_binary_first() {
    if [ "$TIMEOUT_SECONDS" -gt 0 ]; then
        timeout --signal=TERM --kill-after=30 "$TIMEOUT_SECONDS" \
            nice -n "$NICE_LEVEL" "${BINARY_CMD[@]}"
    else
        nice -n "$NICE_LEVEL" "${BINARY_CMD[@]}"
    fi
}

if [ "$PIP_MODE" -eq 1 ] && [ "$SEEN_INSTALL" -eq 1 ]; then
    printf 'safe-build: trying binary wheels first (%s)\n' "${BINARY_CMD[*]}"
    if run_binary_first; then
        printf 'safe-build: binary wheels satisfied the install\n'
        exit 0
    fi
    printf 'safe-build: no complete wheel set; falling back to a bounded source build\n'
fi

run_cmd
printf 'safe-build: done\n'
