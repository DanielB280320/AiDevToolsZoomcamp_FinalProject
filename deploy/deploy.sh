#!/usr/bin/env bash
# Deploy one release on this host (issue #13; spec §12/§13, D50, ADR 0009/0010). Called by poll.sh.
#   deploy.sh <commit-sha> <backend-image@sha256:...> <frontend-image@sha256:...>
# Steps: store the release's compose files -> pull by digest -> migration one-shot (on its own; a
# failure stops here and the old release keeps serving) -> compose up -> health check (/readyz
# plus /healthz reporting this SHA) -> CURRENT_TAG / PREVIOUS_TAG. If the new release does not come
# up healthy, rollback.sh restores the release that was serving, without migrations.
# Exit: 0 deployed | 1 failed, the previous release is serving again (or was never touched)
#       2 failed and there was nothing to roll back to, or the rollback failed too
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$here/lib.sh"

sha="${1:?usage: deploy.sh <sha> <backend-image> <frontend-image>}"
backend_image="${2:?}"
frontend_image="${3:?}"
repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY not set}"
is_sha "$sha" || die "not a commit SHA: $sha"
image_re='^ghcr\.io/[a-z0-9._/-]+@sha256:[0-9a-f]{64}$'
[[ "$backend_image" =~ $image_re && "$frontend_image" =~ $image_re ]] ||
  die "image references must look like ghcr.io/<name>@sha256:<digest>"

exec 9>"$LOCK_FILE"
flock -w 600 9 || die "another deploy or rollback is running"
export FITWISE_LOCKED=1

cur="$(read_tag "$CURRENT_TAG_FILE")"
log "deploy: start $sha (current: ${cur:-none})"

# Compose files of exactly this commit (public repo; raw CDN, not part of the API rate limit).
dir="$RELEASES_DIR/$sha"
mkdir -p "$dir"
for f in compose.yaml deploy/compose.deploy.yaml; do
  curl -fsSL --retry 3 --retry-delay 2 --max-time 30 \
    "https://raw.githubusercontent.com/$repo/$sha/$f" -o "$dir/$(basename "$f")" ||
    { log "deploy: cannot fetch $f at $sha"; exit 1; }
done
printf 'BACKEND_IMAGE=%s\nFRONTEND_IMAGE=%s\n' "$backend_image" "$frontend_image" > "$dir/release.env"

log "deploy: pulling images by digest"
docker pull -q "$backend_image" >/dev/null || { log "deploy: pull of the backend image failed"; exit 1; }
docker pull -q "$frontend_image" >/dev/null || { log "deploy: pull of the frontend image failed"; exit 1; }

log "deploy: database up"
compose_release "$sha" up -d --no-deps --wait db || { log "deploy: database did not become healthy"; exit 1; }

log "deploy: migration step"
if ! compose_release "$sha" run --rm --no-TTY migrate; then
  log "deploy: MIGRATION FAILED; backend not started on $sha, the current release keeps serving"
  exit 1
fi

log "deploy: starting backend and frontend"
stop_placeholder
compose_release "$sha" up -d --no-deps --wait --wait-timeout 90 backend frontend ||
  log "deploy: compose up reported a failure"

if wait_healthy "$sha"; then
  if [ -n "$cur" ] && [ "$cur" != "$sha" ]; then write_state "$PREVIOUS_TAG_FILE" "$cur"; fi
  write_state "$CURRENT_TAG_FILE" "$sha"
  log "deploy: OK, serving $sha (previous: $(read_tag "$PREVIOUS_TAG_FILE"))"
  # Keep the five newest stored releases (the files are tiny; this only bounds growth).
  # shellcheck disable=SC2012
  ls -1t "$RELEASES_DIR" | tail -n +6 | while read -r old; do
    if [ "$old" != "$sha" ] && [ "$old" != "$cur" ]; then rm -rf "${RELEASES_DIR:?}/$old"; fi
  done
  exit 0
fi

log "deploy: $sha is NOT healthy within ${HEALTH_TIMEOUT_SECONDS}s; rolling back"
compose_release "$sha" logs --no-color --tail 15 backend 2>&1 | sed 's/^/  backend: /' || true
if [ -n "$cur" ]; then
  # CURRENT_TAG still names the release that was serving; PREVIOUS_TAG is not touched.
  if "$here/rollback.sh" "$cur"; then
    log "deploy: FAILED $sha, rolled back to $cur"
    exit 1
  fi
  log "deploy: FAILED $sha and the rollback to $cur failed too: manual action needed"
  exit 2
fi
log "deploy: FAILED $sha and there is no previous release; stopping it, restoring the placeholder"
compose_release "$sha" stop backend frontend || true
start_placeholder
exit 2
