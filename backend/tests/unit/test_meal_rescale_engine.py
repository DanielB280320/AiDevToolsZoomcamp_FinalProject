"""#171 D74 portion rescale engine: table-driven and property tests."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engines import constants as c
from app.engines.meal_rescale import rescale_portions


@pytest.mark.parametrize(
    ("factors", "kcal", "target", "expected"),
    [
        ([1.0, 1.0], [400.0, 600.0], 1500.0, [1.5, 1.5]),
        ([1.0, 1.0], [400.0, 600.0], 500.0, [0.5, 0.5]),
        ([1.2, 0.8], [480.0, 320.0], 800.0, [1.2, 0.8]),  # already on target
    ],
)
def test_all_portions_move_together(
    factors: list[float], kcal: list[float], target: float, expected: list[float]
) -> None:
    result = rescale_portions(factors, kcal, target)
    assert list(result.factors) == pytest.approx(expected, abs=0.01)
    assert result.day_kcal == pytest.approx(target, rel=0.01)
    assert not result.clamped
    assert str(round(target)) in result.explanation


def test_a_change_beyond_the_bounds_is_clamped_not_an_error() -> None:
    up = rescale_portions([1.0, 1.0], [400.0, 400.0], 100000.0)
    assert list(up.factors) == [c.RESCALE_PORTION_MAX] * 2
    assert up.clamped and "limited" in up.explanation
    down = rescale_portions([1.0], [400.0], 1.0)
    assert list(down.factors) == [c.RESCALE_PORTION_MIN]
    assert down.clamped


def test_a_clamped_meal_lets_the_others_take_the_difference() -> None:
    result = rescale_portions([2.9, 1.0], [290.0, 400.0], 1000.0)
    assert result.factors[0] == c.RESCALE_PORTION_MAX
    assert result.day_kcal == pytest.approx(1000.0, rel=0.01)


def test_empty_day_is_unchanged() -> None:
    result = rescale_portions([], [], 2000.0)
    assert result.factors == ()


@pytest.mark.parametrize("target", [0.0, -5.0, float("nan"), float("inf")])
def test_bad_target_is_rejected(target: float) -> None:
    with pytest.raises(ValueError, match="target_kcal"):
        rescale_portions([1.0], [100.0], target)


def test_length_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="same length"):
        rescale_portions([1.0], [100.0, 200.0], 500.0)


@given(
    meals=st.lists(st.tuples(st.floats(0.25, 3.0), st.floats(50, 1500)), min_size=1, max_size=6),
    target=st.floats(300, 6000),
)
def test_factors_always_stay_within_bounds(meals: list[tuple[float, float]], target: float) -> None:
    result = rescale_portions([f for f, _ in meals], [k for _, k in meals], target)
    assert len(result.factors) == len(meals)
    assert all(0 < f <= 3 for f in result.factors)
    assert all(c.RESCALE_PORTION_MIN <= f <= c.RESCALE_PORTION_MAX for f in result.factors)
    if not result.clamped:
        assert result.day_kcal == pytest.approx(target, rel=0.02)
