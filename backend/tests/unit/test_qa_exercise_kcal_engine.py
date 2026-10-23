"""QA tests for the F13.2 exercise kcal engine (issue #84), written independently of the PR.

Hand arithmetic at 72.5 kg: 3.5 × 72.5 ÷ 200 = 1.26875 kcal per MET-minute.
"""

import math

import pytest

from app.engines.exercise_kcal import (
    ExtraActivity,
    LoggedExercise,
    PlannedDay,
    PlannedExercise,
    exercise_kcal,
    logged_kcal,
    planned_weekly_kcal,
)

PER_MET_MINUTE = 1.26875  # 3.5 × 72.5 ÷ 200


def test_qa_issue_reference_cases_within_one_kcal():
    # Issue #84 AC: MET 6.0, 80 kg, 30 min → 252; MET 3.5, 60 kg, 45 min → 165 (± 1 kcal).
    assert abs(exercise_kcal(6.0, 80, 30).kcal - 252) <= 1
    assert abs(exercise_kcal(3.5, 60, 45).kcal - 165) <= 1


def test_qa_three_day_template_at_non_round_weight():
    template = [
        PlannedDay(
            "mon",
            [
                PlannedExercise("strength", met=6.0, sets=4, rest_seconds=120),  # 11 min
                PlannedExercise("strength", met=5.0, sets=3, rest_seconds=90),  # 6.75 min
            ],
        ),
        PlannedDay(
            "wed",
            [
                PlannedExercise("bodyweight", met=3.8, sets=3, rest_seconds=60),  # 5.25 min
                PlannedExercise("timed", met=8.0, sets=1, target_seconds=1200),  # 20 min
            ],
        ),
        PlannedDay("fri", [PlannedExercise("timed", met=3.8, sets=3, target_seconds=45)]),  # 2.25
    ]
    # mon: (6 × 11 + 5 × 6.75) × 1.26875 = 99.75 × 1.26875 = 126.5578125
    # wed: (3.8 × 5.25 + 8 × 20) × 1.26875 = 179.95 × 1.26875 = 228.3115625
    # fri: 3.8 × 2.25 × 1.26875 = 8.55 × 1.26875 = 10.8478125
    # week: 365.7171875 → 366; daily 365.7171875 ÷ 7 = 52.2453… → 52
    result = planned_weekly_kcal(template, 72.5)

    assert [d.kcal_exact for d in result.days] == pytest.approx(
        [126.5578125, 228.3115625, 10.8478125]
    )
    assert result.weekly_kcal_exact == pytest.approx(365.7171875)
    assert result.weekly_kcal == 366
    assert result.daily_kcal_exact == pytest.approx(365.7171875 / 7)
    assert result.daily_kcal == 52
    assert "body weight 72.5 kg" in result.explanation
    assert "MET 6 × 11 min" in result.explanation
    assert "MET 3.8 × 2.25 min" in result.explanation


def test_qa_logged_session_extra_set_extra_exercise_and_activity():
    # Planned squat 3 sets + 1 extra set = 4 × (120 + 45) ÷ 60 = 11 min × MET 6 = 66 MET-min
    # Extra curls (not planned), 2 sets at the 90 s rest-timer default = 4.5 min × 3 = 13.5
    # Timed plank logged 50 s + 40 s = 1.5 min × 3.8 = 5.7
    # Extra activity football 30 min × 7 = 210
    # Σ = 295.2 MET-min × 1.26875 = 374.535 → 375 (rounded once)
    result = logged_kcal(
        [
            LoggedExercise("strength", met=6.0, performed_sets=4, rest_seconds=120),
            LoggedExercise("strength", met=3.0, performed_sets=2),
            LoggedExercise("timed", met=3.8, durations_seconds=(50, 40)),
        ],
        72.5,
        [ExtraActivity(met=7.0, minutes=30)],
    )
    assert result.kcal_exact == pytest.approx(374.535)
    assert result.kcal == 375
    assert [p.minutes for p in result.exercises] == pytest.approx([11, 4.5, 1.5])
    assert "body weight 72.5 kg" in result.explanation
    assert "MET 7 × 30 min" in result.explanation
    assert "2 performed sets × (90 s rest + 45 s work)" in result.exercises[1].explanation


def test_qa_activity_explanation_names_met_weight_and_minutes():
    part = logged_kcal([], 72.5, [ExtraActivity(met=7.0, minutes=30)]).activities[0]
    assert "MET × 3.5 × body weight kg ÷ 200 × minutes" in part.explanation
    assert "7 × 3.5 × 72.5 kg ÷ 200 × 30 min" in part.explanation


@pytest.mark.parametrize(
    "call",
    [
        lambda: planned_weekly_kcal(
            [PlannedDay("mon", [PlannedExercise("strength", 5.0, sets=True, rest_seconds=90)])], 80
        ),
        lambda: planned_weekly_kcal(
            [PlannedDay("mon", [PlannedExercise("strength", 5.0, sets=3, rest_seconds=True)])], 80
        ),
        lambda: planned_weekly_kcal(
            [PlannedDay("mon", [PlannedExercise("timed", 5.0, 3, target_seconds=math.nan)])], 80
        ),
        lambda: planned_weekly_kcal(
            [PlannedDay("mon", [PlannedExercise("timed", 5.0, 3, target_seconds=math.inf)])], 80
        ),
        lambda: planned_weekly_kcal(
            [PlannedDay("mon", [PlannedExercise("timed", 5.0, 3, target_seconds=-60)])], 80
        ),
        lambda: planned_weekly_kcal([], True),
        lambda: planned_weekly_kcal([], math.nan),
        lambda: logged_kcal([LoggedExercise("timed", 5.0, durations_seconds=(True,))], 80),
        lambda: logged_kcal([LoggedExercise("timed", 5.0, durations_seconds=(math.inf,))], 80),
        lambda: logged_kcal([LoggedExercise("strength", 5.0, performed_sets=-1)], 80),
        lambda: logged_kcal([LoggedExercise("strength", math.nan, performed_sets=3)], 80),
        lambda: logged_kcal([], 80, [ExtraActivity(met=True, minutes=30)]),
        lambda: logged_kcal([], 80, [ExtraActivity(met=7.0, minutes=math.inf)]),
        lambda: logged_kcal([], 80, [ExtraActivity(met=7.0, minutes=-1)]),
        lambda: logged_kcal([], math.inf),
        lambda: logged_kcal([LoggedExercise("cardio", 5.0)], 80),  # type: ignore[arg-type]
    ],
)
def test_qa_invalid_inputs_on_planned_and_logged_paths_raise_value_error(call):
    with pytest.raises(ValueError):
        call()
