#!/usr/bin/env bash
# Roll the production host back to its PREVIOUS_TAG (spec §15.2, S1 mitigation; issue #113).
#
#   oncall/ops/rollback.sh
#
# Thin wrapper: runs the one rollback implementation, deploy/rollback.sh (installed on the host as
# /opt/fitwise/bin/rollback.sh), locally on the host. No SSM, no AWS credential, no arguments (the
# target is always PREVIOUS_TAG; rolling back to an arbitrary SHA is not on the on-call allow-list).
# Migrations are skipped and nothing is down-migrated (D50). Uses `sudo -n` when not root.
#
# Exit status is passed through unchanged: 0 rolled back and healthy | 1 failed | 3 nothing to roll
# back to (PREVIOUS_TAG empty or equal to the current tag; nothing changed) | 4 refused, the target is
# the release that was already rolled back from | 2 usage error (wrapper only). 3 and 4 mean: escalate.
# Test hook: FITWISE_BIN_DIR (default /opt/fitwise/bin).
set -euo pipefail

if [ "$#" -ne 0 ]; then
  echo "usage: $(basename "$0")   (no arguments: rolls back to PREVIOUS_TAG)" >&2
  exit 2
fi
script="${FITWISE_BIN_DIR:-/opt/fitwise/bin}/rollback.sh"
if [ "$(id -u)" -eq 0 ]; then
  exec "$script"
fi
exec sudo -n "$script"
