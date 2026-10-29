#!/usr/bin/env bash
# Restart one application container (spec §15.2, on-call tool; issue #69).
#
#   oncall/ops/restart.sh <backend|frontend>
#
# Only `backend` and `frontend` are accepted; anything else (no argument, several arguments, db,
# grafana, an option, a service name with odd characters) exits 2 and touches nothing. The
# database and the observability stack are never restarted by the on-call agent.
#
# Environment:
#   COMPOSE   compose command, default "docker compose" (on the host it carries the -f overrides
#             of the running release, like for flag.sh)
#
# Exit status: 0 restarted, 2 invalid arguments, other non-zero: docker compose failed.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $(basename "$0") <backend|frontend>" >&2
  exit 2
fi
case "$1" in
  backend | frontend) service=$1 ;;
  *)
    echo "error: only 'backend' or 'frontend' may be restarted; nothing changed" >&2
    exit 2
    ;;
esac

cd "$(dirname "$0")/../.."
# shellcheck disable=SC2086  # COMPOSE may hold several words, e.g. "docker compose -f a -f b"
exec ${COMPOSE:-docker compose} restart "$service"
