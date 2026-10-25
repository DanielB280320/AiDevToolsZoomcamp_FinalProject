#!/usr/bin/env bash
# Alerts fire-and-resolve test (#97, spec §15.1, D53): KeyJourneyErrors and KeyJourneyLatency
# against the REAL provisioned rules (5 min / 10 min windows) with a stub webhook receiver.
#
#   make test-alerts            (or: observability/alert-test/run.sh [--down])
#
# Starts its own stack (own compose project, own ports, APP_ENV=prod so the `env="prod"` rules
# match, Grafana's webhook pointed at the stub on the Docker host), then runs driver.py.
# Takes about 30-40 minutes (waits for the real alert windows). Evidence goes to
# observability/alert-test/out/ (git-ignored; ALERT_TEST_OUT changes it). ALERT_TEST_ONLY=errors|latency
# runs one alert only. ALERT_TEST_NO_BUILD=1 reuses existing images. `--down` removes the stack afterwards.
# Never run against a real prod host: it stops the database of the stack it started.
set -euo pipefail

cd "$(dirname "$0")/../.."

export COMPOSE_PROJECT_NAME=${ALERT_TEST_PROJECT:-fitwise-alerttest}
export HTTP_PORT=${ALERT_TEST_HTTP_PORT:-18088}
export GRAFANA_PORT=${ALERT_TEST_GRAFANA_PORT:-13030}
export OTLP_HTTP_PORT=${ALERT_TEST_OTLP_PORT:-14319}
export FLUENT_FORWARD_PORT=${ALERT_TEST_FLUENT_PORT:-24225}
STUB_PORT=${ALERT_TEST_STUB_PORT:-18099}
# Throwaway local-only values for a stack that lives in its own fresh volumes.
export APP_ENV=prod
export TAG=${TAG:-local}
export POSTGRES_PASSWORD=${ALERT_TEST_POSTGRES_PASSWORD:-alerttest-local-only}
export JWT_SECRET=${ALERT_TEST_JWT_SECRET:-alerttest-local-only-jwt-secret-0123456789abcdef}
export USER_HASH_SALT=${ALERT_TEST_USER_HASH_SALT:-alerttest-local-only-salt}
export SESSION_COOKIE_SECURE=false
export GRAFANA_ADMIN_USER=admin
export GRAFANA_ADMIN_PASSWORD=${ALERT_TEST_GRAFANA_PASSWORD:-alerttest-local-only}
export ONCALL_WEBHOOK_URL="http://host.docker.internal:${STUB_PORT}/alerts"
export ONCALL_WEBHOOK_USER=grafana
export ONCALL_WEBHOOK_PASSWORD=${ALERT_TEST_WEBHOOK_PASSWORD:-alerttest-local-only}

COMPOSE="docker compose -f compose.yaml -f compose.observability.yaml"
export COMPOSE

# Grafana can take several minutes to become healthy on a loaded machine: retry the wait.
build=--build; [[ -z "${ALERT_TEST_NO_BUILD:-}" ]] || build=
for attempt in 1 2 3 4; do
  $COMPOSE up $build --wait -d && break
  [[ $attempt -lt 4 ]] || { echo "stack did not become healthy" >&2; exit 1; }
  echo "stack not healthy yet (attempt $attempt), retrying" >&2
done

status=0
python3 -I observability/alert-test/driver.py \
  --app "http://127.0.0.1:${HTTP_PORT}" \
  --grafana "http://127.0.0.1:${GRAFANA_PORT}" \
  --stub-port "$STUB_PORT" \
  --out "${ALERT_TEST_OUT:-observability/alert-test/out}" \
  ${ALERT_TEST_ONLY:+--only "$ALERT_TEST_ONLY"} || status=$?

if [[ "${1:-}" == "--down" ]]; then
  $COMPOSE --profile test down --remove-orphans --volumes
fi
exit $status
