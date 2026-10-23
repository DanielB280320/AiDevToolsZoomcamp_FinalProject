#!/usr/bin/env bash
# Run the automated tests for the Claude Code hooks in .claude/hooks/
# (the QA/PM scope guard, ADR 0008). Needs only python3 >= 3.9 and git.
#
#   scripts/test-hooks.sh            # all hook tests
#   scripts/test-hooks.sh -v         # verbose (extra args go to unittest)
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONDONTWRITEBYTECODE=1
exec python3 -m unittest discover -s "$root/.claude/hooks/tests" -t "$root/.claude/hooks/tests" -p 'test_*.py' "$@"
