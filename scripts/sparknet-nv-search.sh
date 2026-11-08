#!/usr/bin/env bash
# Resource-first lookup against NVIDIA's catalogs.
#
# The rule this script exists for: before building a container, model or
# service of our own, check what NVIDIA already publishes. What each surface
# actually is (verified 2026-10-17, see references/nvidia-build-catalog.md):
#
#   integrate.api.nvidia.com/v1/models   JSON, no auth — 81 model ids today
#   integrate.api.nvidia.com/v1/models/<id>
#                                        JSON; 200 for a live model, 410 with
#                                        the end-of-life date for a retired one
#   build.nvidia.com/**                  a Next.js SPA — every route answers
#                                        200 text/html, so it is a browser
#                                        surface, not an API (this is why the
#                                        old `/api/search` idea was dropped)
#   api.ngc.nvidia.com/v2/search/...     JSON but requires a key (401 without)
#
# Auth is optional for everything except `ngc`. When present the key is read
# from one place only: $SPARKNET_STATE_DIR/secrets/build-nvidia.env (default
# .state/secrets/build-nvidia.env, mode 0600, under the gitignored .state/).
# The key is never echoed, logged or written here.
#
# Usage:
#   scripts/sparknet-nv-search.sh --help
#   scripts/sparknet-nv-search.sh models [SUBSTRING]  list model ids (optionally filtered)
#   scripts/sparknet-nv-search.sh show ID            one model; prints its EOL note if retired
#   scripts/sparknet-nv-search.sh ngc QUERY          NGC catalog search (needs a key)
#   scripts/sparknet-nv-search.sh discover           print the browser surfaces to search by hand
#
# Exit codes: 0 ok, 1 network/curl failure, 2 usage error.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${SPARKNET_STATE_DIR:-$REPO_ROOT/.state}"
KEY_FILE="$STATE_DIR/secrets/build-nvidia.env"
INTEGRATE_BASE="https://integrate.api.nvidia.com"
NGC_BASE="https://api.ngc.nvidia.com"

usage() {
  printf '%s\n' \
    'sparknet-nv-search.sh — search NVIDIA catalogs before building your own' \
    '' \
    'Usage:' \
    '  scripts/sparknet-nv-search.sh models [SUBSTRING]  model ids (JSON-backed list)' \
    '  scripts/sparknet-nv-search.sh show ID             one model id; EOL note if retired' \
    '  scripts/sparknet-nv-search.sh ngc QUERY           NGC catalog search (key required)' \
    '  scripts/sparknet-nv-search.sh discover            browser surfaces (SPA, not an API)' \
    '  scripts/sparknet-nv-search.sh --help' \
    '' \
    'Auth (optional): BUILD_NVIDIA_API_KEY in' \
    '  $SPARKNET_STATE_DIR/secrets/build-nvidia.env   (default .state/secrets/)' \
    'is sent as a bearer token; the value is never printed by this script.' \
    '' \
    'Recording a lookup: paste the query and the verdict into the page or plan' \
    'you were working from, so the next agent can see the search happened.'
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
  "")
    usage >&2
    exit 2
    ;;
esac

command -v curl >/dev/null 2>&1 || {
  printf 'sparknet-nv-search: curl not found on PATH\n' >&2
  exit 1
}

cmd="$1"
shift

AUTH=()
HAVE_KEY=0
AUTH_HEADER_FILE=""
cleanup_auth() { [ -z "$AUTH_HEADER_FILE" ] || rm -f "$AUTH_HEADER_FILE"; }
trap cleanup_auth EXIT
if [ -f "$KEY_FILE" ]; then
  # The file is runtime state (0600, gitignored), not part of the repository.
  # shellcheck disable=SC1090
  . "$KEY_FILE"
  if [ -n "${BUILD_NVIDIA_API_KEY:-}" ]; then
    case "$BUILD_NVIDIA_API_KEY" in
      *$'\n'*|*$'\r'*) printf 'sparknet-nv-search: API key contains a newline\n' >&2; exit 2 ;;
    esac
    AUTH_HEADER_FILE="$(mktemp "${TMPDIR:-/tmp}/sparknet-nv-auth.XXXXXX")"
    chmod 600 "$AUTH_HEADER_FILE"
    printf 'Authorization: Bearer %s\n' "$BUILD_NVIDIA_API_KEY" > "$AUTH_HEADER_FILE"
    AUTH=(-H "@$AUTH_HEADER_FILE")
    HAVE_KEY=1
  fi
fi

# ${AUTH[@]+…} keeps `set -u` happy on bash 3.2 (macOS), where expanding an
# empty array is otherwise an unbound-variable error.
fetch() {
  curl -fsS --max-time 30 ${AUTH[@]+"${AUTH[@]}"} "$@"
}

case "$cmd" in
  models)
    pattern="${1:-}"
    fetch "$INTEGRATE_BASE/v1/models" | python3 -c '
import json, sys
pattern = sys.argv[1]
for model in json.load(sys.stdin).get("data", []):
    if pattern.lower() in model.get("id", "").lower():
        print(model.get("id", ""))
' "$pattern"
    ;;
  show)
    [ "$#" -ge 1 ] || { printf 'sparknet-nv-search: show needs an ID\n' >&2; exit 2; }
    id="$1"
    # -w appends the status code so a 410 (retired model) can be reported with
    # its end-of-life body instead of a bare curl failure.
    response="$(curl -sS --max-time 30 ${AUTH[@]+"${AUTH[@]}"} -w '\n%{http_code}' \
      "$INTEGRATE_BASE/v1/models/$id" 2>/dev/null || true)"
    code="${response##*$'\n'}"
    body="${response%$'\n'*}"
    case "$code" in
      200) printf '%s\n' "$body" ;;
      410)
        printf 'sparknet-nv-search: %s is retired — %s\n' "$id" "$body" >&2
        exit 1
        ;;
      "")
        printf 'sparknet-nv-search: no response for %s (network down?)\n' "$id" >&2
        exit 1
        ;;
      *)
        printf 'sparknet-nv-search: %s -> HTTP %s\n' "$id" "$code" >&2
        if [ -n "$body" ]; then
          printf '%s\n' "$body" >&2
        fi
        exit 1
        ;;
    esac
    ;;
  ngc)
    [ "$#" -ge 1 ] || { printf 'sparknet-nv-search: ngc needs a QUERY\n' >&2; exit 2; }
    if [ "$HAVE_KEY" -eq 0 ]; then
      printf 'sparknet-nv-search: NGC search needs a key — set BUILD_NVIDIA_API_KEY in %s\n' "$KEY_FILE" >&2
      exit 2
    fi
    query="$*"
    fetch -G --data-urlencode "q=$query" --data-urlencode "pageSize=20" \
      "$NGC_BASE/v2/search/resources/ALL"
    ;;
  discover)
    printf '%s\n' \
      'Browser surfaces (SPA — search these by hand, then record the verdict):' \
      '  https://build.nvidia.com/explore/discover   curated models + containers' \
      '  https://build.nvidia.com/search?q=<terms>    site search' \
      '  https://catalog.ngc.nvidia.com/search?q=<terms>  NGC containers/helm/models' \
      '' \
      'Machine-readable (this script):' \
      '  sparknet-nv-search.sh models [SUBSTRING]' \
      '  sparknet-nv-search.sh show ID'
    ;;
  *)
    printf 'sparknet-nv-search: unknown command %s\n' "$cmd" >&2
    usage >&2
    exit 2
    ;;
esac
