#!/usr/bin/env bash
# Shared helpers for the host-side deploy scripts (issue #13, ADR 0010). Sourced, not executed.
# Runs as root on the host from /opt/fitwise/bin. Prints timestamped lines to stdout (journald).
# NEVER prints the contents of /opt/fitwise/.env, request headers or tokens: only tags, digests
# and statuses.

# Poller settings (GITHUB_REPOSITORY, DEPLOY_ENV, IMAGE_NAMESPACE) come from /etc/fitwise-deploy.env,
# which only the systemd unit loads. When a script is run by hand (sudo /opt/fitwise/bin/obs.sh) the
# variables are unset, so read them from that file here (issue #120). Variables already set win; the
# file is parsed line by line (KEY=value, only these keys), never executed. No secrets in it.
DEPLOY_ENV_FILE="${DEPLOY_ENV_FILE:-/etc/fitwise-deploy.env}"
load_deploy_env() {
  local key value
  [ -r "$DEPLOY_ENV_FILE" ] || return 0
  for key in GITHUB_REPOSITORY DEPLOY_ENV IMAGE_NAMESPACE; do
    [ -z "${!key:-}" ] || continue
    value="$(sed -n "s/^$key=//p" "$DEPLOY_ENV_FILE" | head -n1)"
    [ -z "$value" ] || export "$key=$value"
  done
  return 0
}
load_deploy_env

APP_DIR="${APP_DIR:-/opt/fitwise}"
ENV_FILE="$APP_DIR/.env"
RELEASES_DIR="$APP_DIR/releases"
CURRENT_TAG_FILE="$APP_DIR/CURRENT_TAG"
PREVIOUS_TAG_FILE="$APP_DIR/PREVIOUS_TAG"
ROLLED_BACK_FROM_FILE="$APP_DIR/ROLLED_BACK_FROM"   # release last rolled back from (#122, D67)
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:80/api/v1}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-120}"
LOCK_FILE="${LOCK_FILE:-/run/fitwise-deploy.lock}"

log() { printf '%s fitwise-deploy: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

is_sha() { [[ "${1:-}" =~ ^[0-9a-f]{40}$ ]]; }

read_tag() { if [ -s "$1" ]; then tr -d '[:space:]' < "$1"; fi; }

# Atomic single-line state file.
write_state() { printf '%s\n' "$2" > "$1.tmp" && mv -f "$1.tmp" "$1"; }

# --- Observability on the host (issue #67; spec §12/§14, ADR 0006) ------------------------------
# OBS_MODE in the root-only env file selects what runs next to the app (set by bootstrap.sh):
#   full     prod: collector, Prometheus, Loki, Tempo, Grafana (compose.obs-full.yaml)
#   forward  dev: only the collector, exporting OTLP/gRPC to the prod collector (compose.obs-forward.yaml)
# Unset or incomplete (no Grafana password / no upstream endpoint) = off, so a half-configured host
# never breaks the app deploy. The observability configuration lives in $OBS_DIR, refreshed by obs.sh.
OBS_DIR="${OBS_DIR:-$APP_DIR/observability}"
OBS_HASH_FILE="$APP_DIR/OBS_CONFIG_HASH"
OBS_COMPOSE_FILES=(compose.observability.yaml compose.obs-full.yaml compose.obs-forward.yaml)

# env_has <KEY>: true when the env file has a non-empty KEY=value line. The value is never printed.
env_has() { [ -r "$ENV_FILE" ] && grep -Eq "^$1=.+" "$ENV_FILE"; }
env_is() { [ -r "$ENV_FILE" ] && grep -qx "$1=$2" "$ENV_FILE"; }

# obs_mode: prints full | forward, or nothing when observability is off or incomplete.
obs_mode() {
  if env_is OBS_MODE full && env_has GRAFANA_ADMIN_PASSWORD; then echo full
  elif env_is OBS_MODE forward && env_has GRAFANA_ADMIN_PASSWORD && env_has OTLP_UPSTREAM_ENDPOINT; then echo forward
  elif env_has OBS_MODE; then log "observability: OBS_MODE is set but incomplete or invalid (needs GRAFANA_ADMIN_PASSWORD, and OTLP_UPSTREAM_ENDPOINT for forward): off" >&2
  fi
  return 0
}

# fetch_obs_compose_files <sha>: the observability compose files of that commit, best effort (a commit
# that predates #67 has none; then the release simply runs without them).
fetch_obs_compose_files() {
  local sha="$1" repo="${GITHUB_REPOSITORY:?}" f dest dir="$RELEASES_DIR/$1"
  for f in compose.observability.yaml deploy/compose.obs-full.yaml deploy/compose.obs-forward.yaml; do
    dest="$dir/$(basename "$f")"
    curl -fsSL --retry 3 --retry-delay 2 --max-time 30 \
      "https://raw.githubusercontent.com/$repo/$sha/$f" -o "$dest.tmp" 2>/dev/null && mv -f "$dest.tmp" "$dest" || rm -f "$dest.tmp" "$dest"
  done
  return 0
}

# compose_release <sha> <compose args...>: docker compose for a stored release, images by digest.
# With OBS_MODE on, the release's observability files are layered on top (backend exports to the
# collector); a release without them runs as before.
compose_release() {
  local sha="$1"; shift
  local dir="$RELEASES_DIR/$sha" files=(-f compose.yaml -f compose.deploy.yaml) mode
  [ -f "$dir/release.env" ] || die "release $sha is not stored on this host"
  mode="$(obs_mode)"
  if [ -n "$mode" ] && [ -f "$dir/compose.observability.yaml" ] && [ -f "$dir/compose.obs-$mode.yaml" ]; then
    files+=(-f compose.observability.yaml -f "compose.obs-$mode.yaml")
  fi
  (
    set -a
    # shellcheck disable=SC1091
    . "$dir/release.env"
    set +a
    export TAG="$sha" HTTP_BIND=0.0.0.0 HTTP_PORT=80 COMPOSE_PROJECT_NAME=fitwise OBS_CONFIG_DIR="$OBS_DIR"
    cd "$dir"
    docker compose --progress quiet --env-file "$ENV_FILE" "${files[@]}" "$@"
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

# demo_health_fail: true only while /opt/fitwise/.env contains the line FITWISE_DEMO_FAIL_HEALTH=1.
# Temporary switch for the prod auto-rollback demo (#14, D61): deploy.sh then treats the post-deploy
# health check as failed, so the normal rollback path runs. Off unless that exact line exists
# (default absent, on every host). rollback.sh never consults it. Only the match result is used:
# the file is never printed.
demo_health_fail() { [ -r "$ENV_FILE" ] && grep -qx 'FITWISE_DEMO_FAIL_HEALTH=1' "$ENV_FILE"; }

# Port 80 is held by the bootstrap placeholder until the first real deploy.
stop_placeholder() { docker rm -f fitwise-placeholder >/dev/null 2>&1 || true; }
start_placeholder() { docker start fitwise-placeholder >/dev/null 2>&1 || true; }
