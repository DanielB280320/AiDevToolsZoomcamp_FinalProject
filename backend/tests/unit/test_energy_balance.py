import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engines.energy_balance import EnergyInputs, day_balance


@pytest.mark.parametrize(
    ("eaten", "base", "train", "act", "burned", "balance"),
    [
        (0, 2000, 0, 0, 2000, -2000),
        (2500, 2000, 300, 100, 2400, 100),
        (1800, 2200, 0, 250, 2450, -650),
        (3000, 0, 0, 0, 0, 3000),
    ],
)
def test_table(eaten, base, train, act, burned, balance):
    r = day_balance(EnergyInputs(eaten, base, train, act))
    assert (r.burned_kcal, r.balance_kcal) == (burned, balance)
    assert "estimated" in r.explanation


kcal = st.integers(min_value=0, max_value=20000)


@given(kcal, kcal, kcal, kcal)
def test_properties(eaten, base, train, act):
    r = day_balance(EnergyInputs(eaten, base, train, act))
    assert r.burned_kcal == base + train + act
    assert r.balance_kcal == eaten - r.burned_kcal
    assert r.burned_kcal >= base
    # more exercise never raises the balance
    more = day_balance(EnergyInputs(eaten, base, train + 1, act))
    assert more.balance_kcal == r.balance_kcal - 1
