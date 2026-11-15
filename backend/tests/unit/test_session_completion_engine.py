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
        ([R(8, 8), R(8, 4), R(8, None)], 0.5),  # (1 + 0.5 + 0) / 3; never-logged scores 0
        ([R(8, 0), R(8, 0)], 0.0),  # skipped sets are logged with no actual
        ([R(8, 12), R(8, 8)], 1.0),  # extra reps above target do not count
        ([R(8, 12), R(8, 0)], 0.5),  # ...and cannot make up for a missed set
        ([R(600, 300)], 0.5),  # timed: seconds
        ([R(8, 8), R(None, 5), R(0, 5)], 1.0),  # sets without a positive target are left out
        ([R(3, 1)], 0.3333),  # rounded to 4 decimals
        ([R(10, 10)] + [R(10, None)] * 31, 0.0313),  # 1/32 = 0.03125: a tie rounds half up
        ([R(3, 1), R(3, 2)] + [R(10, None)] * 30, 0.0313),  # 1/3 + 2/3 is exactly one set
        # D110: sets weigh the same whatever their unit; one 600 s set never outweighs the reps
        ([R(6, 6)] + [R(6, None)] * 4 + [R(10, None)] * 17 + [R(600, 600)], 0.087),  # 2 of 23
        ([R(6, 3), R(600, 600)], 0.75),  # (0.5 + 1) / 2, not 603 / 606
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


def test_nan_actual_is_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        completion([R(8, float("nan"))])
    with pytest.raises(ValueError, match="non-negative"):
        completion([R(8, 8), R(8, float("nan"))])


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


@given(_sets)
def test_ratio_is_the_share_of_sets_done_when_each_is_all_or_nothing(
    sets: list[PlannedSetResult],
) -> None:
    """D110: with every set either done as planned or not at all, completion is done ÷ planned,
    independent of the size or unit of the targets."""
    binary = [R(s.target, s.target if (s.actual or 0) % 2 else None) for s in sets]
    done = sum(1 for s in binary if s.actual is not None)
    assert completion(binary).ratio == round(done / len(binary), 4)
