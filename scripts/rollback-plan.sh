#!/usr/bin/env bash
# Which release does "Rollback production" go back to? (issue #113; spec §13, D50, D57, D58)
#   GITHUB_REPOSITORY=<owner/repo> [SERVED=<version from prod /healthz>] scripts/rollback-plan.sh
# CI has no access to the host, so the previous release is read from what CI CAN read: the history of
# the ref `deploy/prod`. Every promotion (and every rollback) adds one deploy commit whose message is the
# release record (source / backend / frontend). Newest first, that history is the order in which releases
# were approved for prod.
#   current  = SERVED (what prod's /healthz reports) when given, else the newest record's source.
#   target   = the next OLDER record whose source differs from current.
# Using what prod really serves (not the ref head) matters when the newest promotion failed and the host
# rolled itself back: the ref head is then the failed release, the host serves the one before it, and the
# rollback must go to the release before THAT. If SERVED is given but is not in the history, the script
# refuses (it will not guess).
# Prints the plan; with $GITHUB_OUTPUT set, writes current_sha, target_sha, backend_image, frontend_image.
# Exit 1 (before anything is moved) when there is no previous release. Read-only: never touches a ref.
set -euo pipefail

repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY not set}"
served="${SERVED:-}"
fail() { echo "::error::cannot roll back production: $*" >&2; exit 1; }
[ -z "$served" ] || [[ "$served" =~ ^[0-9a-f]{40}$ ]] || fail "prod /healthz reports a version that is not a commit SHA ('${served:0:20}')"

json="$(gh api "repos/$repo/commits?sha=deploy/prod&per_page=50")" || fail "cannot read the history of deploy/prod"
field() { printf '%s\n' "$1" | sed -n "s/^$2: *//p" | head -n1 | tr -d '\r'; }

srcs=(); backs=(); fronts=()
while IFS= read -r b64; do
  msg="$(printf '%s' "$b64" | base64 -d)"
  s="$(field "$msg" source)"
  [[ "$s" =~ ^[0-9a-f]{40}$ ]] || continue   # the initial README commit carries no release
  srcs+=("$s"); backs+=("$(field "$msg" backend)"); fronts+=("$(field "$msg" frontend)")
done < <(printf '%s' "$json" | jq -r '.[].commit.message | @base64')

[ "${#srcs[@]}" -gt 0 ] || fail "deploy/prod has no release record: nothing was ever promoted, so there is nothing to roll back to"
current="${served:-${srcs[0]}}"

start=-1
for i in "${!srcs[@]}"; do if [ "${srcs[$i]}" = "$current" ]; then start=$i; break; fi; done
[ "$start" -ge 0 ] || fail "prod serves ${current:0:12}, which is not in the deploy/prod history; refusing to guess"

t=-1
for ((i = start + 1; i < ${#srcs[@]}; i++)); do if [ "${srcs[$i]}" != "$current" ]; then t=$i; break; fi; done
[ "$t" -ge 0 ] || fail "no previous release: ${current:0:12} is the first release ever promoted to prod (the host keeps its current tag; rollback.sh would exit 3). Nothing was moved"

target="${srcs[$t]}"; backend="${backs[$t]}"; frontend="${fronts[$t]}"
owner_lc="$(tr '[:upper:]' '[:lower:]' <<<"${repo%%/*}")"
re_for() { echo "^ghcr\\.io/${owner_lc//./\\.}/fitwise-$1@sha256:[0-9a-f]{64}\$"; }
[[ "$backend" =~ $(re_for backend) ]] || fail "the release record of ${target:0:12} has no valid backend digest reference"
[[ "$frontend" =~ $(re_for frontend) ]] || fail "the release record of ${target:0:12} has no valid frontend digest reference"

echo "rollback plan: ${current} -> ${target}"
echo "backend: $backend"; echo "frontend: $frontend"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  { echo "current_sha=$current"; echo "target_sha=$target"; echo "backend_image=$backend"; echo "frontend_image=$frontend"; } >> "$GITHUB_OUTPUT"
fi
