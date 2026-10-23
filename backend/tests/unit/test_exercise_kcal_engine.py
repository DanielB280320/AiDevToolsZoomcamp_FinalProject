"""F13.2 exercise kcal engine (issue #84): table-driven hand-computed cases + property tests.

Hand arithmetic: with 80 kg, 3.5 × 80 ÷ 200 = 1.4, so kcal = MET × 1.4 × minutes.
"""

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engines import constants
from app.engines.exercise_kcal import (
    ExtraActivity,
    LoggedExercise,
    PlannedDay,
    PlannedExercise,
    duration_minutes,
    exercise_kcal,
    logged_kcal,
    planned_weekly_kcal,
    round_kcal,
    set_based_minutes,
)

# --- F13.1 MET formula ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("met", "weight_kg", "minutes", "expected_exact", "expected_kcal"),
    [
        # 6.0 × 3.5 × 80 ÷ 200 = 8.4 kcal/min × 30 = 252
        (6.0, 80, 30, 252.0, 252),
        # 3.5 × 3.5 × 60 ÷ 200 = 3.675 kcal/min × 45 = 165.375
        (3.5, 60, 45, 165.375, 165),
        # 8.0 × 3.5 × 70 ÷ 200 = 9.8 kcal/min × 60 = 588 (football 60 min)
        (8.0, 70, 60, 588.0, 588),
        # 5.0 × 3.5 × 80 ÷ 200 = 7 kcal/min × 6.75 = 47.25
        (5.0, 80, 6.75, 47.25, 47),
        # 1 × 3.5 × 100 ÷ 200 = 1.75 × 1 = 1.75 → 2 (half-up region)
        (1.0, 100, 1, 1.75, 2),
        # 2 × 3.5 × 50 ÷ 200 = 1.75 × 2 = 3.5 → 4 (half up, not banker's 4 either way)
        (2.0, 50, 2, 3.5, 4),
        # 1 × 3.5 × 100 ÷ 200 = 1.75 × 1.5 = 2.625 → 3
        (1.0, 100, 1.5, 2.625, 3),
        (6.0, 80, 0, 0.0, 0),
    ],
)
def test_met_formula_hand_computed(met, weight_kg, minutes, expected_exact, expected_kcal):
    result = exercise_kcal(met, weight_kg, minutes)
    assert result.kcal_exact == pytest.approx(expected_exact)
    assert result.kcal == expected_kcal
    assert abs(result.kcal - expected_exact) <= 1
    assert isinstance(result.kcal, int)


def test_round_kcal_is_half_up_not_bankers():
    assert round_kcal(2.5) == 3
    assert round_kcal(3.5) == 4
    assert round_kcal(0.49) == 0
    assert round_kcal(0.0) == 0


def test_explanation_names_formula_and_numbers():
    result = exercise_kcal(6.0, 80, 30)
    assert "MET × 3.5 × body weight kg ÷ 200 × minutes" in result.explanation
    assert "6 × 3.5 × 80 kg ÷ 200 × 30 min = 252 kcal" in result.explanation


# --- F13.1 minute estimation ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("sets", "rest_seconds", "expected_minutes"),
    [
        (3, 90, 6.75),  # 3 × (90 + 45) ÷ 60
        (4, 120, 11.0),  # 4 × 165 ÷ 60
        (3, 60, 5.25),  # 3 × 105 ÷ 60
        (1, 0, 0.75),  # working time only
        (0, 90, 0.0),  # skipped exercise
    ],
)
def test_set_based_minutes(sets, rest_seconds, expected_minutes):
    assert set_based_minutes(sets, rest_seconds) == pytest.approx(expected_minutes)


@pytest.mark.parametrize(("seconds", "expected_minutes"), [(1200, 20.0), (45, 0.75), (0, 0.0)])
def test_duration_minutes(seconds, expected_minutes):
    assert duration_minutes(seconds) == pytest.approx(expected_minutes)


@pytest.mark.parametrize("exercise_type", ["strength", "bodyweight"])
def test_strength_and_bodyweight_use_the_same_minute_rule(exercise_type):
    # 3 sets × (90 + 45) ÷ 60 = 6.75 min; MET 5 at 80 kg = 7 kcal/min → 47.25
    result = logged_kcal(
        [LoggedExercise(exercise_type, met=5.0, performed_sets=3, rest_seconds=90)], 80
    )
    assert result.exercises[0].minutes == pytest.approx(6.75)
    assert result.kcal_exact == pytest.approx(47.25)
    assert result.kcal == 47
    assert "3 performed sets × (90 s rest + 45 s work) ÷ 60 = 6.75 min" in (
        result.exercises[0].explanation
    )


def test_timed_uses_logged_duration():
    # 1200 s = 20 min; MET 7 at 80 kg = 9.8 kcal/min → 196
    result = logged_kcal(
        [LoggedExercise("timed", met=7.0, durations_seconds=(600, 600))],
        80,
    )
    assert result.exercises[0].minutes == pytest.approx(20.0)
    assert result.kcal == 196


@pytest.mark.parametrize(
    "skipped",
    [
        LoggedExercise("strength", met=5.0, performed_sets=0, rest_seconds=90),
        LoggedExercise("bodyweight", met=3.8, performed_sets=0),
        LoggedExercise("timed", met=7.0, durations_seconds=()),
    ],
)
def test_skipped_exercise_is_zero_minutes_and_zero_kcal(skipped):
    result = logged_kcal([skipped], 80)
    assert result.exercises[0].minutes == 0
    assert result.kcal == 0
    assert result.kcal_exact == 0


def test_extra_exercise_without_planned_rest_uses_default_rest():
    extra = LoggedExercise("strength", met=5.0, performed_sets=2)
    assert extra.rest_seconds == constants.DEFAULT_REST_SECONDS == 90
    # 2 × (90 + 45) ÷ 60 = 4.5 min × 7 = 31.5 → 32
    assert logged_kcal([extra], 80).kcal == 32


# --- planned weekly kcal (F3.4 input) -------------------------------------------------------


def _three_day_template() -> list[PlannedDay]:
    return [
        PlannedDay(
            "mon",
            [
                PlannedExercise("strength", met=5.0, sets=4, rest_seconds=120),
                PlannedExercise("timed", met=3.0, sets=3, target_seconds=60),
            ],
        ),
        PlannedDay(
            "wed",
            [
                PlannedExercise("strength", met=4.0, sets=3, rest_seconds=90),
                PlannedExercise("bodyweight", met=3.8, sets=3, rest_seconds=60),
            ],
        ),
        PlannedDay("fri", [PlannedExercise("timed", met=7.0, sets=1, target_seconds=1200)]),
    ]


def test_planned_weekly_kcal_three_day_template_by_hand():
    # 80 kg → 1.4 × MET kcal per minute.
    # mon: squat 4 × (120 + 45) ÷ 60 = 11 min × 5 × 1.4 = 77
    #      plank 3 × 60 s = 3 min × 3 × 1.4 = 12.6            → 89.6
    # wed: bench 3 × (90 + 45) ÷ 60 = 6.75 min × 4 × 1.4 = 37.8
    #      push-up 3 × (60 + 45) ÷ 60 = 5.25 min × 3.8 × 1.4 = 27.93 → 65.73
    # fri: row 1 × 1200 s = 20 min × 7 × 1.4 = 196           → 196
    mon = 5.0 * 1.4 * 11 + 3.0 * 1.4 * 3
    wed = 4.0 * 1.4 * 6.75 + 3.8 * 1.4 * 5.25
    fri = 7.0 * 1.4 * 20
    weekly = mon + wed + fri  # 351.33
    assert weekly == pytest.approx(351.33)

    result = planned_weekly_kcal(_three_day_template(), 80)

    assert [d.label for d in result.days] == ["mon", "wed", "fri"]
    assert [d.kcal_exact for d in result.days] == pytest.approx([89.6, 65.73, 196.0])
    assert result.weekly_kcal_exact == pytest.approx(weekly)
    assert result.weekly_kcal == 351
    # F3.4: avg_daily_planned_exercise_kcal = weekly ÷ 7 = 50.19
    assert result.daily_kcal_exact == pytest.approx(weekly / 7)
    assert result.daily_kcal_exact == pytest.approx(50.19)
    assert result.daily_kcal == 50


def test_planned_weekly_explanation_lists_formula_weight_met_and_minutes():
    text = planned_weekly_kcal(_three_day_template(), 80).explanation
    assert "MET × 3.5 × body weight kg ÷ 200 × minutes" in text
    assert "body weight 80 kg" in text
    assert "MET 5 × 11 min = 77" in text
    assert "MET 3.8 × 5.25 min = 27.93" in text
    assert "MET 7 × 20 min = 196" in text
    assert "351.33 ÷ 7 = 50 kcal/day" in text


def test_planned_weekly_kcal_with_no_training_days_is_zero():
    result = planned_weekly_kcal([], 80)
    assert (result.weekly_kcal, result.daily_kcal) == (0, 0)
    assert "no training days" in result.explanation


def test_planned_day_without_exercises_counts_zero():
    result = planned_weekly_kcal([PlannedDay("tue", [])], 80)
    assert result.days[0].kcal == 0
    assert "tue: 0" in result.explanation


def test_planned_timed_exercise_requires_target_seconds():
    with pytest.raises(ValueError, match="target_seconds"):
        planned_weekly_kcal([PlannedDay("mon", [PlannedExercise("timed", met=7.0, sets=1)])], 80)


# --- logged session kcal --------------------------------------------------------------------


def test_logged_session_includes_extra_sets_exercises_and_activities():
    # 80 kg → 1.4 × MET per minute.
    # bench planned 3 sets + 1 extra set = 4 performed × (90 + 45) ÷ 60 = 9 min × 4 × 1.4 = 50.4
    # extra exercise (not in plan), curls 2 sets at default 90 s rest = 4.5 min × 3.5 × 1.4 = 22.05
    # bike 2 × 600 s = 20 min × 7 × 1.4 = 196
    # activity football 60 min × 8 × 1.4 = 672
    session = [
        LoggedExercise("strength", met=4.0, performed_sets=4, rest_seconds=90),
        LoggedExercise("strength", met=3.5, performed_sets=2),
        LoggedExercise("timed", met=7.0, durations_seconds=(600, 600)),
    ]
    result = logged_kcal(session, 80, [ExtraActivity(met=8.0, minutes=60)])
    expected = 50.4 + 22.05 + 196 + 672
    assert result.kcal_exact == pytest.approx(expected)
    assert result.kcal == 940  # 940.45
    assert len(result.exercises) == 3
    assert len(result.activities) == 1
    assert result.activities[0].kcal_exact == pytest.approx(exercise_kcal(8.0, 80, 60).kcal_exact)
    assert "MET 8 × 60 min = 672" in result.explanation
    assert "body weight 80 kg" in result.explanation


def test_extra_activity_on_a_rest_day_alone():
    result = logged_kcal([], 70, [ExtraActivity(met=8.0, minutes=60)])
    assert result.kcal == 588
    assert "Exercises: none" in result.explanation


def test_sum_of_three_exercises_is_rounded_once():
    # MET 3 at 80 kg = 4.2 kcal/min; 3 sets × 90 s rest = 6.75 min → 28.35 each.
    # Rounded once: 3 × 28.35 = 85.05 → 85. Rounding each first would give 3 × 28 = 84.
    one = LoggedExercise("strength", met=3.0, performed_sets=3, rest_seconds=90)
    result = logged_kcal([one, one, one], 80)
    assert [p.kcal_exact for p in result.exercises] == pytest.approx([28.35] * 3)
    assert sum(p.kcal for p in result.exercises) == 84
    assert result.kcal_exact == pytest.approx(85.05)
    assert result.kcal == 85


def test_planned_week_is_rounded_once():
    # Same 28.35-kcal exercise on 3 days: weekly 85.05 → 85 (not 84); daily 12.15 → 12.
    day = [PlannedExercise("strength", met=3.0, sets=3, rest_seconds=90)]
    result = planned_weekly_kcal([PlannedDay(d, day) for d in ("mon", "wed", "fri")], 80)
    assert sum(d.kcal for d in result.days) == 84
    assert result.weekly_kcal == 85
    assert result.daily_kcal == 12


# --- validation -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("met", "weight_kg", "minutes"),
    [
        (0, 80, 30),
        (-1, 80, 30),
        (6, 0, 30),
        (6, -80, 30),
        (6, 80, -1),
        (math.nan, 80, 30),
        (6, math.inf, 30),
        (6, 80, math.nan),
        (True, 80, 30),
    ],
)
def test_invalid_formula_inputs_raise(met, weight_kg, minutes):
    with pytest.raises(ValueError):
        exercise_kcal(met, weight_kg, minutes)


@pytest.mark.parametrize(
    "call",
    [
        lambda: set_based_minutes(-1, 90),
        lambda: set_based_minutes(3, -10),
        lambda: duration_minutes(-1),
        lambda: logged_kcal([LoggedExercise("timed", met=7.0, durations_seconds=(-5,))], 80),
        lambda: logged_kcal([LoggedExercise("cardio", met=7.0)], 80),  # type: ignore[arg-type]
        lambda: logged_kcal([], 0),
        lambda: logged_kcal([], 80, [ExtraActivity(met=8.0, minutes=-1)]),
        lambda: planned_weekly_kcal([], -1),
        lambda: planned_weekly_kcal(
            [PlannedDay("mon", [PlannedExercise("timed", met=7.0, sets=-1, target_seconds=60)])],
            80,
        ),
        lambda: planned_weekly_kcal(
            [PlannedDay("mon", [PlannedExercise("strength", met=0, sets=3, rest_seconds=90)])],
            80,
        ),
    ],
)
def test_invalid_engine_inputs_raise(call):
    with pytest.raises(ValueError):
        call()


# --- property tests -------------------------------------------------------------------------

mets = st.floats(min_value=0.5, max_value=25, allow_nan=False, allow_infinity=False)
weights = st.floats(min_value=20, max_value=400, allow_nan=False, allow_infinity=False)
minutes_st = st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False)
factors = st.floats(min_value=0.01, max_value=100, allow_nan=False, allow_infinity=False)


@given(mets, weights, minutes_st)
def test_kcal_is_never_negative(met, weight_kg, minutes):
    result = exercise_kcal(met, weight_kg, minutes)
    assert result.kcal >= 0
    assert result.kcal_exact >= 0
    assert abs(result.kcal - result.kcal_exact) <= 0.5


@given(mets, weights, minutes_st, factors)
def test_kcal_is_linear_in_minutes(met, weight_kg, minutes, k):
    base = exercise_kcal(met, weight_kg, minutes).kcal_exact
    scaled = exercise_kcal(met, weight_kg, minutes * k).kcal_exact
    assert math.isclose(scaled, base * k, rel_tol=1e-9, abs_tol=1e-9)


@given(mets, weights, minutes_st, factors)
def test_kcal_is_linear_in_body_weight(met, weight_kg, minutes, k):
    base = exercise_kcal(met, weight_kg, minutes).kcal_exact
    scaled = exercise_kcal(met, weight_kg * k, minutes).kcal_exact
    assert math.isclose(scaled, base * k, rel_tol=1e-9, abs_tol=1e-9)


@given(mets, weights)
def test_zero_minutes_is_zero_kcal(met, weight_kg):
    result = exercise_kcal(met, weight_kg, 0)
    assert (result.kcal, result.kcal_exact) == (0, 0)


@given(
    st.one_of(st.floats(max_value=0, allow_nan=False), st.integers(max_value=0)),
    weights,
    minutes_st,
)
def test_met_not_positive_raises(met, weight_kg, minutes):
    with pytest.raises(ValueError):
        exercise_kcal(met, weight_kg, minutes)


@given(mets, st.floats(max_value=0, allow_nan=False), minutes_st)
def test_weight_not_positive_raises(met, weight_kg, minutes):
    with pytest.raises(ValueError):
        exercise_kcal(met, weight_kg, minutes)


@given(mets, weights, st.floats(max_value=-1e-9, allow_nan=False))
def test_negative_minutes_raise(met, weight_kg, minutes):
    with pytest.raises(ValueError):
        exercise_kcal(met, weight_kg, minutes)


@given(st.integers(min_value=0, max_value=20), st.integers(min_value=0, max_value=600))
def test_set_based_minutes_matches_rule(sets, rest_seconds):
    assert set_based_minutes(sets, rest_seconds) == pytest.approx(sets * (rest_seconds + 45) / 60)


@given(
    st.lists(
        st.tuples(
            mets,
            st.integers(min_value=0, max_value=10),
            st.integers(min_value=0, max_value=300),
        ),
        max_size=8,
    ),
    weights,
)
def test_session_total_equals_sum_of_parts_and_rounds_once(parts, weight_kg):
    exercises = [
        LoggedExercise("strength", met=m, performed_sets=s, rest_seconds=r) for m, s, r in parts
    ]
    result = logged_kcal(exercises, weight_kg)
    assert result.kcal_exact == pytest.approx(math.fsum(p.kcal_exact for p in result.exercises))
    assert result.kcal == round_kcal(result.kcal_exact)
    assert result.kcal >= 0


@given(
    st.lists(
        st.lists(
            st.tuples(
                mets,
                st.integers(min_value=0, max_value=10),
                st.integers(min_value=0, max_value=300),
            ),
            max_size=6,
        ),
        max_size=7,
    ),
    weights,
)
def test_planned_daily_is_weekly_over_seven(days, weight_kg):
    template = [
        PlannedDay(
            f"d{i}",
            [PlannedExercise("strength", met=m, sets=s, rest_seconds=r) for m, s, r in day],
        )
        for i, day in enumerate(days)
    ]
    result = planned_weekly_kcal(template, weight_kg)
    assert result.daily_kcal_exact == pytest.approx(result.weekly_kcal_exact / 7)
    assert result.weekly_kcal == round_kcal(result.weekly_kcal_exact)
    assert result.weekly_kcal >= 0
