#!/usr/bin/env bash
# Weekly adaptive-calorie job (issue #42, spec F14). Runs as root from fitwise-adaptive-calories.timer
# on dev and prod; installed to /opt/fitwise/bin by deploy/bootstrap.sh.
#
#   docker exec <running backend container> python -m app.cli.adaptive_calories
#
# The CLI is idempotent per athlete and Monday and decides "this week" in each athlete's own time
# zone, so the timer runs on Monday and Tuesday (see the timer): the Tuesday run catches the zones
# west of UTC whose Monday had not started yet. Any failure exits non-zero, so the unit fails
# (`systemctl --failed`, `journalctl -u fitwise-adaptive-calories`). Output holds only statuses and
# the count the CLI prints (no health data, no athlete ids).
set -euo pipefail

log() { printf '%s fitwise-adaptive-calories: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

backend="$(docker ps -q --filter label=com.docker.compose.project=fitwise --filter label=com.docker.compose.service=backend | head -n1)"
[ -n "$backend" ] || die "backend container not running"

log "running the weekly check"
# Only the status line printed by the CLI is kept; its stderr carries no values either.
docker exec "$backend" python -m app.cli.adaptive_calories || die "the weekly check failed"
log "done"
