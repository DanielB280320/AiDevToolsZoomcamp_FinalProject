#!/usr/bin/env bash
# Tests oncall/ops/rollback.sh (thin wrapper) and the poller's rollback routing (#113).
#   - the wrapper passes the exit code of deploy/rollback.sh through: 0 / 1 / 3
#   - it takes no arguments (exit 2), and runs the host script, not a copy of the logic
#   - poll.sh sends a release equal to PREVIOUS_TAG to rollback.sh (no migration step), anything
#     else to deploy.sh
# No docker, no network, no root: fake scripts, fake sudo and fake curl.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; root="$here/.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fails=0
ck() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (want '$3', got '$2')"; fails=$((fails+1)); fi; }

# --- wrapper ---
mkdir -p "$tmp/host" "$tmp/bin"
printf '#!/usr/bin/env bash\necho "ran rollback.sh args=[$*]"\nexit "${FAKE_EXIT:-0}"\n' > "$tmp/host/rollback.sh"
printf '#!/usr/bin/env bash\n[ "$1" = -n ] || exit 99\nshift\nexec "$@"\n' > "$tmp/bin/sudo"
chmod +x "$tmp/host/rollback.sh" "$tmp/bin/sudo"
export PATH="$tmp/bin:$PATH" FITWISE_BIN_DIR="$tmp/host"
for code in 0 1 3; do
  out="$(FAKE_EXIT=$code "$root/oncall/ops/rollback.sh" 2>&1)"; got=$?
  ck "wrapper exit $code passed through" "$got" "$code"
done
ck "wrapper runs the host script without arguments" "$out" "ran rollback.sh args=[]"
"$root/oncall/ops/rollback.sh" abc >/dev/null 2>&1; ck "wrapper rejects arguments (exit 2)" "$?" "2"
ck "wrapper has no rollback logic of its own" "$(grep -cE 'docker|compose|alembic' "$root/oncall/ops/rollback.sh")" "0"

# the real deploy/rollback.sh with an empty PREVIOUS_TAG exits 3 and changes nothing, via the wrapper
mkdir -p "$tmp/realapp"; : > "$tmp/realapp/PREVIOUS_TAG"; printf '%s\n' "$(printf 'b%.0s' $(seq 40))" > "$tmp/realapp/CURRENT_TAG"
FITWISE_BIN_DIR="$root/deploy" APP_DIR="$tmp/realapp" LOCK_FILE="$tmp/lock" "$root/oncall/ops/rollback.sh" >/dev/null 2>&1
ck "real rollback.sh, empty PREVIOUS_TAG: exit 3 via wrapper" "$?" "3"
ck "CURRENT_TAG kept" "$(tr -d '\n' < "$tmp/realapp/CURRENT_TAG")" "$(printf 'b%.0s' $(seq 40))"

# --- poller routing ---
S=$(printf 'a%.0s' $(seq 40)); D=$(printf '1%.0s' $(seq 64))
poll_case() { # name previous-tag release-stored(0/1) want
  local name="$1" prev="$2" stored="$3" want="$4"
  local app="$tmp/app-$RANDOM"; mkdir -p "$app/releases/$S" "$tmp/pbin"
  [ "$stored" = 1 ] && : > "$app/releases/$S/release.env"
  printf '%s\n' "$prev" > "$app/PREVIOUS_TAG"; printf '%s\n' "$(printf 'b%.0s' $(seq 40))" > "$app/CURRENT_TAG"
  cp "$root/deploy/poll.sh" "$root/deploy/lib.sh" "$tmp/pbin/"
  printf '#!/usr/bin/env bash\necho "ROUTE rollback $*"\n' > "$tmp/pbin/rollback.sh"
  printf '#!/usr/bin/env bash\necho "ROUTE deploy"\n' > "$tmp/pbin/deploy.sh"
  chmod +x "$tmp/pbin/"*.sh
  local msg; msg="$(printf 'deploy prod %s\n\nsource: %s\nbackend: ghcr.io/o/fitwise-backend@sha256:%s\nfrontend: ghcr.io/o/fitwise-frontend@sha256:%s\n' "$S" "$S" "$D" "$D")"
  jq -n --arg m "$msg" --arg r "$(printf 'c%.0s' $(seq 40))" '{commit:{sha:$r,commit:{message:$m}}}' > "$tmp/body.json"
  # fake curl: write body to -o file, headers to -D file, print status
  cat > "$tmp/bin/curl" <<'CURL'
#!/usr/bin/env bash
while [ $# -gt 0 ]; do case "$1" in -o) o="$2"; shift;; -D) d="$2"; shift;; esac; shift; done
cp "$FAKE_BODY" "$o"; : > "$d"; printf 200
CURL
  chmod +x "$tmp/bin/curl"
  local out; out="$(FAKE_BODY="$tmp/body.json" APP_DIR="$app" GITHUB_REPOSITORY=o/r DEPLOY_ENV=prod IMAGE_NAMESPACE=ghcr.io/o/ "$tmp/pbin/poll.sh" 2>&1 | grep '^ROUTE' || true)"
  ck "$name" "$out" "$want"
}
poll_case "ref moved to PREVIOUS_TAG (stored) -> rollback.sh, no migration" "$S" 1 "ROUTE rollback $S"
poll_case "ref moved to another release -> normal deploy"                   "$(printf 'd%.0s' $(seq 40))" 1 "ROUTE deploy"
poll_case "PREVIOUS_TAG empty -> normal deploy"                             "" 1 "ROUTE deploy"
poll_case "PREVIOUS_TAG but not stored on host -> normal deploy"            "$S" 0 "ROUTE deploy"
[ "$fails" = 0 ] && echo "all on-call rollback tests passed" || { echo "$fails failed"; exit 1; }
