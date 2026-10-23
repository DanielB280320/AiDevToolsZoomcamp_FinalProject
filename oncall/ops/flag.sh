#!/usr/bin/env bash
# Change one allow-listed feature flag on the running stack (spec §15.2, on-call tool).
#
#   oncall/ops/flag.sh <key> <value>
#   oncall/ops/flag.sh progression_engine v1           # S2 mitigation
#   oncall/ops/flag.sh fault_injection_latency_ms 0    # S3 mitigation
#
# Runs the backend's flag CLI (`python -m app.cli.flags set`) inside the backend container, so
# it uses the container's own DATABASE_URL: no secrets in arguments or in this script. The CLI
# is the single source of the allow-list (app/config.py FEATURE_FLAGS): an unknown key or an
# invalid value exits non-zero with a message and changes nothing. Running backends see the
# change within FLAG_CACHE_TTL_SECONDS (5 s), without a restart.
#
# The change is recorded with updated_by = $FLAG_ACTOR (default oncall-agent) and logged as one
# JSON line in the backend container's log stream (the CLI writes it to /proc/1/fd/1).
#
# Environment:
#   COMPOSE      compose command, default "docker compose" (e.g. with -f overrides on EC2)
#   FLAG_ACTOR   actor label recorded with the change, default oncall-agent
#
# Exit status: 0 changed (or already set), 2 invalid arguments, other non-zero on failure.
set -euo pipefail

usage() {
  echo "usage: $(basename "$0") <key> <value>" >&2
  echo "  allowed keys and values: see app/config.py FEATURE_FLAGS or" >&2
  echo "  'docker compose exec -T backend python -m app.cli.flags --help'" >&2
}

if [ "$#" -ne 2 ]; then
  usage
  exit 2
fi

key=$1
value=$2
actor=${FLAG_ACTOR:-oncall-agent}

# Cheap shape check before reaching the container; the CLI does the real validation.
if [[ ! $key =~ ^[a-z][a-z0-9_]{0,63}$ ]] || [[ ! $value =~ ^[A-Za-z0-9_-]{1,64}$ ]]; then
  echo "error: invalid key or value format; nothing changed" >&2
  usage
  exit 2
fi

cd "$(dirname "$0")/../.."
# shellcheck disable=SC2086  # COMPOSE may hold several words, e.g. "docker compose -f a -f b"
exec ${COMPOSE:-docker compose} exec -T backend \
  python -m app.cli.flags set "$key" "$value" --actor "$actor" --log-stream /proc/1/fd/1
