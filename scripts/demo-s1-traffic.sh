#!/usr/bin/env bash
# Traffic for demo scenario S1 (issue #20): POST /sessions/{id}/finish at a steady rate, so the
# KeyJourneyErrors guard (>= 20 requests in 5 min, > 5 % failing) is met.
#   BASE_URL=http://<prod host> scripts/demo-s1-traffic.sh [count=40] [pause_seconds=6]
# The request has no body and no credentials, the session id is a fixed all-zero UUID that exists
# nowhere, and only the HTTP status code is printed, so it carries no health data. On a healthy
# release it answers 401 (no session cookie); on the S1 build the fault answers 500 before
# authentication (backend/app/demo_faults.py). After the rollback it answers 401 again, so the
# ratio falls back under 5 % while the script keeps sending.
set -euo pipefail
base="${BASE_URL:?set BASE_URL, for example http://<prod elastic ip>}"
count="${1:-40}"
pause="${2:-6}"
case "$count$pause" in *[!0-9]*) echo "count and pause must be integers" >&2; exit 2 ;; esac
sid="00000000-0000-0000-0000-000000000000"
ok=0
err=0
for i in $(seq 1 "$count"); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 -X POST "${base%/}/api/v1/sessions/$sid/finish" || true)"
  case "$code" in 5*) err=$((err + 1)) ;; *) ok=$((ok + 1)) ;; esac
  printf '%s %3d/%d HTTP %s\n' "$(date -u +%H:%M:%SZ)" "$i" "$count" "$code"
  sleep "$pause"
done
echo "done: ${err} x 5xx, ${ok} other"
