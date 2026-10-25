#!/usr/bin/env bash
# Tests scripts/rollback-plan.sh against a fake `gh` serving a canned deploy/prod history (#113).
# No network, no docker.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
export GITHUB_REPOSITORY=Owner/repo
h() { printf "$1%.0s" $(seq 40); }          # 40 hex chars
A=$(h a); B=$(h b); C=$(h c)
d() { printf "$1%.0s" $(seq 64); }
rec() { # sha digestchar -> commit JSON element
  jq -n --arg m "$(printf 'deploy prod %s\n\nsource: %s\nbackend: ghcr.io/owner/fitwise-backend@sha256:%s\nfrontend: ghcr.io/owner/fitwise-frontend@sha256:%s\n' "$1" "$1" "$(d "$2")" "$(d "$2")")" '{commit:{message:$m}}'
}
readme='{"commit":{"message":"Initial release records"}}'
cat > "$tmp/bin/gh" <<'FAKE'
#!/usr/bin/env bash
case "$*" in *"commits?sha=deploy/prod"*) [ -f "$FAKE_HISTORY" ] && cat "$FAKE_HISTORY" || exit 1 ;; *) echo "unexpected gh: $*" >&2; exit 1 ;; esac
FAKE
chmod +x "$tmp/bin/gh"
export PATH="$tmp/bin:$PATH" FAKE_HISTORY="$tmp/hist.json"
fails=0
run() { # name want-exit want-target(or "") served history-json...
  local name="$1" want="$2" tgt="$3" served="$4"; shift 4
  printf '[%s]' "$(IFS=,; echo "$*")" > "$FAKE_HISTORY"
  : > "$tmp/out"; out="$(SERVED="$served" GITHUB_OUTPUT="$tmp/out" "$here/rollback-plan.sh" 2>&1)"; got=$?
  gt="$(sed -n 's/^target_sha=//p' "$tmp/out")"
  if [ "$got" = "$want" ] && [ "$gt" = "$tgt" ]; then echo "ok   $name"; else echo "FAIL $name (exit $got, target '$gt')"; echo "$out" | sed 's/^/     /'; fails=$((fails+1)); fi
}
# newest first
run "normal: head C, served C -> B"                0 "$B" "$C" "$(rec "$C" 3)" "$(rec "$B" 2)" "$(rec "$A" 1)" "$readme"
run "no SERVED: head is current -> B"              0 "$B" ""   "$(rec "$C" 3)" "$(rec "$B" 2)" "$(rec "$A" 1)"
run "failed head C, host serves B -> A"            0 "$A" "$B" "$(rec "$C" 3)" "$(rec "$B" 2)" "$(rec "$A" 1)"
run "re-promotion of same sha is skipped"          0 "$A" "$B" "$(rec "$B" 2)" "$(rec "$B" 2)" "$(rec "$A" 1)"
run "first deploy: no previous -> fails"           1 ""   "$A" "$(rec "$A" 1)" "$readme"
run "only README commit -> fails"                  1 ""   ""   "$readme"
run "served sha not in history -> refuses"         1 ""   "$C" "$(rec "$B" 2)" "$(rec "$A" 1)"
run "served not a sha -> refuses"                  1 ""   "zzz" "$(rec "$B" 2)" "$(rec "$A" 1)"
# a record without valid digest references is refused
bad="$(jq -n --arg m "deploy prod $A

source: $A
backend: docker.io/evil/backend@sha256:$(d 1)
frontend: ghcr.io/owner/fitwise-frontend@sha256:$(d 1)" '{commit:{message:$m}}')"
run "foreign image reference in target -> fails"   1 ""   "$B" "$(rec "$B" 2)" "$bad"
rm -f "$FAKE_HISTORY"
: > "$tmp/out"; SERVED="" "$here/rollback-plan.sh" >/dev/null 2>&1; got=$?
if [ "$got" = 1 ]; then echo "ok   unreadable history -> fails"; else echo "FAIL unreadable history (exit $got)"; fails=$((fails+1)); fi
[ "$fails" = 0 ] && echo "all rollback-plan tests passed" || { echo "$fails failed"; exit 1; }
