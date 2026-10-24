#!/usr/bin/env bash
# Tests scripts/promote-verify.sh against a fake `gh` (no network). Issue #14.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
GOOD=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa; SMOKEFAIL=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
SKIPPED=cccccccccccccccccccccccccccccccccccccccc; UNKNOWN=dddddddddddddddddddddddddddddddddddddddd
NOREC=eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee; BADIMG=ffffffffffffffffffffffffffffffffffffffff
D=$(printf '1%.0s' $(seq 64))
cat > "$tmp/bin/gh" <<FAKE
#!/usr/bin/env bash
args="\$*"
case "\$args" in
  *"workflows/ci.yml/runs?head_sha=$GOOD"*) echo 101 ;;
  *"workflows/ci.yml/runs?head_sha=$SMOKEFAIL"*) echo 102 ;;
  *"workflows/ci.yml/runs?head_sha=$SKIPPED"*) echo 103 ;;
  *"workflows/ci.yml/runs?head_sha=$NOREC"*) echo 104 ;;
  *"workflows/ci.yml/runs?head_sha=$BADIMG"*) echo 105 ;;
  *"workflows/ci.yml/runs?head_sha="*) : ;;
  *"actions/runs/102/jobs"*"Dev serves"*) echo failure ;;
  *"actions/runs/103/jobs"*"Dev serves"*) echo skipped ;;
  *"actions/runs/"*"/jobs"*) echo success ;;
  "run download 101"*|"run download 105"*)
    out=""; while [ \$# -gt 0 ]; do [ "\$1" = "-D" ] && out="\$2"; shift; done
    if [ "$GOOD" != "" ] && [[ "\$args" == *"download 101"* ]]; then
      printf 'backend: ghcr.io/danielb280320/fitwise-backend@sha256:$D\nfrontend: ghcr.io/danielb280320/fitwise-frontend@sha256:$D\n' > "\$out/release-record.txt"
    else
      printf 'backend: docker.io/evil/backend:latest\nfrontend: ghcr.io/danielb280320/fitwise-frontend@sha256:$D\n' > "\$out/release-record.txt"
    fi ;;
  "run download"*) exit 1 ;;
  *"branches/deploy/dev"*) echo "deploy dev x" ;;
  *) echo "unexpected gh call: \$args" >&2; exit 1 ;;
esac
FAKE
chmod +x "$tmp/bin/gh"
export PATH="$tmp/bin:$PATH" GITHUB_REPOSITORY=DanielB280320/fitwise
fails=0
expect() { # name, want-exit, grep-pattern, args...
  local name="$1" want="$2" pat="$3"; shift 3
  out="$("$here/promote-verify.sh" "$@" 2>&1)"; code=$?
  if [ "$code" = "$want" ] && grep -Eq -- "$pat" <<<"$out"; then echo "ok   $name"; else echo "FAIL $name (exit $code): $out"; fails=$((fails+1)); fi
}
expect "proven SHA passes and prints digests" 0 "backend: ghcr.io/danielb280320/fitwise-backend@sha256:$D" $GOOD
expect "short SHA rejected"                   1 "40-character" abc123
expect "empty input rejected"                 1 "40-character"
expect "unknown SHA rejected"                 1 "no ci.yml run on main" $UNKNOWN
expect "smoke-dev failed rejected"            1 "smoke-dev=failure" $SMOKEFAIL
expect "smoke-dev skipped rejected"           1 "smoke-dev=skipped" $SKIPPED
expect "missing release record rejected"      1 "no release record" $NOREC
expect "non-GHCR/non-digest image rejected"   1 "backend image reference" $BADIMG
[ "$fails" = 0 ] && echo "all promote-verify tests passed" || { echo "$fails failed"; exit 1; }
