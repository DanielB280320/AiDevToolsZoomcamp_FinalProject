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
rec() { # sha digestchar [run-id] -> commit JSON element
  local extra=""; [ -z "${3:-}" ] || extra="$(printf 'run: %s\n' "$3")"
  jq -n --arg m "$(printf 'deploy prod %s\n\nsource: %s\nbackend: ghcr.io/owner/fitwise-backend@sha256:%s\nfrontend: ghcr.io/owner/fitwise-frontend@sha256:%s\n%s' "$1" "$1" "$(d "$2")" "$(d "$2")" "$extra")" '{commit:{message:$m}}'
}
readme='{"commit":{"message":"Initial release records"}}'
cat > "$tmp/bin/gh" <<'FAKE'
#!/usr/bin/env bash
case "$*" in
  *"commits?sha=deploy/prod"*) [ -f "$FAKE_HISTORY" ] && cat "$FAKE_HISTORY" || exit 1 ;;
  *"actions/runs/"*) all="$*"; id="${all#*actions/runs/}"; id="${id%% *}"
     # FAKE_RUNS/<id> holds "<path><TAB><conclusion><TAB><branch>"; a missing file is an API error
     [ -f "$FAKE_RUNS/$id" ] && cat "$FAKE_RUNS/$id" || exit 1 ;;
  *) echo "unexpected gh: $*" >&2; exit 1 ;;
esac
FAKE
chmod +x "$tmp/bin/gh"
mkdir -p "$tmp/runs"
export PATH="$tmp/bin:$PATH" FAKE_HISTORY="$tmp/hist.json" FAKE_RUNS="$tmp/runs"
# records without a run line (before #122) count as good only when listed here
printf '# test\n%s\n%s\n%s # inline comment\n' "$A" "$B" "$C" > "$tmp/legacy.txt"
export LEGACY_GOOD_FILE="$tmp/legacy.txt"
run_result() { printf '%s\t%s\t%s\n' "${3:-.github/workflows/promote-prod.yml}" "$2" "${4:-main}" > "$tmp/runs/$1"; }
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
# --- verified history (#122): the run that wrote each record decides ---
run_result 101 success                       # A promoted, smoke green
run_result 102 failure                       # B promoted, smoke failed (host rolled back by itself)
run_result 103 success                       # C promoted, smoke green
run "good A, FAILED B, good C -> A (not B)"      0 "$A" "$C" "$(rec "$C" 3 103)" "$(rec "$B" 2 102)" "$(rec "$A" 1 101)"
run_result 104 success .github/workflows/rollback-prod.yml
run "rollback-written record counts as good"     0 "$B" "$C" "$(rec "$C" 3 103)" "$(rec "$B" 2 104)" "$(rec "$A" 1 101)"
run "only older record failed -> refuses"        1 ""   "$C" "$(rec "$C" 3 103)" "$(rec "$B" 2 102)"
run "failed + unknown run id -> refuses"         1 ""   "$C" "$(rec "$C" 3 103)" "$(rec "$B" 2 999)" "$(rec "$A" 1 998)"
run_result 105 cancelled
run "cancelled run is not good"                  1 ""   "$C" "$(rec "$C" 3 103)" "$(rec "$B" 2 105)"
run_result 106 success .github/workflows/ci.yml
run "run of another workflow is not good"        1 ""   "$C" "$(rec "$C" 3 103)" "$(rec "$B" 2 106)"
run_result 107 success .github/workflows/promote-prod.yml feature
run "run from a non-main branch is not good"     1 ""   "$C" "$(rec "$C" 3 103)" "$(rec "$B" 2 107)"
run_result 108 in_progress
run "run not finished is not good"               1 ""   "$C" "$(rec "$C" 3 103)" "$(rec "$B" 2 108)"
run "failed head C, host serves B (verified), failed C skipped -> A" 0 "$A" "$B" "$(rec "$C" 3 102)" "$(rec "$B" 2 101)" "$(rec "$A" 1 101)"
run "failed-in-the-middle twice, good A at the bottom" 0 "$A" "$C" "$(rec "$C" 3 103)" "$(rec "$B" 2 102)" "$(rec "$B" 2 102)" "$(rec "$A" 1 101)"
printf '# only A\n%s\n' "$A" > "$tmp/legacy.txt"
run "legacy record not listed (B) is skipped -> A" 0 "$A" "$C" "$(rec "$C" 3 103)" "$(rec "$B" 2)" "$(rec "$A" 1)"
printf '# empty\n' > "$tmp/legacy.txt"
run "legacy record, empty list -> refuses"       1 ""   "$C" "$(rec "$C" 3 103)" "$(rec "$B" 2)"
rm -f "$tmp/legacy.txt"
run "legacy list missing -> refuses"             1 ""   "$C" "$(rec "$C" 3 103)" "$(rec "$B" 2)"
printf '%s\n' "$A" "$B" "$C" > "$tmp/legacy.txt"
out="$(printf '[%s]' "$(rec "$C" 3 103),$(rec "$B" 2 102),$(rec "$A" 1 101)" > "$FAKE_HISTORY"; SERVED="$C" "$here/rollback-plan.sh" 2>&1)"
case "$out" in *"skipped (not verified good on prod): ${B:0:12}"*) echo "ok   plan names the skipped release" ;; *) echo "FAIL skipped release not named"; echo "$out"; fails=$((fails+1)) ;; esac
# the committed legacy list excludes the release that failed on prod on 2026-10-25
if ! grep -q 5005280817ced5daeb2eb13ccb663254dc9b9267 "$here/../deploy/legacy-good-releases.txt" 2>/dev/null || \
   [ -z "$(sed 's/#.*//' "$here/../deploy/legacy-good-releases.txt" | grep 5005280817ced5daeb2eb13ccb663254dc9b9267)" ]; then echo "ok   committed legacy list excludes the failed 5005280"; else echo "FAIL legacy list lists 5005280"; fails=$((fails+1)); fi

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
