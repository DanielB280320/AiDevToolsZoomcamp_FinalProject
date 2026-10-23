#!/usr/bin/env python3
"""FitWise scope-guard entry shim (ADR 0008).

A PreToolUse hook. The fast path reads the event, and for any agent other
than ``qa``/``pm`` returns immediately (allow) using only ``json``/``sys`` —
it never imports the full checker. Only ``qa``/``pm`` sessions load
``_guard_impl`` (compiled once to a cached ``.pyc``), which keeps the
per-call cost of every other session close to a bare interpreter start.

Unreadable input exits 2 (block). See _guard_impl.py for the checker and
docs/adr/0008-enforce-agent-write-scopes-with-a-hook.md for the design.
"""

from __future__ import annotations

import json
import sys

RESTRICTED = ("qa", "pm")


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError) as exc:
        print(f"FitWise scope guard: unreadable hook input ({exc}); blocking.", file=sys.stderr)
        return 2
    if not isinstance(event, dict):
        print("FitWise scope guard: unreadable hook input (not a JSON object); blocking.", file=sys.stderr)
        return 2
    agent = str(event.get("agent_type") or "").strip().lower()
    if agent not in RESTRICTED:
        return 0  # not a restricted agent: allow without loading the checker

    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from _guard_impl import decide, emit

    reason = decide(event)
    if reason:
        emit(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
