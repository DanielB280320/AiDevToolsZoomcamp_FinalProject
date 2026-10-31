#!/usr/bin/env bash
# Tests the weekly adaptive-calorie scheduler (#42) with a fake docker: no network, no root.
#   - the script runs the CLI inside the running fitwise backend container and exits 0
#   - backend container down, or the CLI failing, exits non-zero with an ERROR line
#   - the output never contains more than statuses and the CLI's count line
#   - the units are valid (systemd-analyze verify/calendar when available), the timer is
#     Persistent, runs Monday and Tuesday UTC, and bootstrap installs and enables it everywhere
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; dep="$here/../deploy"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fails=0
ck() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (want '$3', got '$2')"; fails=$((fails+1)); fi; }
mkdir -p "$tmp/bin"
cat > "$tmp/bin/docker" <<'F'
#!/usr/bin/env bash
echo "docker $*" >> "$FAKE_LOG"
case "$1" in
  ps) [ "${FAKE_NO_BACKEND:-0}" = 1 ] || echo abc123 ;;
  exec) [ "${FAKE_CLI_FAIL:-0}" = 1 ] && exit 1; echo "adaptive calorie suggestions created: 2" ;;
esac
F
chmod +x "$tmp/bin/docker"
export PATH="$tmp/bin:$PATH" FAKE_LOG="$tmp/log"
run() { : > "$FAKE_LOG"; env "$@" bash "$dep/adaptive-calories.sh" > "$tmp/out" 2>&1; echo $?; }

ck "success exits 0" "$(run X=1)" 0
ck "runs the CLI in the backend container" "$(grep -c '^docker exec abc123 python -m app.cli.adaptive_calories$' "$FAKE_LOG")" 1
ck "finds the container by compose project and service" "$(grep -c 'label=com.docker.compose.project=fitwise.*label=com.docker.compose.service=backend' "$FAKE_LOG")" 1
ck "output holds statuses and the count only" "$(grep -vc 'fitwise-adaptive-calories: \|created: 2' "$tmp/out")" 0
for f in FAKE_NO_BACKEND FAKE_CLI_FAIL; do
  got="$(run "$f=1")"; [ "$got" != 0 ] && got=nonzero
  ck "$f fails" "$got" nonzero
  ck "$f is logged as ERROR" "$(grep -c 'ERROR:' "$tmp/out")" 1
done
ck "no backend: nothing is executed" "$(run FAKE_NO_BACKEND=1 >/dev/null; grep -c '^docker exec' "$FAKE_LOG")" 0

timer="$dep/fitwise-adaptive-calories.timer"; svc="$dep/fitwise-adaptive-calories.service"
ck "timer is Persistent" "$(grep -c '^Persistent=true' "$timer")" 1
ck "timer runs Monday and Tuesday in UTC" "$(grep -c '^OnCalendar=Mon,Tue \*-\*-\* 01:00:00 UTC$' "$timer")" 1
ck "service is oneshot" "$(grep -c '^Type=oneshot' "$svc")" 1
ck "service runs the installed script" "$(grep -c '^ExecStart=/opt/fitwise/bin/adaptive-calories.sh$' "$svc")" 1
if command -v systemd-analyze >/dev/null; then
  ck "calendar expression is valid" "$(systemd-analyze calendar 'Mon,Tue *-*-* 01:00:00 UTC' >/dev/null 2>&1; echo $?)" 0
  ck "next elapse is a Monday or Tuesday" "$(systemd-analyze calendar 'Mon,Tue *-*-* 01:00:00 UTC' 2>/dev/null | grep -c 'Normalized form: Mon,Tue')" 1
  cp "$dep/adaptive-calories.sh" "$tmp/adaptive-calories.sh"; chmod +x "$tmp/adaptive-calories.sh"
  sed "s#/opt/fitwise/bin/adaptive-calories.sh#$tmp/adaptive-calories.sh#" "$svc" > "$tmp/fitwise-adaptive-calories.service"
  cp "$timer" "$tmp/"
  out="$(systemd-analyze verify "$tmp/fitwise-adaptive-calories.service" "$tmp/fitwise-adaptive-calories.timer" 2>&1)"
  # A runner without Docker installed reports docker.service as missing; that is not a unit error.
  ck "systemd-analyze verify has no unit errors" "$(printf '%s\n' "$out" | grep -v 'docker.service not found' | grep -c 'adaptive-calories')" 0
else
  echo "skip systemd-analyze checks (not installed)"
fi
b="$dep/bootstrap.sh"
for f in adaptive-calories.sh fitwise-adaptive-calories.service fitwise-adaptive-calories.timer; do
  ck "bootstrap installs $f for every env" "$(awk -v f="$f" '/^if \[ "\$ENV_NAME" = prod \]; then/{p=1} /^fi$/{p=0} !p && index($0,"install_file " f){c++} END{print c+0}' "$b")" 1
done
ck "bootstrap enables the timer for every env" "$(grep -c '^systemctl enable --now fitwise-adaptive-calories.timer' "$b")" 1
[ "$fails" = 0 ] && echo "all adaptive-calories scheduler tests passed" || { echo "$fails failure(s)"; exit 1; }
