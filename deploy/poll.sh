#!/usr/bin/env bash
# Poll the approved-release ref and deploy when it moved (issue #13; ADR 0010, spec D57).
# Run by fitwise-deploy.timer every 150 s as root. No GitHub credentials: the repository is public.
#
# The ref `deploy/<env>` (a branch, moved only by the workflow's GITHUB_TOKEN) points at a deploy
# commit whose message carries the release:
#     deploy dev <sha>
#     source: <40-hex commit sha of main>
#     backend: ghcr.io/<owner>/fitwise-backend@sha256:<digest>
#     frontend: ghcr.io/<owner>/fitwise-frontend@sha256:<digest>
# One request per poll: GET /repos/<repo>/branches/deploy/<env> with If-None-Match (a 304 costs
# no parsing and no deploy). 24 polls per hour; a deploy adds none (compose files come from the
# raw CDN, images from GHCR). That stays far below the 60 requests per hour per IP limit.
#
# A ref object is attempted at most once (LAST_REF): a failed or rolled-back release is never
# retried, and a manual rollback.sh is not undone. The poller acts again only when the ref moves.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$here/lib.sh"

repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY not set}"
env_name="${DEPLOY_ENV:?DEPLOY_ENV not set}"
image_ns="${IMAGE_NAMESPACE:?IMAGE_NAMESPACE not set}"   # e.g. ghcr.io/danielb280320/
etag_file="$APP_DIR/POLL_ETAG"
last_ref_file="$APP_DIR/LAST_REF"
api="${GITHUB_API:-https://api.github.com}"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

args=(-sS --max-time 20 -o "$work/body" -D "$work/headers" -w '%{http_code}'
  -H 'Accept: application/vnd.github+json' -H 'X-GitHub-Api-Version: 2022-11-28'
  -H 'User-Agent: fitwise-deploy-poller')
if [ -s "$etag_file" ]; then args+=(-H "If-None-Match: $(cat "$etag_file")"); fi

code="$(curl "${args[@]}" "$api/repos/$repo/branches/deploy/$env_name" || true)"
remaining="$(grep -i '^x-ratelimit-remaining:' "$work/headers" 2>/dev/null | tr -d '\r' | awk '{print $2}' || true)"

case "$code" in
  304) exit 0 ;;                                   # nothing moved (quiet: this is the common case)
  200) ;;
  404) log "poll: ref deploy/$env_name does not exist yet"; exit 0 ;;
  403|429) log "poll: rate limited by GitHub (HTTP $code, remaining ${remaining:-?}); will retry next interval"; exit 0 ;;
  *)   log "poll: GitHub API unreachable or unexpected (HTTP ${code:-none}); keeping the current release"; exit 0 ;;
esac

etag="$(grep -i '^etag:' "$work/headers" | tr -d '\r' | sed 's/^[^:]*: *//' || true)"
if ! jq -e . "$work/body" >/dev/null 2>&1; then log "poll: unexpected payload (not JSON)"; exit 0; fi
ref_sha="$(jq -r '.commit.sha // empty' "$work/body" 2>/dev/null || true)"
message="$(jq -r '.commit.commit.message // empty' "$work/body" 2>/dev/null || true)"
is_sha "$ref_sha" || { log "poll: unexpected ref payload"; exit 0; }

if [ -n "$etag" ]; then printf '%s\n' "$etag" > "$etag_file"; fi
if [ "$ref_sha" = "$(read_tag "$last_ref_file")" ]; then exit 0; fi   # already attempted this ref value

# Parse and validate the release record. Anything unexpected is refused, never executed.
field() { printf '%s\n' "$message" | sed -n "s/^$1: *//p" | head -n1 | tr -d '\r'; }
sha="$(field source)"; backend="$(field backend)"; frontend="$(field frontend)"
image_re="^${image_ns//./\\.}fitwise-(backend|frontend)@sha256:[0-9a-f]{64}\$"
printf '%s\n' "$ref_sha" > "$last_ref_file"      # recorded BEFORE deploying: never retried
if ! is_sha "$sha" || ! [[ "$backend" =~ $image_re ]] || ! [[ "$frontend" =~ $image_re ]]; then
  log "poll: ref ${ref_sha:0:12} carries no valid release record; ignored"
  exit 0
fi

if [ "$sha" = "$(read_tag "$CURRENT_TAG_FILE")" ]; then
  log "poll: $sha is already the current release"
  exit 0
fi

log "poll: deploy/$env_name moved to ${ref_sha:0:12}: release $sha (rate-limit remaining ${remaining:-?})"
# "Rollback production" (#113) moves the ref back to the release that served before. That release is
# PREVIOUS_TAG and is stored on this host, so it is started by rollback.sh: no migration step (D50;
# its schema is already applied, and an older image must never run `alembic upgrade` on a newer
# database). Any other release goes through the normal deploy.
if [ "$sha" = "$(read_tag "$PREVIOUS_TAG_FILE")" ] && [ -f "$RELEASES_DIR/$sha/release.env" ]; then
  log "poll: $sha is PREVIOUS_TAG: rolling back without the migration step"
  exec "$here/rollback.sh" "$sha"
fi
exec "$here/deploy.sh" "$sha" "$backend" "$frontend"
