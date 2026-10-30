#!/usr/bin/env bash
# Rollback compatibility guard (issue #82; spec §11, §13; D50, ADR 0009).
#
#   make rollback-compat [PREV_REF=<git ref>]      # CI: PREV_REF=HEAD^1 (the PR's base)
#   scripts/rollback-compat.sh [PREV_REF]
#
# Builds the backend image N from the working tree and the previous release's image N-1 from
# PREV_REF (default: merge-base of HEAD and origin/main). Then, in a throwaway Compose project
# with no published ports:
#
#   0. N-1 schema: `alembic upgrade head` from image N-1 (any release can do that).
#   A. Forward deploy of N, the documented way (compose.yaml, `migrate` service):
#        TAG=N docker compose run --rm migrate && TAG=N docker compose up -d --no-deps --wait backend
#      -> the step runs from image N and exits 0, then the backend becomes healthy; readyz 200
#         and the schema is at N's head.
#   B. Rollback to N-1, the documented way:
#        TAG=N-1 docker compose up -d --no-deps --wait backend
#      -> the migration step does NOT run; readyz 200 with migrations ok; alembic_version is
#         still N's head (no down-migration).
#   C. Image N on a newer schema (simulated N+1 revision), the rollback way, then
#      `docker compose restart backend` -> readyz 200; alembic_version untouched. This fails as
#      soon as the backend start path migrates again, even in a PR that adds no migration.
#
# Set NEW_REF to build image N from a git ref instead of the working tree.
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE=${COMPOSE:-docker compose}
PREV_REF=${1:-${PREV_REF:-}}
NEW_REF=${NEW_REF:-}
if [[ -z "$PREV_REF" ]]; then
  PREV_REF=$(git merge-base HEAD origin/main)
fi
prev_sha=$(git rev-parse --verify --quiet "${PREV_REF}^{commit}") ||
  { echo "rollback-compat: unknown PREV_REF '$PREV_REF'" >&2; exit 2; }

run_id="$$-$RANDOM"
project="fitwise-rollback-compat-${run_id}"
prefix="fitwise-rollback-compat"
new_tag="new-${run_id}"
prev_tag="prev-${run_id}"
fake_newer="ffffffff0082" # stands for a revision shipped by a newer release (N+1)

# Placeholder local-only values from .env.example; the shell values below take precedence.
dc() { IMAGE_PREFIX="$prefix" $COMPOSE -p "$project" --env-file .env.example "$@"; }
step() { printf '\n== %s\n' "$*"; }
fail() {
  echo "rollback-compat: FAILED: $*" >&2
  dc logs --no-color --tail 60 migrate backend >&2 || true
  exit 1
}
cleanup() {
  dc down --volumes --remove-orphans >/dev/null 2>&1 || true
  docker image rm "$prefix-backend:$new_tag" "$prefix-backend:$prev_tag" >/dev/null 2>&1 || true
}
trap cleanup EXIT

build_from_ref() { # <ref> <tag>
  git archive --format=tar "$1:backend" | docker build --quiet -t "$prefix-backend:$2" - >/dev/null
}

psql_db() {
  dc exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -qtA -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' sh "$1"
}
db_versions() { psql_db "SELECT string_agg(version_num, ',' ORDER BY version_num) FROM alembic_version"; }

image_heads() { # <tag>: this image's Alembic heads, comma separated and sorted
  docker run --rm --entrypoint python "$prefix-backend:$1" -c \
    "from app.migrations import load_migration_scripts as l; print(','.join(sorted(l().heads)))"
}

readyz() { # prints "<status> <body>" from inside the backend container
  dc exec -T backend python -c '
import urllib.error, urllib.request
try:
    r = urllib.request.urlopen("http://127.0.0.1:8000/api/v1/readyz", timeout=5)
    print(r.status, r.read().decode())
except urllib.error.HTTPError as e:
    print(e.code, e.read().decode())
'
}
expect_ready() {
  local got
  got=$(readyz)
  echo "   readyz: $got"
  [[ "$got" == '200 {"status":"ok","checks":{"database":"ok","migrations":"ok"}}' ]] ||
    fail "$1: readyz is not 200/migrations ok"
}
# Any container of the `migrate` service, from `up` or `run`, running or exited.
migrate_containers() {
  docker ps -a -q --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.service=migrate"
}

step "Build image N ($([[ -n $NEW_REF ]] && git rev-parse --short "$NEW_REF" || echo 'working tree')) and N-1 ($(git rev-parse --short "$prev_sha"))"
if [[ -n "$NEW_REF" ]]; then
  build_from_ref "$NEW_REF" "$new_tag"
else
  docker build --quiet -t "$prefix-backend:$new_tag" backend >/dev/null
fi
build_from_ref "$prev_sha" "$prev_tag"
new_heads=$(image_heads "$new_tag")
prev_heads=$(image_heads "$prev_tag")
echo "   N heads: $new_heads   N-1 heads: $prev_heads"

step "0. Database at N-1's schema (alembic upgrade head from image N-1)"
TAG=$prev_tag dc up -d --wait db
TAG=$prev_tag dc run --rm --no-deps -T migrate alembic upgrade head >/dev/null 2>&1 ||
  fail "image N-1 could not migrate an empty database"
[[ "$(db_versions)" == "$prev_heads" ]] || fail "schema is not at N-1's head"
echo "   alembic_version: $(db_versions)"

step "A. Forward deploy N: TAG=N docker compose run --rm migrate && ... up -d --no-deps --wait backend"
TAG=$new_tag dc run --rm -T migrate || fail "the migration step from image N did not exit 0"
[[ "$(db_versions)" == "$new_heads" ]] || fail "schema is not at N's head after the migration step"
TAG=$new_tag dc up -d --no-deps --wait --wait-timeout 300 backend ||
  fail "forward deploy did not become healthy"
echo "   alembic_version: $(db_versions)"
expect_ready "forward deploy"

step "B. Rollback to N-1: TAG=N-1 docker compose up -d --no-deps --wait backend"
TAG=$prev_tag dc up -d --no-deps --wait --wait-timeout 300 backend ||
  fail "rollback: the previous image's backend did not become healthy on N's schema"
[[ "$(docker inspect --format '{{.Config.Image}}' "$(dc ps -q backend)")" == "$prefix-backend:$prev_tag" ]] ||
  fail "rollback did not start image N-1"
[[ -z "$(migrate_containers)" ]] || fail "rollback ran the migration step"
[[ "$(db_versions)" == "$new_heads" ]] || fail "rollback changed alembic_version (down-migration?)"
echo "   alembic_version: $(db_versions) (unchanged)"
expect_ready "rollback"
echo "   core writes by image N-1 on N's schema (any 5xx fails):"
dc exec -T backend python -I - <scripts/rollback-compat-writes.py ||
  fail "rollback: the previous image cannot perform its core writes on N's schema"
# Rule 6: the synthetic account's address must not appear in the backend logs.
if dc logs --no-color backend 2>&1 | grep -q 'rollback-[0-9a-f]*@example\.com'; then
  fail "rollback: the synthetic account's email reached the backend logs"
fi

step "C. Image N on a newer schema ($fake_newer), the rollback way, then a restart"
psql_db "UPDATE alembic_version SET version_num = '$fake_newer'" >/dev/null
TAG=$new_tag dc up -d --no-deps --wait --wait-timeout 300 backend ||
  fail "image N does not start on a newer schema: its start path must not migrate (D50)"
expect_ready "image N on a newer schema"
TAG=$new_tag dc restart backend >/dev/null
TAG=$new_tag dc up -d --no-deps --wait --wait-timeout 300 backend >/dev/null ||
  fail "image N did not come back after a restart"
[[ "$(db_versions)" == "$fake_newer" ]] || fail "a backend restart changed alembic_version"
expect_ready "restart"

step "rollback-compat: OK (N-1 $(git rev-parse --short "$prev_sha") runs on N's schema; no step on rollback)"
