import datetime as dt

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engines.body_tracking import check_recalculation, seven_day_average

D = dt.date(2026, 10, 22)


def days_ago(n: int) -> dt.date:
    return D - dt.timedelta(days=n)


@pytest.mark.parametrize(
    ("entries", "average", "count"),
    [
        ([], None, 0),
        ([(0, 80.0)], 80.0, 1),
        ([(0, 80.0), (3, 81.0), (6, 82.0)], 81.0, 3),  # 3 of 7 days present
        ([(0, 80.0), (6, 82.0), (7, 100.0)], 81.0, 2),  # day 7 is outside the window
        ([(1, 70.0), (2, 71.0)], 70.5, 2),
        ([(-1, 90.0), (0, 80.0)], 80.0, 1),  # a later day is outside the window
        ([(i, 80.0 + i) for i in range(7)], 83.0, 7),
    ],
)
def test_seven_day_average_table(entries, average, count):
    result = seven_day_average([(days_ago(n), kg) for n, kg in entries], D)
    assert result.average_kg == average
    assert result.count == count
    assert result.window_start == days_ago(6)
    assert result.explanation


@pytest.mark.parametrize(
    ("used", "new", "needed", "change"),
    [
        (80.0, 81.6, True, 2.0),  # exactly 2 %
        (80.0, 78.4, True, -2.0),
        (80.0, 81.52, False, 1.9),  # 1.9 %
        (80.0, 78.48, False, -1.9),
        (100.0, 102.0, True, 2.0),
        (100.0, 101.9, False, 1.9),
        (72.5, 72.5, False, 0.0),
        (60.0, 70.0, True, 16.67),
    ],
)
def test_recalculation_table(used, new, needed, change):
    result = check_recalculation(used, new)
    assert result.needed is needed
    assert result.change_pct == pytest.approx(change, abs=0.005)
    assert result.reason


@pytest.mark.parametrize(("used", "new"), [(0, 80.0), (80.0, 0), (-1, 80.0)])
def test_recalculation_rejects_non_positive(used, new):
    with pytest.raises(ValueError):
        check_recalculation(used, new)


weights = st.floats(min_value=35, max_value=300, allow_nan=False).map(lambda w: round(w, 2))
offsets = st.integers(min_value=-30, max_value=30)


@given(st.lists(st.tuples(offsets, weights), max_size=20))
def test_average_properties(entries):
    result = seven_day_average([(days_ago(n), kg) for n, kg in entries], D)
    in_window = {n: kg for n, kg in entries if 0 <= n <= 6}
    assert result.count == len(in_window)
    if in_window:
        assert result.average_kg is not None
        assert min(in_window.values()) - 1e-9 <= result.average_kg <= max(in_window.values()) + 1e-9
    else:
        assert result.average_kg is None


@given(weights, weights)
def test_recalculation_properties(used, new):
    result = check_recalculation(used, new)
    assert (
        result.needed == (abs(new - used) * 100 >= 2 * used - 1e-9)
        or abs(abs(new - used) * 100 - 2 * used) < 1e-6
    )
    if new == used:
        assert not result.needed
    # symmetric in direction: scaling the new weight up or down by the same amount of kg
    mirrored = check_recalculation(used, 2 * used - new) if 2 * used - new > 0 else None
    if mirrored is not None and abs(abs(new - used) * 100 - 2 * used) > 1e-6:
        assert mirrored.needed == result.needed
