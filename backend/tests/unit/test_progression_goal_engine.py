"""F11 / D107 goal-driven progression engine: table-driven rule tests and property tests."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engines.constants import (
    PROGRESSION_HOLD_GOALS,
    PROGRESSION_MAX_STEP_PCT,
    TRAINING_GOAL_BY_PROFILE_GOAL,
    TRAINING_GOAL_REP_RANGES,
    TRAINING_GOALS,
)
from app.engines.progression import LoggedSet, min_weight_kg, plate_step_kg
from app.engines.progression_goal import (
    GoalProgressionInput,
    default_training_goal,
    recommended_rep_range,
    resolve_training_goal,
    step_factors,
    suggest,
    weight_increase_kg,
)


def sets(reps: list[int], weight: float | None = 40.0) -> list[LoggedSet]:
    return [LoggedSet(reps=r, weight_kg=weight) for r in reps]


def inp(logged: list[LoggedSet], **kw: object) -> GoalProgressionInput:
    base: dict[str, object] = {
        "goal": "hypertrophy",
        "equipment": "machine",
        "sets_planned": 3,
        "target_weight_kg": 40.0,
        "reps_min": 8,
        "reps_max": 12,
    }
    base.update(kw)
    return GoalProgressionInput(logged_sets=logged, **base)  # type: ignore[arg-type]


# ───────────── goals and ranges ─────────────


def test_goal_defaults_from_the_profile_goal() -> None:
    assert default_training_goal("muscle_gain") == "hypertrophy"
    assert default_training_goal("cutting") == "cutting"
    assert default_training_goal("maintenance") == "maintenance"
    assert default_training_goal("recomposition") == "hypertrophy"
    assert default_training_goal("wellness") == "endurance"
    assert default_training_goal(None) == "hypertrophy"
    assert default_training_goal("unknown") == "hypertrophy"


def test_stored_goal_wins_over_the_default() -> None:
    assert resolve_training_goal("strength", "wellness") == "strength"
    assert resolve_training_goal(None, "wellness") == "endurance"
    assert resolve_training_goal("bogus", "cutting") == "cutting"


def test_rep_ranges_per_goal() -> None:
    assert {g: recommended_rep_range(g) for g in TRAINING_GOALS} == {
        "strength": (3, 6),
        "hypertrophy": (8, 12),
        "endurance": (13, 20),
        "maintenance": (6, 12),
        "cutting": (8, 12),
    }


def test_every_profile_goal_maps_to_a_training_goal() -> None:
    assert set(TRAINING_GOAL_BY_PROFILE_GOAL.values()) <= set(TRAINING_GOALS)
    assert set(TRAINING_GOAL_REP_RANGES) == set(TRAINING_GOALS)


# ───────────── rules ─────────────


@pytest.mark.parametrize(
    ("name", "logged", "kw", "action", "weight", "reps"),
    [
        ("all at max -> heavier, back to min", sets([12, 12, 12]), {}, "increase_weight", 42.5, 8),
        (
            "extra sets beyond the plan ignored",
            sets([12, 12, 12, 3]),
            {},
            "increase_weight",
            42.5,
            8,
        ),
        ("inside the range -> add reps", sets([10, 9, 11]), {}, "increase_reps", 40.0, 10),
        ("weakest set sets the next reps", sets([12, 12, 8]), {}, "increase_reps", 40.0, 9),
        ("reps capped at max", sets([12, 12, 11]), {}, "increase_reps", 40.0, 12),
        ("one set below min -> hold, retry", sets([10, 10, 7]), {}, "hold", 40.0, 8),
        ("missing a planned set is a failure", sets([12, 12]), {}, "hold", 40.0, 8),
        (
            "third failing session -> deload 10 %",
            sets([6, 6, 6]),
            {"consecutive_failures": 2},
            "deload",
            35.0,
            8,
        ),
        (
            "second failing session -> hold",
            sets([6, 6, 6]),
            {"consecutive_failures": 1},
            "hold",
            40.0,
            8,
        ),
        (
            "maintenance holds at max reps",
            sets([12, 12, 12]),
            {"goal": "maintenance"},
            "hold",
            40.0,
            8,
        ),
        (
            "cutting holds at max reps",
            sets([12, 12, 12]),
            {"goal": "cutting"},
            "hold",
            40.0,
            8,
        ),
        (
            "maintenance adds reps inside the range, never weight",
            sets([10, 10, 10]),
            {"goal": "maintenance"},
            "increase_reps",
            40.0,
            11,
        ),
        (
            "cutting still deloads when failing",
            sets([5, 5, 5]),
            {"goal": "cutting", "consecutive_failures": 2},
            "deload",
            35.0,
            8,
        ),
        (
            "strength 5 % of 100 kg on a barbell",
            sets([6, 6, 6], 100.0),
            {
                "goal": "strength",
                "equipment": "barbell",
                "target_weight_kg": 100.0,
                "reps_min": 3,
                "reps_max": 6,
            },
            "increase_weight",
            105.0,
            3,
        ),
        (
            "endurance on small weights moves one plate step",
            sets([20, 20, 20], 10.0),
            {
                "goal": "endurance",
                "target_weight_kg": 10.0,
                "reps_min": 13,
                "reps_max": 20,
            },
            "increase_weight",
            12.5,
            13,
        ),
        (
            "linear (one rep target) goes heavier when met",
            sets([8, 8, 8]),
            {"rule": "linear", "reps_min": 8, "reps_max": 8},
            "increase_weight",
            42.5,
            8,
        ),
    ],
)
def test_rules(
    name: str,
    logged: list[LoggedSet],
    kw: dict[str, object],
    action: str,
    weight: float,
    reps: int,
) -> None:
    result = suggest(inp(logged, **kw))
    assert (result.action, result.weight_kg, result.reps) == (action, weight, reps), name
    assert result.reason


def test_failure_counter_resets_on_success_and_deload() -> None:
    assert suggest(inp(sets([12, 12, 12]), consecutive_failures=2)).consecutive_failures == 0
    assert suggest(inp(sets([6, 6, 6]), consecutive_failures=2)).consecutive_failures == 0
    assert suggest(inp(sets([6, 6, 6]), consecutive_failures=1)).consecutive_failures == 2
    assert suggest(inp(sets([10, 10, 10]), consecutive_failures=1)).consecutive_failures == 0


def test_skipped_exercise_and_missing_targets() -> None:
    assert suggest(inp([])).action == "none"
    assert suggest(inp(sets([8]), reps_min=None, reps_max=None)).action == "none"


def test_sets_at_other_weights_are_ignored() -> None:
    result = suggest(inp(sets([12, 12, 12], 30.0)))
    assert result.action == "hold"  # no working sets at 40 kg: a failure, not a progression


def test_first_session_calibrates_the_weight() -> None:
    result = suggest(inp(sets([10, 10, 10], 41.0), is_first_session=True, target_weight_kg=None))
    assert result.action == "calibrate"
    assert result.weight_kg == 40.0  # 41 kg on the 2.5 kg plate grid
    assert result.reps == 8


def test_deload_never_adds_weight_below_the_barbell() -> None:
    result = suggest(
        inp(
            sets([2, 2, 2], 15.0),
            equipment="barbell",
            target_weight_kg=15.0,
            consecutive_failures=2,
        )
    )
    assert result.action == "hold"
    assert result.weight_kg == min_weight_kg("barbell")


# ───────────── step sizing ─────────────


def test_step_is_smaller_for_advanced_older_lighter_athletes() -> None:
    base = inp([], goal="strength", target_weight_kg=100.0, equipment="barbell")
    young = weight_increase_kg(base, 100.0, 2.5)
    careful = weight_increase_kg(
        inp(
            [],
            goal="strength",
            target_weight_kg=100.0,
            equipment="barbell",
            experience="advanced",
            age_years=62,
            lifestyle="sedentary",
            body_weight_kg=55.0,
        ),
        100.0,
        2.5,
    )
    assert young == 5.0
    assert careful == 2.5  # never below one plate step


def test_beginners_step_more_than_advanced() -> None:
    beginner = weight_increase_kg(inp([], goal="strength", experience="beginner"), 100.0, 2.5)
    advanced = weight_increase_kg(inp([], goal="strength", experience="advanced"), 100.0, 2.5)
    assert beginner > advanced


def test_factors_default_to_one_when_unknown() -> None:
    assert set(step_factors(inp([])).values()) == {1.0}


def test_inputs_never_hold_the_age() -> None:
    result = suggest(inp(sets([12, 12, 12]), age_years=47, body_weight_kg=83.0))
    dumped = repr(result.inputs)
    assert "47" not in dumped.replace("0.85", "")  # the age itself is not stored
    assert "age_years" not in result.inputs
    assert "body_weight" in result.inputs["step_factors"]


def test_imperial_uses_the_five_pound_grid() -> None:
    result = suggest(inp(sets([12, 12, 12]), imperial=True))
    assert result.action == "increase_weight"
    step_kg = plate_step_kg("machine", True)
    assert (result.weight_kg or 0) - 40.0 >= step_kg - 1e-6


# ───────────── properties ─────────────


goals = st.sampled_from(TRAINING_GOALS)
equipment = st.sampled_from(["barbell", "dumbbell", "machine", "cable", "bodyweight"])


@given(
    goal=goals,
    equip=equipment,
    weight=st.floats(0, 300, allow_nan=False),
    low=st.integers(1, 20),
    span=st.integers(0, 10),
    reps=st.lists(st.integers(0, 40), min_size=0, max_size=6),
    failures=st.integers(0, 5),
    age=st.none() | st.integers(14, 100),
    exp=st.none() | st.sampled_from(["beginner", "intermediate", "advanced"]),
    body=st.none() | st.floats(35, 300, allow_nan=False),
    imperial=st.booleans(),
)
def test_properties(
    goal: str,
    equip: str,
    weight: float,
    low: int,
    span: int,
    reps: list[int],
    failures: int,
    age: int | None,
    exp: str | None,
    body: float | None,
    imperial: bool,
) -> None:
    p = inp(
        sets(reps, weight),
        goal=goal,
        equipment=equip,
        target_weight_kg=weight,
        reps_min=low,
        reps_max=low + span,
        consecutive_failures=failures,
        age_years=age,
        experience=exp,
        body_weight_kg=body,
        imperial=imperial,
    )
    result = suggest(p)
    assert result.reason
    if result.action == "none":
        return
    # Reps stay inside the planned range and the counter stays non-negative.
    assert result.reps is None or low <= result.reps <= low + span
    assert result.consecutive_failures >= 0
    if result.action == "increase_weight":
        assert goal not in PROGRESSION_HOLD_GOALS  # maintenance / cutting never raise the load
        assert result.weight_kg is not None and result.weight_kg > weight
        step = plate_step_kg(equip, imperial)
        cap = max(step, weight * PROGRESSION_MAX_STEP_PCT)
        assert result.weight_kg - weight <= cap + step + 1e-6
    if result.action == "deload":
        assert result.weight_kg is not None and result.weight_kg < weight
    if result.action in ("hold", "increase_reps"):
        assert result.weight_kg is not None
        assert result.weight_kg <= max(weight, min_weight_kg(equip)) + 1e-6
    if result.action == "increase_reps":
        assert result.weight_kg == weight


@given(
    weight=st.floats(1, 300, allow_nan=False),
    goal=goals,
    age=st.none() | st.integers(14, 100),
    exp=st.none() | st.sampled_from(["beginner", "intermediate", "advanced"]),
)
def test_step_is_one_plate_step_at_least(
    weight: float, goal: str, age: int | None, exp: str | None
) -> None:
    p = inp([], goal=goal, age_years=age, experience=exp)
    step = 2.5
    inc = weight_increase_kg(p, weight, step)
    assert inc >= step - 1e-9
    assert abs(inc / step - round(inc / step)) < 1e-9
