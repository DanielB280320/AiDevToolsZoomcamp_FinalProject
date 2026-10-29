#!/usr/bin/env bash
# Tests the root helper of the on-call agent (deploy/oncall-compose.sh) and the docker shim
# (oncall/host/docker), issue #69. No docker, no root, no network: fake docker and fake sudo.
#   - ps / logs / restart backend|frontend / the flag CLI pass through to `docker compose` of the
#     CURRENT_TAG release
#   - everything else (follow, exec of anything else, restart db, down, up, other options) exits 2
#     and docker is never called
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; root="$here/.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fails=0
ck() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (want '$3', got '$2')"; fails=$((fails+1)); fi; }

SHA=$(printf 'a%.0s' $(seq 40))
export APP_DIR="$tmp/app" DEPLOY_ENV_FILE="$tmp/none"
mkdir -p "$APP_DIR/releases/$SHA" "$tmp/bin"
printf '%s\n' "$SHA" > "$APP_DIR/CURRENT_TAG"; : > "$APP_DIR/.env"; : > "$APP_DIR/releases/$SHA/release.env"
printf '#!/bin/sh\necho "$@" >> "%s/docker.log"\n' "$tmp" > "$tmp/bin/docker"; chmod +x "$tmp/bin/docker"
export PATH="$tmp/bin:$PATH"
helper="$root/deploy/oncall-compose.sh"

run_ok() { # name args... : expects exit 0 and one docker call ending with the args
  local name="$1"; shift; rm -f "$tmp/docker.log"
  "$helper" "$@" >/dev/null 2>&1; ck "$name exit" "$?" "0"
  ck "$name docker call" "$(sed 's/^.*compose.yaml -f compose.deploy.yaml //' "$tmp/docker.log" 2>/dev/null)" "$*"
}
run_bad() {
  local name="$1"; shift; rm -f "$tmp/docker.log"
  "$helper" "$@" >/dev/null 2>&1; ck "$name refused (exit 2)" "$?" "2"
  ck "$name docker not called" "$([ -e "$tmp/docker.log" ] && echo called || echo no)" "no"
}
run_ok "ps" ps
run_ok "ps -a --format" ps -a --format json
run_ok "logs" logs --since 30m --tail 200 backend
run_ok "restart backend" restart backend
run_ok "restart frontend" restart frontend
run_ok "flag CLI" exec -T backend python -m app.cli.flags set progression_engine v1 --actor oncall-agent --log-stream /proc/1/fd/1

run_bad "no args"
run_bad "up" up -d
run_bad "down" down
run_bad "ps unknown option" ps --filter x
run_bad "logs follow" logs -f backend
run_bad "logs --follow" logs --follow backend
run_bad "logs odd service" logs 'backend;id'
run_bad "restart db" restart db
run_bad "restart two" restart backend frontend
run_bad "restart none" restart
run_bad "exec shell" exec -T backend sh
run_bad "exec psql" exec -T db psql -U postgres
run_bad "exec flag bad actor" exec -T backend python -m app.cli.flags set progression_engine v1 --actor root --log-stream /proc/1/fd/1
run_bad "exec flag bad key" exec -T backend python -m app.cli.flags set 'a;b' v1 --actor oncall-agent --log-stream /proc/1/fd/1
run_bad "exec extra arg" exec -T backend python -m app.cli.flags set a v1 --actor oncall-agent --log-stream /proc/1/fd/1 x

# no deployed release: refuses (exit 1), docker not called
rm -f "$APP_DIR/CURRENT_TAG" "$tmp/docker.log"; "$helper" ps >/dev/null 2>&1; ck "no release: failure" "$([ $? -ne 0 ] && echo y)" "y"

# the shim: only `docker compose ...`, forwarded through sudo to the helper
printf '#!/bin/sh\n[ "$1" = -n ] || exit 99\nshift\necho "$@" > "%s/sudo.log"\n' "$tmp" > "$tmp/bin/sudo"; chmod +x "$tmp/bin/sudo"
"$root/oncall/host/docker" compose logs --tail 5 backend >/dev/null 2>&1
ck "shim forwards compose" "$(cat "$tmp/sudo.log")" "/opt/fitwise/bin/oncall-compose.sh logs --tail 5 backend"
rm -f "$tmp/sudo.log"; "$root/oncall/host/docker" ps >/dev/null 2>&1; ck "shim refuses non-compose (exit 2)" "$?" "2"
ck "shim did not call sudo" "$([ -e "$tmp/sudo.log" ] && echo called || echo no)" "no"

[ "$fails" = 0 ] && echo "all passed" || { echo "$fails failed"; exit 1; }
