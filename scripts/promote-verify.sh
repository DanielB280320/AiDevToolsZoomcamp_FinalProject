#!/usr/bin/env bash
# Is <sha> proven on dev, and which images did dev run? (issue #14; spec §13, D58)
#   GITHUB_REPOSITORY=<owner/repo> scripts/promote-verify.sh <40-hex sha>
# "Proven on dev" = the ci.yml run on main (push) for that SHA has the jobs deploy-dev and
# smoke-dev concluded `success`. Exit 0 and print `backend:` / `frontend:` lines (the dev release
# record: image references with @sha256 digests); also appended to $GITHUB_OUTPUT when set.
# Exit 1 with a reason otherwise. Read-only: it never touches a ref. Needs gh (+ sed), `actions: read`.
#
# Where the digests come from: the `release-record` artifact the publish job uploads. Releases
# that predate the artifact fall back to the deploy/dev ref when it still carries that release.
set -euo pipefail

sha="${1:-}"
repo="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY not set}"
DEPLOY_DEV_JOB="${DEPLOY_DEV_JOB:-Approve release for dev (move deploy/dev)}"   # names in ci.yml
SMOKE_DEV_JOB="${SMOKE_DEV_JOB:-Dev serves this SHA, then e2e smoke}"
fail() { echo "::error::cannot promote ${sha:-<none>}: $*" >&2; exit 1; }

[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || fail "the input must be a full 40-character lowercase commit SHA"

runs="$(gh api "repos/$repo/actions/workflows/ci.yml/runs?head_sha=$sha&branch=main&event=push&per_page=20" \
  --jq '[.workflow_runs[] | {id, created_at}] | sort_by(.created_at) | reverse | .[].id')"
[ -n "$runs" ] || fail "no ci.yml run on main for this SHA (unknown SHA, or it never reached main)"

proven_run=""; reasons=""
for id in $runs; do
  conclusion() { # job name -> its conclusion in the latest attempt of run $id, or "missing"
    gh api "repos/$repo/actions/runs/$id/jobs?filter=latest&per_page=100" \
      --jq "[.jobs[] | select(.name == \"$1\") | .conclusion] | first // \"missing\""
  }
  dd="$(conclusion "$DEPLOY_DEV_JOB")"; sd="$(conclusion "$SMOKE_DEV_JOB")"
  if [ "$dd" = success ] && [ "$sd" = success ]; then proven_run="$id"; break; fi
  reasons="$reasons run $id: deploy-dev=$dd smoke-dev=$sd;"
done
[ -n "$proven_run" ] || fail "dev deploy is not proven (need deploy-dev and smoke-dev = success).$reasons"
echo "dev proven by ci.yml run $proven_run"

record=""
dir="$(mktemp -d)"; trap 'rm -rf "$dir"' EXIT
if gh run download "$proven_run" --repo "$repo" -n release-record -D "$dir" >/dev/null 2>&1 && [ -s "$dir/release-record.txt" ]; then
  record="$(cat "$dir/release-record.txt")"
else
  msg="$(gh api "repos/$repo/branches/deploy/dev" --jq .commit.commit.message 2>/dev/null || true)"
  if [ "$(printf '%s\n' "$msg" | sed -n 's/^source: *//p' | head -n1)" = "$sha" ]; then record="$msg"; fi
fi
[ -n "$record" ] || fail "no release record (image digests) found for this SHA"

field() { printf '%s\n' "$record" | sed -n "s/^$1: *//p" | head -n1 | tr -d '\r'; }
backend="$(field backend)"; frontend="$(field frontend)"
owner_lc="$(tr '[:upper:]' '[:lower:]' <<<"${repo%%/*}")"
re_for() { echo "^ghcr\\.io/${owner_lc//./\\.}/fitwise-$1@sha256:[0-9a-f]{64}\$"; }
[[ "$backend" =~ $(re_for backend) ]] || fail "backend image reference is not a digest reference of this repo's GHCR package"
[[ "$frontend" =~ $(re_for frontend) ]] || fail "frontend image reference is not a digest reference of this repo's GHCR package"

echo "backend: $backend"; echo "frontend: $frontend"
if [ -n "${GITHUB_OUTPUT:-}" ]; then { echo "backend_image=$backend"; echo "frontend_image=$frontend"; } >> "$GITHUB_OUTPUT"; fi
