#!/usr/bin/env bash
# Turn the S1 demo fault ON in the working tree (issue #20; spec §15.3, D91). Used on the drill branch only.
#   scripts/demo-s1-enable.sh
# Flips backend/app/demo_faults.py S1_FINISH_RAISES to True and makes the guard test
# (test_shipped_build_has_no_demo_fault) expect it, so CI is green for the drill PR. The fix is
# `git revert` of that PR. Refuses to run twice. Never run it on main.
set -euo pipefail
cd "$(dirname "$0")/.."
fault=backend/app/demo_faults.py
guard=backend/tests/unit/test_demo_faults.py
grep -q '^S1_FINISH_RAISES: bool = False$' "$fault" || { echo "demo fault is not in the shipped (off) state" >&2; exit 1; }
grep -q 'assert demo_faults.S1_FINISH_RAISES is False' "$guard" || { echo "guard test not found" >&2; exit 1; }
sed -i 's/^S1_FINISH_RAISES: bool = False$/S1_FINISH_RAISES: bool = True  # DEMO S1 drill build (#20)/' "$fault"
sed -i 's/assert demo_faults.S1_FINISH_RAISES is False/assert demo_faults.S1_FINISH_RAISES is True  # DEMO S1 drill build (#20)/' "$guard"
git diff --stat -- "$fault" "$guard"
