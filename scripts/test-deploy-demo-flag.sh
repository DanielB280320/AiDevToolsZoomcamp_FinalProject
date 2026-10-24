#!/usr/bin/env bash
# Tests the FITWISE_DEMO_FAIL_HEALTH switch in deploy/lib.sh (#14, D60). No docker, no network.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export APP_DIR="$tmp"
# shellcheck disable=SC1091
. "$here/../deploy/lib.sh"
fails=0
check() { # name, want (0 = flag active), env-file content or "<absent>"
  rm -f "$ENV_FILE"; [ "$3" = "<absent>" ] || printf '%b' "$3" > "$ENV_FILE"
  demo_health_fail; got=$?
  if [ "$got" = "$2" ]; then echo "ok   $1"; else echo "FAIL $1 (got $got)"; fails=$((fails+1)); fi
}
check "no .env file: off"              1 "<absent>"
check "flag not present: off"          1 "JWT_SECRET=x\nDB_PASSWORD=y\n"
check "flag=0: off"                    1 "FITWISE_DEMO_FAIL_HEALTH=0\n"
check "commented out: off"             1 "# FITWISE_DEMO_FAIL_HEALTH=1\n"
check "other variable with suffix: off" 1 "XFITWISE_DEMO_FAIL_HEALTH=1\n"
check "flag=1 among others: on"        0 "A=b\nFITWISE_DEMO_FAIL_HEALTH=1\nC=d\n"
out="$(demo_health_fail 2>&1)"; [ -z "$out" ] && echo "ok   prints nothing" || { echo "FAIL prints output"; fails=$((fails+1)); }
# rollback.sh must not consult the flag; deploy.sh must.
grep -q demo_health_fail "$here/../deploy/rollback.sh" && { echo "FAIL rollback.sh uses the flag"; fails=$((fails+1)); } || echo "ok   rollback.sh ignores the flag"
grep -q demo_health_fail "$here/../deploy/deploy.sh" && echo "ok   deploy.sh checks the flag" || { echo "FAIL deploy.sh does not check the flag"; fails=$((fails+1)); }
[ "$fails" = 0 ] && echo "all demo-flag tests passed" || { echo "$fails failed"; exit 1; }
