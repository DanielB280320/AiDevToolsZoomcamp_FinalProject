"""Progression engine v2 (experimental, spec §15.3, scenario S2).

v2 behaves exactly like v1, including for bodyweight exercises. It used to raise
`BodyweightNotSupported` for them, which made finishing such a session return a 5xx and tripped
KeyJourneyErrors; that is fixed and the exception is no longer raised.

It is reachable only through the `progression_engine` feature flag, which defaults to `v1`; never
set it to `v2` outside the demo. The error message is a constant: no exercise, weight or rep
value (health data, §6.5) may ever be put into it.
"""

from app.engines import progression
from app.engines.progression import ProgressionInput, Suggestion


class BodyweightNotSupported(Exception):  # noqa: N818 - reads better as a domain error
    """The injected S2 fault. Constant message by design (no health data)."""

    def __init__(self) -> None:
        super().__init__("progression engine v2 does not support bodyweight exercises")


def suggest(p: ProgressionInput) -> Suggestion:
    # Bodyweight exercises are handled by v1 (incident #218): v2 no longer raises.
    return progression.suggest(p)
