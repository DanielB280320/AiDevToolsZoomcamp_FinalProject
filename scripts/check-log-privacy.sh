#!/usr/bin/env bash
# Log-privacy smoke check for the running Compose stack (CLAUDE.md rule 6, spec §6.5).
#
#   make check-log-privacy        (needs `make up` first)
#
# Sends requests that carry a unique marker in the query string, Referer, User-Agent, Cookie,
# Authorization and X-Forwarded-For (a TEST-NET address), and a sensitive-looking SPA route,
# both while the backend is healthy and while it is STOPPED (the upstream-failure path a
# restart, deploy or rollback takes, where nginx's error log used to record the full request
# line). Then it fails if any container log line since the start contains the marker, the
# forwarded address, the client IP nginx saw, or the error-log context fields
# ("request:", "referrer:", "client:").
#
# The backend is always started again before the script exits.
set -euo pipefail

COMPOSE=${COMPOSE:-docker compose}
marker="LOGPRIVACY$(date +%s)$RANDOM"
fake_ip="203.0.113.77" # RFC 5737 TEST-NET-3, never a real client

hostport=$($COMPOSE port frontend 8080 2>/dev/null || true)
if [[ -z "$hostport" ]]; then
  echo "check-log-privacy: the stack is not running; run 'make up' first." >&2
  exit 1
fi
base="http://localhost:${hostport##*:}"
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)

restore_backend() {
  $COMPOSE up -d --wait backend >/dev/null 2>&1 || echo "WARN: could not restart backend" >&2
}
trap restore_backend EXIT

probe() {
  local label=$1 code
  for path in \
    "/api/v1/foods?q=${marker}food&email=${marker}%40example.com&token=${marker}tok" \
    "/api/v1/healthz?note=${marker}note" \
    "/today?q=${marker}spa"; do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 \
      -e "http://ref.example/?food=${marker}ref" \
      -A "${marker}agent" \
      -b "fitwise_session=${marker}cookie" \
      -H "Authorization: Bearer ${marker}bearer" \
      -H "X-Forwarded-For: ${fake_ip}" \
      "${base}${path}" || true)
    echo "  ${label}: ${path%%\?*} -> ${code}"
  done
}

echo "check-log-privacy: marker ${marker}, base ${base}"
probe "backend up  "
echo "  stopping backend (upstream-failure path)"
$COMPOSE stop backend >/dev/null 2>&1
probe "backend down"
restore_backend
trap - EXIT

# The address nginx sees as the client (the Docker network gateway for host requests).
client_ip=$($COMPOSE exec -T frontend sh -c "ip route 2>/dev/null | awk '/default/ {print \$3}'" | tr -d '\r' || true)

logs=$($COMPOSE logs --no-color --since "$since" 2>&1)
patterns=("$marker" "$fake_ip" "request: \"" "referrer: \"" "client: ")
[[ -n "$client_ip" ]] && patterns+=("$client_ip")

fail=0
for pattern in "${patterns[@]}"; do
  hits=$(grep -cF -- "$pattern" <<<"$logs" || true)
  printf '  %-28s %s hit(s)\n' "$pattern" "$hits"
  if [[ "$hits" -ne 0 ]]; then
    fail=1
    grep -F -- "$pattern" <<<"$logs" | head -3 | sed 's/^/    > /'
  fi
done

if [[ $fail -ne 0 ]]; then
  echo "check-log-privacy: FAILED, sensitive request data reached container logs." >&2
  exit 1
fi
echo "check-log-privacy: OK (0 hits in $(wc -l <<<"$logs") log lines)"
