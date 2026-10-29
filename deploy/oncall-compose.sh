#!/usr/bin/env bash
# Root-side helper for the on-call agent's compose access (issue #69; spec §15.2, ADR 0007).
#
#   sudo -n /opt/fitwise/bin/oncall-compose.sh <ps|logs|restart|exec> ...
#
# `docker compose` on the host needs the root-only /opt/fitwise/.env, so the unprivileged
# `fitwise-oncall` user (not in the docker group) reaches it only through this script, via sudo
# (sudoers: this file and rollback.sh, nothing else). It runs `docker compose` for the CURRENT_TAG
# release (compose_release in lib.sh) and accepts exactly these shapes; anything else exits 2:
#
#   ps    [-a|--all] [-q|--quiet] [--services] [--format V] [--status V]
#   logs  [--no-color] [-t|--timestamps] [--no-log-prefix] [--since V] [--until V] [--tail N] [service...]
#         (never -f/--follow: a follow would hang until the agent's timeout)
#   restart backend|frontend
#   exec -T backend python -m app.cli.flags set <key> <value> --actor oncall-agent --log-stream /proc/1/fd/1
#         (the flag CLI of oncall/ops/flag.sh; the CLI validates key and value against FEATURE_FLAGS)
#
# Tests: scripts/test-oncall-compose.sh.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
. "$here/lib.sh"

usage() { echo "usage: $(basename "$0") ps|logs|restart|exec ... (see the header)" >&2; exit 2; }
bad() { echo "error: $*" >&2; exit 2; }
word='^[A-Za-z0-9_.:-]{1,64}$'
service='^[a-z][a-z0-9_-]{0,40}$'

[ "$#" -ge 1 ] || usage
sub="$1"; shift
args=()
case "$sub" in
  ps)
    while [ "$#" -gt 0 ]; do
      case "$1" in
        -a|--all|-q|--quiet|--services) args+=("$1"); shift ;;
        --format|--status) [ "$#" -ge 2 ] && [[ "$2" =~ $word ]] || bad "bad value for $1"; args+=("$1" "$2"); shift 2 ;;
        *) bad "ps option not allowed: $1" ;;
      esac
    done ;;
  logs)
    while [ "$#" -gt 0 ]; do
      case "$1" in
        --no-color|-t|--timestamps|--no-log-prefix) args+=("$1"); shift ;;
        --since|--until|--tail) [ "$#" -ge 2 ] && [[ "$2" =~ $word ]] || bad "bad value for $1"; args+=("$1" "$2"); shift 2 ;;
        *) [[ "$1" =~ $service ]] || bad "logs argument not allowed: $1"; args+=("$1"); shift ;;
      esac
    done ;;
  restart)
    [ "$#" -eq 1 ] && { [ "$1" = backend ] || [ "$1" = frontend ]; } || bad "restart takes backend or frontend"
    args=("$1") ;;
  exec)
    [ "$#" -eq 12 ] || bad "exec is only for the feature-flag CLI"
    [ "$1 $2 $3 $4 $5 $6" = "-T backend python -m app.cli.flags set" ] || bad "exec is only for the feature-flag CLI"
    [[ "$7" =~ ^[a-z][a-z0-9_]{0,63}$ ]] && [[ "$8" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || bad "bad flag key or value"
    [ "$9 ${10} ${11} ${12}" = "--actor oncall-agent --log-stream /proc/1/fd/1" ] || bad "exec is only for the feature-flag CLI"
    args=("$@") ;;
  *) usage ;;
esac

sha="$(read_tag "$CURRENT_TAG_FILE")"
is_sha "$sha" || die "no release is deployed on this host"
compose_release "$sha" "$sub" "${args[@]}"
