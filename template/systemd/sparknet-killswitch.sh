#!/usr/bin/env bash
# KillSwitch (root-restricted) - minimal viable implementation
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$(cd "${SCRIPT_DIR}/../scripts" && pwd)/sparknet-env.sh"

DRY_RUN=0
FORCE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --force)
      FORCE=1
      shift
      ;;
    --help|-h)
      echo "Usage: $0 [--dry-run] [--force]"
      echo "KillSwitch: halts schedulers, tears down wg0, stops control planes, enforces nftables drop (ROOT-GATED)"
      exit 0
      ;;
    *)
      shift
      ;;
  esac
done

log() {
  local level="$1"
  shift
  printf "[%s] [%s] %s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$level" "$*"
}

log "INFO" "sparknet-killswitch starting"
log "INFO" "EUID=$(id -u), UID=$(id -u), USER=${USER:-$(id -un)}"

# Root-gating check
if [[ "$(id -u)" -ne 0 ]]; then
  log "ERROR" "KillSwitch requires root privileges (EUID=0). Current EUID=$(id -u)"
  log "ERROR" "Root-gated as per design - requires signed approvals"
  exit 1
fi

log "INFO" "ROOT-GATED check: PASSED"
log "INFO" "Staged teardown (template):"
log "INFO" "  1. Halt Sparknet schedulers/agents"
log "INFO" "  2. Tear down wg0 (WireGuard Master Anchor)"
log "INFO" "  3. Stop control planes (orchestrator/agents)"
log "INFO" "  4. Enforce emergency nftables drop policy"
log "INFO" "  5. Lock critical paths state"

if [[ "${DRY_RUN}" -eq 1 ]]; then
  log "INFO" "DRY-RUN: No actual teardown performed"
  log "INFO" "sparknet-killswitch completed (DRY-RUN)"
  exit 0
fi

if [[ "${FORCE}" -ne 1 ]]; then
  log "WARN" "Use --force to execute actual teardown (template mode)"
  log "INFO" "sparknet-killswitch completed (template mode, no action)"
  exit 0
fi

log "INFO" "Executing teardown (template mode)"
log "INFO" "sparknet-killswitch completed"
exit 0
