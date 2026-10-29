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
# Only a release that was GOOD on prod is a target (issue #122, D67). A record is good when the run that
# wrote it ("Promote to production" or "Rollback production", named by the `run:` line of the record)
# finished successfully, which means its last job (prod serves the SHA, readyz, e2e smoke) passed;
# looked up with the workflow's GITHUB_TOKEN (actions: read). A release that failed on the host and was
# rolled back automatically has a failed run, so it is skipped. Records from before the `run:` line
# existed are good only if listed in deploy/legacy-good-releases.txt (override: LEGACY_GOOD_FILE).
# If no earlier good release exists the plan fails; it never picks an unverified one.
# Prints the plan; with $GITHUB_OUTPUT set, writes current_sha, target_sha, backend_image, frontend_image.
# Exit 1 (before anything is moved) when there is no previous release. Read-only: never touches a ref.
set -euo pipefail

repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY not set}"
served="${SERVED:-}"
fail() { echo "::error::cannot roll back production: $*" >&2; exit 1; }
[ -z "$served" ] || [[ "$served" =~ ^[0-9a-f]{40}$ ]] || fail "prod /healthz reports a version that is not a commit SHA ('${served:0:20}')"

json="$(gh api "repos/$repo/commits?sha=deploy/prod&per_page=50")" || fail "cannot read the history of deploy/prod"
field() { printf '%s\n' "$1" | sed -n "s/^$2: *//p" | head -n1 | tr -d '\r'; }

srcs=(); backs=(); fronts=(); runs=()
while IFS= read -r b64; do
  msg="$(printf '%s' "$b64" | base64 -d)"
  s="$(field "$msg" source)"
  [[ "$s" =~ ^[0-9a-f]{40}$ ]] || continue   # the initial README commit carries no release
  srcs+=("$s"); backs+=("$(field "$msg" backend)"); fronts+=("$(field "$msg" frontend)")
  r="$(field "$msg" run)"; [[ "$r" =~ ^[0-9]{1,20}$ ]] || r=""; runs+=("$r")
done < <(printf '%s' "$json" | jq -r '.[].commit.message | @base64')

[ "${#srcs[@]}" -gt 0 ] || fail "deploy/prod has no release record: nothing was ever promoted, so there is nothing to roll back to"
current="${served:-${srcs[0]}}"

start=-1
for i in "${!srcs[@]}"; do if [ "${srcs[$i]}" = "$current" ]; then start=$i; break; fi; done
[ "$start" -ge 0 ] || fail "prod serves ${current:0:12}, which is not in the deploy/prod history; refusing to guess"

legacy_file="${LEGACY_GOOD_FILE:-$(dirname "$0")/../deploy/legacy-good-releases.txt}"
is_legacy_good() { [ -r "$legacy_file" ] && sed 's/#.*//; s/[[:space:]]//g' "$legacy_file" | grep -qx "$1"; }
# good_record <index>: 0 when the record was verified good on prod (see the header).
good_record() {
  local run="${runs[$1]}" info
  if [ -z "$run" ]; then is_legacy_good "${srcs[$1]}"; return; fi
  info="$(gh api "repos/$repo/actions/runs/$run" --jq '[.path, .conclusion, .head_branch] | @tsv' 2>/dev/null)" || return 1
  case "$info" in
    ".github/workflows/promote-prod.yml"*$'\t'success$'\t'main | ".github/workflows/rollback-prod.yml"*$'\t'success$'\t'main) return 0 ;;
  esac
  return 1
}

t=-1; seen_other=0; skipped=()
for ((i = start + 1; i < ${#srcs[@]}; i++)); do
  [ "${srcs[$i]}" != "$current" ] || continue
  seen_other=1
  if good_record "$i"; then t=$i; break; fi
  skipped+=("${srcs[$i]:0:12}")
done
if [ "$t" -lt 0 ]; then
  [ "$seen_other" = 1 ] || fail "no previous release: ${current:0:12} is the first release ever promoted to prod (the host keeps its current tag; rollback.sh would exit 3). Nothing was moved"
  fail "no earlier release was verified good on prod (skipped, unverified or failed: ${skipped[*]}); refusing to pick one. Roll forward with 'Promote to production' or decide with the owner. Nothing was moved"
fi
[ "${#skipped[@]}" -eq 0 ] || echo "skipped (not verified good on prod): ${skipped[*]}"

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
