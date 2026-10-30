"""F12.2 nutrition completion: table-driven and property tests."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engines.nutrition_completion import nutrition_completion


@pytest.mark.parametrize(
    ("statuses", "ratio", "eaten"),
    [
        ([], None, 0),
        ([None, None, None], 0.0, 0),
        (["eaten", None, None], 0.3333, 1),
        (["eaten", "adjusted", None], 0.6667, 2),
        (["skipped", None, "eaten"], 0.3333, 1),
        (["skipped", "skipped"], 0.0, 0),
        (["eaten", "adjusted", "eaten", "adjusted"], 1.0, 4),
        (["extra", "eaten"], 0.5, 1),  # extra is never a planned meal; defensive
    ],
)
def test_completion_table(statuses: list[str | None], ratio: float | None, eaten: int) -> None:
    result = nutrition_completion(statuses)
    assert result.ratio == ratio
    assert result.eaten == eaten
    assert result.planned == len(statuses)
    assert result.explanation


@given(st.lists(st.sampled_from([None, "eaten", "adjusted", "skipped"]), min_size=1, max_size=12))
def test_ratio_is_within_zero_and_one_and_skips_never_count(statuses: list[str | None]) -> None:
    result = nutrition_completion(statuses)
    assert result.ratio is not None and 0 <= result.ratio <= 1
    assert result.eaten == sum(s in ("eaten", "adjusted") for s in statuses)
