#!/usr/bin/env bash
# Tests that lib.sh loads /etc/fitwise-deploy.env when a host script is run by hand (#120):
# `sudo /opt/fitwise/bin/obs.sh` used to fail with "GITHUB_REPOSITORY: parameter null or not set".
# No network, no docker: the scripts are run up to their first check.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$here/.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fails=0
ok() { echo "ok   $1"; }; bad() { echo "FAIL $1"; fails=$((fails+1)); }
printf 'GITHUB_REPOSITORY=o/r\nDEPLOY_ENV=prod\nIMAGE_NAMESPACE=o\n' > "$tmp/deploy.env"
run() { env -u GITHUB_REPOSITORY -u DEPLOY_ENV -u IMAGE_NAMESPACE APP_DIR="$tmp/app" LOCK_FILE="$tmp/lock" "$@"; }
probe='. "$1/deploy/lib.sh"; echo "$GITHUB_REPOSITORY|$DEPLOY_ENV|$IMAGE_NAMESPACE"'

got="$(run DEPLOY_ENV_FILE="$tmp/deploy.env" bash -c "$probe" _ "$root")"
[ "$got" = "o/r|prod|o" ] && ok "unset variables are read from the env file" || bad "load: $got"

got="$(run DEPLOY_ENV_FILE="$tmp/deploy.env" GITHUB_REPOSITORY=x/y bash -c "$probe" _ "$root")"
[ "$got" = "x/y|prod|o" ] && ok "a variable already set wins" || bad "precedence: $got"

got="$(run DEPLOY_ENV_FILE="$tmp/missing" bash -c "$probe" _ "$root")"
[ "$got" = "||" ] && ok "missing env file: nothing set, no error" || bad "missing: $got"

printf 'GITHUB_REPOSITORY=$(touch %s/pwned)\n' "$tmp" > "$tmp/evil.env"
run DEPLOY_ENV_FILE="$tmp/evil.env" bash -c "$probe" _ "$root" >/dev/null
[ ! -e "$tmp/pwned" ] && ok "env file is parsed, never executed" || bad "env file was executed"

# The three scripts, run by hand with nothing exported, get past the repository check.
sha=$(printf 'a%.0s' {1..40}); d=$(printf 'b%.0s' {1..64})
img="ghcr.io/o/x@sha256:$d"
out="$(run DEPLOY_ENV_FILE="$tmp/deploy.env" bash "$root/deploy/deploy.sh" "$sha" "$img" "$img" 2>&1)"
case "$out" in *"not set"*) bad "deploy.sh: $out";; *) ok "deploy.sh finds GITHUB_REPOSITORY";; esac
out="$(run DEPLOY_ENV_FILE="$tmp/deploy.env" bash "$root/deploy/rollback.sh" 2>&1)"
case "$out" in *"not set"*) bad "rollback.sh: $out";; *) ok "rollback.sh finds its settings";; esac
mkdir -p "$tmp/app/releases/$sha"; touch "$tmp/app/releases/$sha/release.env"
printf 'OBS_MODE=full\nGRAFANA_ADMIN_PASSWORD=x\n' > "$tmp/app/.env"
out="$(run DEPLOY_ENV_FILE="$tmp/deploy.env" PATH="$tmp/nobin:$PATH" bash "$root/deploy/obs.sh" "$sha" 2>&1)"
case "$out" in *"not set"*) bad "obs.sh: $out";; *) ok "obs.sh finds GITHUB_REPOSITORY";; esac
out="$(run DEPLOY_ENV_FILE="$tmp/missing" bash "$root/deploy/deploy.sh" "$sha" "$img" "$img" 2>&1)"
case "$out" in *"not set"*) ok "control: without the file deploy.sh still fails fast";; *) bad "control: $out";; esac

[ "$fails" = 0 ] && echo "all deploy-env tests passed" || { echo "$fails failed"; exit 1; }
