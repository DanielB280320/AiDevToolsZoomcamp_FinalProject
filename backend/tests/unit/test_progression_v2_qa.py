"""QA property tests for the demo-only progression engine v2 (#86, spec §15.3 S2)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engines import progression, progression_v2
from app.engines.progression import LoggedSet, ProgressionInput

_sets = st.lists(
    st.builds(
        LoggedSet,
        reps=st.integers(0, 30),
        weight_kg=st.one_of(st.none(), st.floats(0, 300, allow_nan=False)),
        seconds=st.one_of(st.none(), st.integers(0, 600)),
        completed=st.booleans(),
    ),
    max_size=6,
)


def _inputs(exercise_type: str) -> st.SearchStrategy[ProgressionInput]:
    return st.builds(
        ProgressionInput,
        exercise_type=st.just(exercise_type),
        rule=st.sampled_from(["linear", "double", "manual"]),
        equipment=st.sampled_from(["barbell", "dumbbell", "machine", "bodyweight"]),
        sets_planned=st.integers(1, 6),
        logged_sets=_sets,
        target_weight_kg=st.one_of(st.none(), st.floats(0, 300, allow_nan=False)),
        target_reps=st.one_of(st.none(), st.integers(1, 30)),
        reps_min=st.one_of(st.none(), st.integers(1, 15)),
        reps_max=st.one_of(st.none(), st.integers(1, 30)),
        target_seconds=st.one_of(st.none(), st.integers(1, 600)),
        increment_kg=st.sampled_from([0.0, 1.25, 2.5]),
        deload_enabled=st.booleans(),
        consecutive_failures=st.integers(0, 4),
        is_first_session=st.booleans(),
    )


@given(_inputs("strength") | _inputs("timed"))
def test_v2_equals_v1_for_non_bodyweight(p: ProgressionInput) -> None:
    try:
        expected = progression.suggest(p)
    except Exception as exc:  # v2 must fail identically to v1
        with pytest.raises(type(exc)):
            progression_v2.suggest(p)
        return
    assert progression_v2.suggest(p) == expected


@given(_inputs("bodyweight"))
def test_v2_always_raises_for_bodyweight_with_constant_message(p: ProgressionInput) -> None:
    with pytest.raises(progression_v2.BodyweightNotSupported) as raised:
        progression_v2.suggest(p)
    assert str(raised.value) == "progression engine v2 does not support bodyweight exercises"
