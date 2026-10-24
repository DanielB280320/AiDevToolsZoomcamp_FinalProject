"""QA boundary tests for the F11 progression engine (#31)."""

from __future__ import annotations

import pytest

from app.engines.constants import KG_PER_LB
from app.engines.progression import LoggedSet, ProgressionInput, suggest


def _sets(reps: list[int], w: float | None = 100.0) -> list[LoggedSet]:
    return [LoggedSet(reps=r, weight_kg=w) for r in reps]


def _lin(reps: list[int], **kw: object) -> ProgressionInput:
    base: dict[str, object] = {
        "exercise_type": "strength",
        "rule": "linear",
        "equipment": "barbell",
        "sets_planned": 3,
        "target_weight_kg": 100.0,
        "target_reps": 5,
        "increment_kg": 2.5,
        "deload_enabled": True,
    }
    base.update(kw)
    return ProgressionInput(logged_sets=_sets(reps), **base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("prior", "action", "after"),
    [(0, "hold", 1), (1, "hold", 2), (2, "deload", 0), (3, "deload", 0)],
)
def test_deload_boundary_is_third_failure(prior: int, action: str, after: int) -> None:
    s = suggest(_lin([4, 4, 4], consecutive_failures=prior))
    assert (s.action, s.consecutive_failures) == (action, after)


def test_deload_after_success_resets() -> None:
    s = suggest(_lin([5, 5, 5], consecutive_failures=2))
    assert (s.action, s.consecutive_failures) == ("increase_weight", 0)


def test_deload_on_double_progression() -> None:
    inp = ProgressionInput(
        exercise_type="strength",
        rule="double",
        equipment="machine",
        sets_planned=3,
        logged_sets=_sets([6, 6, 6], 50.0),
        target_weight_kg=50.0,
        reps_min=8,
        reps_max=12,
        increment_kg=2.5,
        deload_enabled=True,
        consecutive_failures=2,
    )
    s = suggest(inp)
    assert (s.action, s.weight_kg) == ("deload", 45.0)


def test_bodyweight_never_deloads() -> None:
    inp = ProgressionInput(
        exercise_type="bodyweight",
        rule="double",
        equipment="bodyweight",
        sets_planned=3,
        logged_sets=_sets([2, 2, 2], None),
        reps_min=6,
        reps_max=15,
        deload_enabled=True,
        consecutive_failures=5,
    )
    s = suggest(inp)
    assert s.action == "increase_reps" and s.weight_kg is None


def test_imperial_barbell_grid_is_min_plus_5lb_multiples() -> None:
    step = 5 * KG_PER_LB
    s = suggest(_lin([5, 5, 5], imperial=True, increment_kg=step))
    assert s.action == "increase_weight"
    k = (s.weight_kg - 20.0) / step  # type: ignore[operator]
    assert abs(k - round(k)) < 1e-9
    assert "lb" in s.reason and "kg" not in s.reason


def test_imperial_calibration_floor_is_45lb() -> None:
    s = suggest(
        ProgressionInput(
            exercise_type="strength",
            rule="linear",
            equipment="barbell",
            sets_planned=3,
            logged_sets=_sets([5, 5, 5], 10.0),
            target_reps=5,
            is_first_session=True,
            imperial=True,
        )
    )
    assert s.weight_kg == 20.0
    assert "45 lb" in s.reason


def test_increment_smaller_than_plate_step_holds_and_says_so() -> None:
    s = suggest(_lin([5, 5, 5], increment_kg=1.0))
    assert s.action == "hold" and s.weight_kg == 100.0
    assert "plate step" in s.reason


def test_uncompleted_sets_do_not_count() -> None:
    logged = [LoggedSet(5, 100.0), LoggedSet(5, 100.0), LoggedSet(5, 100.0, completed=False)]
    s = suggest(
        ProgressionInput(
            exercise_type="strength",
            rule="linear",
            equipment="barbell",
            sets_planned=3,
            logged_sets=logged,
            target_weight_kg=100.0,
            target_reps=5,
            increment_kg=2.5,
        )
    )
    assert s.action == "hold" and s.consecutive_failures == 1


def test_all_sets_uncompleted_is_skipped() -> None:
    s = suggest(
        ProgressionInput(
            exercise_type="strength",
            rule="linear",
            equipment="barbell",
            sets_planned=3,
            logged_sets=[LoggedSet(5, 100.0, completed=False)],
            target_weight_kg=100.0,
            target_reps=5,
            consecutive_failures=2,
        )
    )
    assert s.action == "none" and s.consecutive_failures == 2


def test_manual_wins_even_on_first_session() -> None:
    s = suggest(_lin([5, 5, 5], rule="manual", is_first_session=True))
    assert s.action == "none"


def test_cardio_machine_equipment_rounds_to_minute() -> None:
    inp = ProgressionInput(
        exercise_type="timed",
        rule="double",
        equipment="cardio_machine",
        sets_planned=1,
        logged_sets=[LoggedSet(seconds=1500)],
        target_seconds=1500,
    )
    assert suggest(inp).seconds == 1680  # 1650 -> nearest minute (half up)


def test_timed_exact_boundary_target_met() -> None:
    inp = ProgressionInput(
        exercise_type="timed",
        rule="double",
        equipment="none",
        sets_planned=2,
        logged_sets=[LoggedSet(seconds=30), LoggedSet(seconds=29)],
        target_seconds=30,
    )
    assert suggest(inp).action == "hold"


def test_bodyweight_add_weight_starts_from_zero_plus_increment() -> None:
    inp = ProgressionInput(
        exercise_type="bodyweight",
        rule="double",
        equipment="bodyweight",
        sets_planned=2,
        logged_sets=_sets([15, 15], None),
        reps_min=6,
        reps_max=15,
        increment_kg=2.5,
        allows_added_weight=True,
    )
    s = suggest(inp)
    assert s.weight_kg == 2.5 and "+2.5 kg" in s.reason


def test_property_strategy_is_not_vacuous() -> None:
    """The F11.2 strategy must actually reach increase and deload branches."""
    from collections import Counter

    from hypothesis import given, settings

    from tests.unit.test_progression_engine import inputs

    seen: Counter[str] = Counter()

    @settings(max_examples=500, database=None, deadline=None)
    @given(inputs())
    def run(inp: ProgressionInput) -> None:
        seen[suggest(inp).action] += 1

    run()
    assert seen["increase_weight"] >= 5
    assert seen["deload"] >= 5


def test_property_strategy_share_of_weight_increases() -> None:
    """Round 2: successes must be common (>= 10 % reach increase_weight)."""
    from collections import Counter

    from hypothesis import given, settings

    from tests.unit.test_progression_engine import inputs

    seen: Counter[str] = Counter()

    @settings(max_examples=1000, database=None, deadline=None)
    @given(inputs())
    def run(inp: ProgressionInput) -> None:
        seen[suggest(inp).action] += 1

    run()
    assert seen["increase_weight"] / sum(seen.values()) >= 0.1


def test_off_grid_custom_100lb_displays_as_100lb() -> None:
    """Custom target 100 lb stored as 45.36 kg reads 100 lb (store metric, show user units)."""
    inp = _lin([5, 5, 5], imperial=True, increment_kg=5 * KG_PER_LB, target_weight_kg=45.36)
    inp = ProgressionInput(**{**inp.__dict__, "logged_sets": _sets([5, 5, 5], 45.36)})
    s = suggest(inp)
    assert s.action == "increase_weight"
    assert s.reason.startswith("All 3 sets reached 5 reps at 100 lb"), s.reason
    # the result snaps to the barbell grid (20 kg + k x 5 lb) and reads as 105 lb
    assert s.reason.endswith("→ 105 lb × 5."), s.reason
