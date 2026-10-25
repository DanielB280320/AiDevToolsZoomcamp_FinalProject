#!/usr/bin/env bash
# Start or refresh the observability containers on this host (issue #67; spec §12/§14, ADR 0006).
#   obs.sh [sha]      # as root; default: CURRENT_TAG. Called by deploy.sh after a healthy deploy.
# Needs OBS_MODE=full|forward in /opt/fitwise/.env (bootstrap.sh sets it; see lib.sh obs_mode).
#   full     prod: otel-collector, prometheus, loki, tempo, grafana (+ readiness probe)
#   forward  dev:  otel-collector only, exporting to the prod collector
# The configuration of the release commit (observability/) is downloaded from codeload (public repo,
# not part of the API rate limit) into /opt/fitwise/observability. When it changed the containers are
# recreated, otherwise left running. Telemetry is never allowed to fail a release: problems are logged
# and the script exits 0 for them (exit 1 only on a usage error).
# The stack survives a reboot: Docker starts at boot and every service has restart: unless-stopped.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$here/lib.sh"

sha="${1:-$(read_tag "$CURRENT_TAG_FILE")}"
is_sha "$sha" || die "obs: no release to attach to (pass a commit SHA or deploy first)"
mode="$(obs_mode)"
if [ -z "$mode" ]; then log "obs: OBS_MODE is off on this host; nothing to do"; exit 0; fi

if [ "${FITWISE_LOCKED:-}" != 1 ]; then
  exec 9>"$LOCK_FILE"
  flock -w 600 9 || die "another deploy or rollback is running"
fi

[ -f "$RELEASES_DIR/$sha/release.env" ] || die "obs: release $sha is not stored on this host"
fetch_obs_compose_files "$sha"
if [ ! -f "$RELEASES_DIR/$sha/compose.obs-$mode.yaml" ]; then
  log "obs: release $sha has no observability compose files (older than #67); skipping"
  exit 0
fi

# Configuration of exactly this commit.
repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY not set}"
tmp="$(mktemp -d "$APP_DIR/.obs.XXXXXX")"
trap 'rm -rf "$tmp"' EXIT
if ! curl -fsSL --retry 3 --retry-delay 2 --max-time 120 "https://codeload.github.com/$repo/tar.gz/$sha" |
     tar -xz -C "$tmp" --strip-components=1 --wildcards '*/observability'; then
  log "obs: cannot download the observability configuration of $sha; keeping what runs now"
  exit 0
fi
[ -d "$tmp/observability" ] || { log "obs: $sha has no observability/ directory"; exit 0; }
new_hash="$(cd "$tmp/observability" && find . -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -d' ' -f1)"
force=()
if [ "$new_hash" != "$(read_tag "$OBS_HASH_FILE")" ] || [ ! -d "$OBS_DIR" ]; then
  log "obs: configuration changed ($mode): containers will be recreated"
  rm -rf "$OBS_DIR.old"
  [ ! -d "$OBS_DIR" ] || mv "$OBS_DIR" "$OBS_DIR.old"
  mv "$tmp/observability" "$OBS_DIR"
  chmod -R a+rX "$OBS_DIR"          # containers run as non-root users
  rm -rf "$OBS_DIR.old"
  write_state "$OBS_HASH_FILE" "$new_hash"
  force=(--force-recreate)
fi

if [ "$mode" = full ]; then services=(otel-collector prometheus loki tempo grafana obs-probe)
else services=(otel-collector); fi
log "obs: starting ${services[*]} ($mode, release $sha)"
if compose_release "$sha" up -d --wait --wait-timeout 240 "${force[@]}" "${services[@]}"; then
  log "obs: OK ($mode)"
else
  # Forget the hash so the next run recreates and retries; the application keeps serving.
  rm -f "$OBS_HASH_FILE"
  log "obs: WARNING the observability stack did not become healthy; the application is not affected"
fi
exit 0
