#!/usr/bin/env bash
# Contract smoke (spec §10): responses of the running stack validate against openapi.yaml.
#
#   make contract-smoke           (needs `make up` first)
#
# 1. Reads the operations the backend actually serves from its generated OpenAPI document
#    (/api/v1/openapi.json, served outside prod). Operations that exist only in the contract
#    (planned, not implemented yet) are skipped; new endpoints are picked up automatically.
# 2. Signs up a throwaway athlete so authenticated operations (getMe, updateMe, ...) are
#    exercised with a valid session cookie, not only as 401s.
# 3. Runs schemathesis against the COMMITTED openapi.yaml (not the app's generated document)
#    through nginx, with the response-conformance checks: no 5xx, documented status codes,
#    content types, headers and body schemas.
# 4. Fails if the throwaway account's email or password reached the container logs (rule 6).
#
# Environment: BASE_URL (default: the published frontend port), SCHEMATHESIS_MAX_EXAMPLES
# (default 25), SCHEMATHESIS_SEED (default 1, so CI runs are reproducible).
set -euo pipefail

COMPOSE=${COMPOSE:-docker compose}
SCHEMATHESIS_VERSION=4.32.4
CHECKS=not_a_server_error,status_code_conformance,content_type_conformance,response_headers_conformance,response_schema_conformance
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)

base=${BASE_URL:-}
if [[ -z "$base" ]]; then
  hostport=$($COMPOSE port frontend 8080 2>/dev/null || true)
  if [[ -z "$hostport" ]]; then
    echo "contract-smoke: the stack is not running; run 'make up' first." >&2
    exit 1
  fi
  base="http://localhost:${hostport##*:}"
fi
api="${base}/api/v1"
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# --- 0. No real network (CLAUDE.md rule 4, #153) --------------------------------------------
# The backend must talk to the Open Food Facts fake (compose.ci.yaml), never the real service.
if [[ -z "${BASE_URL:-}" ]]; then
  off_url=$($COMPOSE exec -T backend printenv OFF_BASE_URL 2>/dev/null || true)
  if [[ "$off_url" != http://off-fake:* ]]; then
    echo "contract-smoke: the backend's OFF_BASE_URL is '${off_url:-<default>}', not the Open Food Facts fake." >&2
    echo "  Start the stack with: COMPOSE_FILE=compose.yaml:compose.ci.yaml make up" >&2
    exit 1
  fi
  echo "contract-smoke: OFF_BASE_URL=${off_url} (fake, no external requests)"
fi

# --- 1. Served operations ---------------------------------------------------------------------
served=$(curl -fsS --max-time 15 "${api}/openapi.json" | python3 -c '
import json, sys
doc = json.load(sys.stdin)
methods = {"get", "post", "put", "patch", "delete"}
ids = sorted(op["operationId"] for item in doc["paths"].values()
             for m, op in item.items() if m in methods and "operationId" in op)
print("\n".join(ids))')
if [[ -z "$served" ]]; then
  echo "contract-smoke: the backend serves no operations?" >&2
  exit 1
fi
include=()
while read -r op; do include+=(--include-operation-id "$op"); done <<<"$served"
echo "contract-smoke: ${api}, operations: $(tr '\n' ' ' <<<"$served")"

# --- 2. Throwaway session -------------------------------------------------------------------
suffix="$(date +%s)$RANDOM"
email="smoke-${suffix}@example.com"
password="smoke-pw-${suffix}-$RANDOM$RANDOM"
workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' EXIT
headers="${workdir}/headers"
code=$(curl -sS -o /dev/null -D "$headers" -w '%{http_code}' --max-time 15 \
  -H 'Content-Type: application/json' -X POST "${api}/auth/signup" \
  -d "{\"email\":\"${email}\",\"password\":\"${password}\",\"display_name\":\"Smoke\",\"role\":\"athlete\",\"birth_date\":\"1995-04-12\",\"units\":\"metric\",\"timezone\":\"Europe/Madrid\",\"accept_disclaimer\":true}")
cookie=$(sed -n 's/^[Ss]et-[Cc]ookie: *\(fitwise_session=[^;]*\).*/\1/p' "$headers" | head -1)
if [[ "$code" != 201 || -z "$cookie" ]]; then
  echo "contract-smoke: sign-up of the throwaway account failed (HTTP ${code})." >&2
  exit 1
fi

# --- 3. Schemathesis --------------------------------------------------------------------------
# -H is applied to every request; unauthenticated operations (health, sign-up, login) ignore it.
# --output-sanitize (default on) keeps the cookie out of the report. Runs in $workdir so its
# .schemathesis/ cache never lands in the repository.
(cd "$workdir" && uvx --quiet "schemathesis==${SCHEMATHESIS_VERSION}" run "${root}/openapi.yaml" \
  --url "$api" \
  "${include[@]}" \
  --header "Cookie: ${cookie}" \
  --checks "$CHECKS" \
  --max-examples "${SCHEMATHESIS_MAX_EXAMPLES:-25}" \
  --seed "${SCHEMATHESIS_SEED:-1}" \
  --workers 1 \
  --request-timeout 10 \
  --generation-database none \
  --no-color)

# --- 4. The throwaway credentials never reach the logs ---------------------------------------
if [[ -z "${BASE_URL:-}" ]]; then
  hits=$($COMPOSE logs --no-color --since "$since" 2>&1 | grep -cF -e "$email" -e "$password" || true)
  if [[ "$hits" -ne 0 ]]; then
    echo "contract-smoke: FAILED, the smoke account's email or password appears in logs (${hits} lines)." >&2
    exit 1
  fi
  echo "contract-smoke: smoke account email/password in logs: 0 hits"
fi
echo "contract-smoke: OK"
