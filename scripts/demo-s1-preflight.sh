#!/usr/bin/env bash
# Read-only pre-flight for demo scenario S1 (issue #20), the part that needs no host access.
#   BASE_URL=http://<prod host> GITHUB_REPOSITORY=<owner/repo> scripts/demo-s1-preflight.sh [drill-sha]
# Checks what prod serves (public /healthz and /readyz), that it is a release prod approved before, the
# last "Promote to production" runs, and, with a drill SHA, that dev proved it and that it differs
# from what prod serves. It changes nothing: GET requests and `gh` reads only. Exit 1 if a check fails.
# The host-side checks (CURRENT_TAG/PREVIOUS_TAG, responder, alert rule state) are the block in
# docs/runbooks/demo-s1.md, section "Pre-flight", run by the orchestrator over SSM.
set -uo pipefail
base="${BASE_URL:?set BASE_URL, for example http://<prod elastic ip>}"
repo="${GITHUB_REPOSITORY:-DanielB280320/AiDevToolsZoomcamp_FinalProject}"
drill="${1:-}"
fails=0
check() { # description, command...
  local what="$1"
  shift
  if "$@" >/dev/null 2>&1; then echo "ok    $what"; else echo "FAIL  $what"; fails=$((fails + 1)); fi
}

served="$(curl -fsS --max-time 10 "${base%/}/api/v1/healthz" | jq -r '.version // empty' 2>/dev/null)"
echo "prod serves: ${served:-unreachable}"
check "healthz returns a 40-hex SHA" test "${#served}" -eq 40
check "readyz is 200" curl -fsS --max-time 10 -o /dev/null "${base%/}/api/v1/readyz"

history="$(gh api "repos/$repo/commits?sha=deploy/prod&per_page=50" --jq '.[].commit.message' 2>/dev/null || true)"
check "the served SHA is in the history of deploy/prod (prod approved it)" \
  bash -c '[ -n "$1" ] && grep -q "^source: *$1" <<<"$2"' _ "$served" "$history"
echo "deploy/prod, newest releases first:"
grep '^source:' <<<"$history" | head -5 | sed 's/^/  /'
echo "last runs of 'Promote to production':"
gh run list --repo "$repo" --workflow promote-prod.yml --limit 3 --json databaseId,conclusion,headSha,createdAt \
  --jq '.[] | "  run \(.databaseId) \(.conclusion // "in progress") \(.createdAt)"' 2>/dev/null || echo "  (gh not available)"

if [ -n "$drill" ]; then
  [[ "$drill" =~ ^[0-9a-f]{40}$ ]] || { echo "FAIL  the drill SHA must be 40 lowercase hex characters"; exit 1; }
  check "the drill SHA differs from what prod serves" test "$drill" != "$served"
  GITHUB_REPOSITORY="$repo" check "dev proved the drill SHA (deploy-dev and smoke-dev succeeded)" \
    "$(dirname "$0")/promote-verify.sh" "$drill"
fi

if [ "$fails" -eq 0 ]; then echo "pre-flight (public part): all checks passed"; else echo "pre-flight: $fails check(s) failed"; exit 1; fi
