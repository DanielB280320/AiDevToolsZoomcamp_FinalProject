#!/usr/bin/env bash
# Shared helpers for the host-side deploy scripts (issue #13, ADR 0010). Sourced, not executed.
# Runs as root on the host from /opt/fitwise/bin. Prints timestamped lines to stdout (journald).
# NEVER prints the contents of /opt/fitwise/.env, request headers or tokens: only tags, digests
# and statuses.

APP_DIR="${APP_DIR:-/opt/fitwise}"
ENV_FILE="$APP_DIR/.env"
RELEASES_DIR="$APP_DIR/releases"
CURRENT_TAG_FILE="$APP_DIR/CURRENT_TAG"
PREVIOUS_TAG_FILE="$APP_DIR/PREVIOUS_TAG"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:80/api/v1}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-120}"
LOCK_FILE="${LOCK_FILE:-/run/fitwise-deploy.lock}"

log() { printf '%s fitwise-deploy: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

is_sha() { [[ "${1:-}" =~ ^[0-9a-f]{40}$ ]]; }

read_tag() { if [ -s "$1" ]; then tr -d '[:space:]' < "$1"; fi; }

# Atomic single-line state file.
write_state() { printf '%s\n' "$2" > "$1.tmp" && mv -f "$1.tmp" "$1"; }

# compose_release <sha> <compose args...>: docker compose for a stored release, images by digest.
compose_release() {
  local sha="$1"; shift
  local dir="$RELEASES_DIR/$sha"
  [ -f "$dir/release.env" ] || die "release $sha is not stored on this host"
  (
    set -a
    # shellcheck disable=SC1091
    . "$dir/release.env"
    set +a
    export TAG="$sha" HTTP_BIND=0.0.0.0 HTTP_PORT=80 COMPOSE_PROJECT_NAME=fitwise
    cd "$dir"
    docker compose --env-file "$ENV_FILE" -f compose.yaml -f compose.deploy.yaml "$@"
  )
}

# wait_healthy <sha>: /readyz is 200 and /healthz reports exactly this release, within the timeout.
wait_healthy() {
  local sha="$1" deadline=$((SECONDS + HEALTH_TIMEOUT_SECONDS)) body
  while [ "$SECONDS" -lt "$deadline" ]; do
    if curl -fsS --max-time 5 -o /dev/null "$HEALTH_URL/readyz" 2>/dev/null &&
       body="$(curl -fsS --max-time 5 "$HEALTH_URL/healthz" 2>/dev/null)" &&
       [ "$(printf '%s' "$body" | jq -r '.version // empty' 2>/dev/null)" = "$sha" ]; then
      return 0
    fi
    sleep 3
  done
  return 1
}

# Port 80 is held by the bootstrap placeholder until the first real deploy.
stop_placeholder() { docker rm -f fitwise-placeholder >/dev/null 2>&1 || true; }
start_placeholder() { docker start fitwise-placeholder >/dev/null 2>&1 || true; }
