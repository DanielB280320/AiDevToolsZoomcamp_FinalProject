"""F10.2 completion engine: table-driven cases and properties."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engines.session_completion import PlannedSetResult, completion

R = PlannedSetResult


@pytest.mark.parametrize(
    ("sets", "ratio"),
    [
        ([R(8, 8), R(8, 8), R(8, 8)], 1.0),
        ([R(8, 8), R(8, 4), R(8, None)], 0.5),  # 12 / 24; a never-logged set counts as 0
        ([R(8, 0), R(8, 0)], 0.0),  # skipped sets are logged with no actual
        ([R(8, 12), R(8, 8)], 1.0),  # extra reps above target do not count
        ([R(8, 12), R(8, 0)], 0.5),  # ...and cannot make up for a missed set
        ([R(600, 300)], 0.5),  # timed: seconds
        ([R(8, 8), R(None, 5), R(0, 5)], 1.0),  # sets without a positive target are left out
        ([R(3, 1)], 0.3333),  # rounded to 4 decimals
    ],
)
def test_completion_table(sets: list[PlannedSetResult], ratio: float) -> None:
    result = completion(sets)
    assert result.ratio == ratio
    assert "÷" in result.explanation


@pytest.mark.parametrize("sets", [[], [R(None, 4)], [R(0, 4)]])
def test_no_positive_target_is_undefined(sets: list[PlannedSetResult]) -> None:
    result = completion(sets)
    assert result.ratio is None
    assert result.explanation


def test_negative_actual_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        completion([R(8, -1)])


_sets = st.lists(
    st.builds(
        R,
        st.integers(min_value=1, max_value=600),
        st.one_of(st.none(), st.integers(min_value=0, max_value=2000)),
    ),
    min_size=1,
    max_size=30,
)


@given(_sets)
def test_ratio_is_between_zero_and_one(sets: list[PlannedSetResult]) -> None:
    ratio = completion(sets).ratio
    assert ratio is not None
    assert 0 <= ratio <= 1


@given(_sets)
def test_doing_every_set_as_planned_is_full_completion(sets: list[PlannedSetResult]) -> None:
    full = [R(s.target, s.target) for s in sets]
    assert completion(full).ratio == 1.0


@given(_sets)
def test_more_work_never_lowers_completion(sets: list[PlannedSetResult]) -> None:
    more = [R(s.target, (s.actual or 0) + 1) for s in sets]
    base = [R(s.target, s.actual) for s in sets]
    assert completion(more).ratio >= completion(base).ratio  # type: ignore[operator]
