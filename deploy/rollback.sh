#!/usr/bin/env bash
# Roll back a host to an earlier release (issue #13; spec §12/§13, D50, ADR 0010). One script for
# the poller's automatic rollback, the owner, CI and the on-call agent.
#   rollback.sh [sha]      # on the host, as root; default target: PREVIOUS_TAG
# Starts the target release's images (by the digests stored with it) WITHOUT the migration step:
# the older backend runs on the newer schema as it is (migrations are backward compatible).
# CURRENT_TAG becomes the target; PREVIOUS_TAG is left as it was (so after a rollback
# PREVIOUS_TAG == CURRENT_TAG). The release rolled back from is written to ROLLED_BACK_FROM (for incident
# reports; ROLLBACK_FROM overrides it, deploy.sh passes the failed release). The poller does not
# redeploy a rolled-back tag: it acts again only when the approved ref moves.
# A rollback WITHOUT an argument (on-call) is refused when it would go nowhere or back to the release
# that was just rolled back from; going forward again is "Promote to production" (#122, D66).
# Exit: 0 rolled back and healthy | 1 failed | 3 nothing to roll back to (PREVIOUS_TAG empty or equal
#       to CURRENT_TAG) | 4 refused: the target is the release that was rolled back from
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$here/lib.sh"

if [ "${FITWISE_LOCKED:-}" != 1 ]; then
  exec 9>"$LOCK_FILE"
  flock -w 600 9 || die "another deploy or rollback is running"
fi

explicit="${1:-}"
target="${1:-$(read_tag "$PREVIOUS_TAG_FILE")}"
cur="$(read_tag "$CURRENT_TAG_FILE")"
if [ -z "$target" ]; then
  log "rollback: PREVIOUS_TAG is empty, nothing to roll back to"
  exit 3
fi
is_sha "$target" || die "rollback: target is not a commit SHA"
if [ -z "$explicit" ]; then
  if [ "$target" = "$cur" ]; then
    log "rollback: refused: PREVIOUS_TAG equals CURRENT_TAG ($target), nothing earlier to go back to; escalate to the owner (a fix goes out through 'Promote to production')"
    exit 3
  fi
  if [ "$target" = "$(read_tag "$ROLLED_BACK_FROM_FILE")" ]; then
    log "rollback: refused: $target is the release that was rolled back from (known bad); escalate to the owner"
    exit 4
  fi
fi
from="${ROLLBACK_FROM:-$cur}"
if [ -n "$from" ] && ! is_sha "$from"; then from=""; fi

log "rollback: ${cur:-none} -> $target (migrations skipped)"
stop_placeholder
compose_release "$target" up -d --no-deps --wait --wait-timeout 90 backend frontend ||
  log "rollback: compose up of $target reported a failure"
if wait_healthy "$target"; then
  write_state "$CURRENT_TAG_FILE" "$target"
  if [ -n "$from" ] && [ "$from" != "$target" ]; then write_state "$ROLLED_BACK_FROM_FILE" "$from"; fi
  log "rollback: done, serving $target"
else
  log "ERROR rollback: $target did not become healthy"
  exit 1
fi
