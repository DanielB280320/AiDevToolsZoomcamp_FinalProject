"""Progression engine v2: a DEMO-ONLY faulty version (spec §15.3, scenario S2).

v2 behaves exactly like v1 except that it raises `BodyweightNotSupported` for bodyweight
exercises, so finishing a session that contains one returns a 5xx and trips KeyJourneyErrors.
It exists only so the on-call agent has a real fault to mitigate (`flag.sh progression_engine v1`).

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
    if p.exercise_type == "bodyweight":
        raise BodyweightNotSupported
    return progression.suggest(p)
