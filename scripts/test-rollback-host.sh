#!/usr/bin/env bash
# Tests deploy/rollback.sh state handling (#122, D66): PREVIOUS_TAG after a rollback, ROLLED_BACK_FROM,
# and the refusals of a no-argument rollback. No docker, no network: fake docker and curl, temp APP_DIR.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; root="$here/.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
printf '#!/usr/bin/env bash\nexit 0\n' > "$tmp/bin/docker"
cat > "$tmp/bin/curl" <<'CURL'
#!/usr/bin/env bash
case "$*" in *"-o /dev/null"*) exit 0 ;; esac
printf '{"version":"%s"}' "$(cat "$APP_DIR/CURRENT_TAG_WANTED")"
CURL
chmod +x "$tmp/bin/"*
export PATH="$tmp/bin:$PATH" LOCK_FILE="$tmp/lock" HEALTH_TIMEOUT_SECONDS=2 DEPLOY_ENV_FILE=/nonexistent
h() { printf "$1%.0s" $(seq 40); }
A=$(h a); B=$(h b); C=$(h c)
fails=0
ck() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (want '$3', got '$2')"; fails=$((fails+1)); fi; }
# setup <current> <previous> <rolled-back-from or ""> : fresh host with releases A B C stored
setup() {
  export APP_DIR="$tmp/app-$RANDOM$RANDOM"; mkdir -p "$APP_DIR/releases"
  for r in "$A" "$B" "$C"; do mkdir -p "$APP_DIR/releases/$r"; : > "$APP_DIR/releases/$r/release.env"; done
  printf '%s\n' "$1" > "$APP_DIR/CURRENT_TAG"; printf '%s\n' "$2" > "$APP_DIR/PREVIOUS_TAG"
  [ -z "$3" ] || printf '%s\n' "$3" > "$APP_DIR/ROLLED_BACK_FROM"
}
rb() { # args...: runs rollback.sh; the fake curl reports the target as served
  local want="${1:-$(tr -d '[:space:]' < "$APP_DIR/PREVIOUS_TAG")}"; printf '%s' "$want" > "$APP_DIR/CURRENT_TAG_WANTED"
  "$root/deploy/rollback.sh" "$@" >"$tmp/out" 2>&1; echo $?
}
rd() { if [ -f "$APP_DIR/$1" ]; then tr -d '[:space:]' < "$APP_DIR/$1"; fi; }

# 1. A -> B promoted (previous A), B bad: no-arg rollback goes to A; PREVIOUS_TAG stays A, so it equals CURRENT_TAG
setup "$B" "$A" ""
ck "no-arg rollback B -> A: exit 0" "$(rb)" 0
ck "  CURRENT_TAG = A" "$(rd CURRENT_TAG)" "$A"
ck "  PREVIOUS_TAG unchanged (= A)" "$(rd PREVIOUS_TAG)" "$A"
ck "  ROLLED_BACK_FROM = B" "$(rd ROLLED_BACK_FROM)" "$B"
# 2. a second no-arg rollback has nowhere to go
ck "second no-arg rollback: exit 3 (PREVIOUS == CURRENT)" "$(rb)" 3
ck "  nothing changed (CURRENT A)" "$(rd CURRENT_TAG)" "$A"
ck "  ROLLED_BACK_FROM still B" "$(rd ROLLED_BACK_FROM)" "$B"
grep -q 'escalate' "$tmp/out" && echo "ok   refusal says to escalate" || { echo "FAIL refusal message"; fails=$((fails+1)); }
# 3. PREVIOUS_TAG names the release rolled back from (e.g. state left by an older version): refused with 4, not executed
setup "$A" "$B" "$B"
ck "target == ROLLED_BACK_FROM: exit 4" "$(rb)" 4
ck "  CURRENT_TAG kept" "$(rd CURRENT_TAG)" "$A"
# 4. an explicit target (owner / 'Rollback production' via poll.sh) is never refused by the note
setup "$A" "$B" "$B"
ck "explicit target == ROLLED_BACK_FROM: exit 0 (owner decides)" "$(rb "$B")" 0
ck "  CURRENT_TAG = B" "$(rd CURRENT_TAG)" "$B"
ck "  ROLLED_BACK_FROM = A" "$(rd ROLLED_BACK_FROM)" "$A"
# 5. automatic rollback after a failed deploy: deploy.sh passes the failed release
setup "$A" "$C" ""
export ROLLBACK_FROM="$B"; ck "auto rollback to A, failed B: exit 0" "$(rb "$A")" 0; unset ROLLBACK_FROM
ck "  PREVIOUS_TAG unchanged (C)" "$(rd PREVIOUS_TAG)" "$C"
ck "  ROLLED_BACK_FROM = failed B" "$(rd ROLLED_BACK_FROM)" "$B"
# 6. empty PREVIOUS_TAG
setup "$A" "" ""; : > "$APP_DIR/PREVIOUS_TAG"
ck "empty PREVIOUS_TAG: exit 3" "$(rb)" 3
# 7. unhealthy target: failure, state untouched
setup "$B" "$A" ""
printf '%s' "$C" > "$APP_DIR/CURRENT_TAG_WANTED"; "$root/deploy/rollback.sh" >/dev/null 2>&1; got=$?
ck "target not healthy: exit 1" "$got" 1
ck "  CURRENT_TAG kept, no ROLLED_BACK_FROM" "$(rd CURRENT_TAG)|$(rd ROLLED_BACK_FROM)" "$B|"
# 8. deploy.sh clears the note after a successful deploy and tells rollback.sh what it rolled back from
grep -q 'rm -f "\$ROLLED_BACK_FROM_FILE"' "$root/deploy/deploy.sh" && echo "ok   deploy.sh clears ROLLED_BACK_FROM on success" || { echo "FAIL deploy.sh does not clear the note"; fails=$((fails+1)); }
grep -q 'ROLLBACK_FROM="\$sha" "\$here/rollback.sh"' "$root/deploy/deploy.sh" && echo "ok   deploy.sh passes the failed release" || { echo "FAIL deploy.sh rollback call"; fails=$((fails+1)); }
[ "$fails" = 0 ] && echo "all rollback-host tests passed" || { echo "$fails failed"; exit 1; }
