"""F5 training plan generator: table-driven rules plus property tests on the real seed."""

import itertools
from dataclasses import asdict

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.engines.constants import (
    CALIBRATION_HINT,
    EQUIPMENT_BY_VARIANT,
    GOAL_CARDIO_MINUTES,
    GOAL_REP_RANGES,
    PLAN_REST_SECONDS,
    WARMUP_MINUTES,
    WORKING_SECONDS_PER_SET,
)
from app.engines.training_plan import (
    WEEKDAYS,
    CatalogExercise,
    GeneratedPlan,
    PlanRequest,
    generate_plan,
)
from app.models.exercise import EQUIPMENT
from app.seed_exercises import SEED_EXERCISES

CATALOG = [
    CatalogExercise(
        id=f"ex-{i:03d}",
        name=s.name,
        muscle_group=s.muscle_group,
        equipment=s.equipment,
        type=s.type,
        met=s.met,
        increment_kg=s.increment_kg,
    )
    for i, s in enumerate(SEED_EXERCISES)
]
BY_ID = {e.id: e for e in CATALOG}
BY_NAME = {e.name: e for e in CATALOG}
DAYS = {
    2: ["tue", "fri"],
    3: ["mon", "wed", "fri"],
    4: ["mon", "tue", "thu", "sat"],
    5: ["mon", "tue", "wed", "fri", "sat"],
    6: ["mon", "tue", "wed", "thu", "fri", "sat"],
}
GOALS = list(GOAL_REP_RANGES)
EXPERIENCES = ["beginner", "intermediate", "advanced"]
VARIANTS = list(EQUIPMENT_BY_VARIANT)
LENGTHS = [30, 45, 60, 75, 90]
SETS_RANGE = {"beginner": (2, 3), "intermediate": (3, 4), "advanced": (3, 5)}


def req(
    days: int = 3,
    equipment: str = "full_gym",
    experience: str = "beginner",
    goal: str = "muscle_gain",
    minutes: int = 60,
    avoided: tuple[str, ...] = (),
    preferred: list[str] | None = None,
) -> PlanRequest:
    return PlanRequest(
        experience=experience,
        goal=goal,
        days_per_week=days,
        preferred_days=preferred or DAYS[days],
        session_minutes=minutes,
        equipment=equipment,
        avoided_exercise_ids=avoided,
    )


def check_valid(plan: GeneratedPlan, r: PlanRequest) -> None:
    assert len(plan.days) == r.days_per_week
    assert [d.weekday for d in plan.days] == sorted(r.preferred_days, key=WEEKDAYS.index)
    allowed = EQUIPMENT_BY_VARIANT[r.equipment]
    (mlo, mhi), (alo, ahi) = GOAL_REP_RANGES[r.goal]
    slo, shi = SETS_RANGE[r.experience]
    for day in plan.days:
        ids = [x.exercise_id for x in day.exercises]
        assert len(ids) == len(set(ids)), "no duplicate exercise within a day"
        assert any(not x.is_cardio for x in day.exercises), "a day needs a strength exercise"
        assert day.estimated_seconds <= r.session_minutes * 60
        seconds = WARMUP_MINUTES * 60
        for position, x in enumerate(day.exercises):
            ex = BY_ID[x.exercise_id]
            assert ex.equipment in allowed
            assert x.exercise_id not in r.avoided_exercise_ids
            assert x.target_weight_kg is None
            assert x.order == position
            if x.is_cardio:
                assert ex.muscle_group == "cardio"
                assert x.target_seconds is not None
                seconds += x.target_seconds
                continue
            assert slo <= x.sets <= shi
            seconds += x.sets * (x.rest_seconds + WORKING_SECONDS_PER_SET)
            if ex.type == "timed":
                assert x.reps_min is None and x.target_seconds
            else:
                assert x.reps_min is not None and x.reps_max is not None
                in_main = mlo <= x.reps_min <= x.reps_max <= mhi
                in_acc = alo <= x.reps_min <= x.reps_max <= ahi
                assert in_main or in_acc
            assert (x.calibration_hint == CALIBRATION_HINT) == (ex.type == "strength")
        assert seconds == day.estimated_seconds
        assert day.explanation
    assert plan.explanation


# --- F5.1 every (days, equipment) combination ------------------------------------------------


@pytest.mark.parametrize(
    ("days", "equipment", "experience", "goal", "minutes"),
    list(itertools.product(DAYS, VARIANTS, EXPERIENCES, GOALS, LENGTHS)),
)
def test_every_combination_gives_a_valid_plan(
    days: int, equipment: str, experience: str, goal: str, minutes: int
) -> None:
    r = req(days, equipment, experience, goal, minutes)
    check_valid(generate_plan(r, CATALOG), r)


# --- reps, sets and cardio per goal and experience --------------------------------------------


@pytest.mark.parametrize("goal", GOALS)
def test_reps_and_cardio_follow_the_goal(goal: str) -> None:
    r = req(5, "full_gym", "intermediate", goal, 90)
    plan = generate_plan(r, CATALOG)
    (mlo, mhi), (alo, ahi) = GOAL_REP_RANGES[goal]
    seen = set()
    for day in plan.days:
        cardio = [x for x in day.exercises if x.is_cardio]
        assert cardio[0].target_seconds == GOAL_CARDIO_MINUTES[goal] * 60
        for x in day.exercises:
            if x.is_cardio or x.reps_min is None:
                continue
            assert (x.reps_min, x.reps_max) in {(mlo, mhi), (alo, ahi)}
            seen.add((x.reps_min, x.reps_max))
    assert seen == {(mlo, mhi), (alo, ahi)}


@pytest.mark.parametrize(
    ("experience", "main", "acc"),
    [("beginner", 3, 2), ("intermediate", 4, 3), ("advanced", 5, 3)],
)
def test_sets_follow_experience(experience: str, main: int, acc: int) -> None:
    plan = generate_plan(req(3, "full_gym", experience, "maintenance", 90), CATALOG)
    first = plan.days[0].exercises
    assert first[0].sets == main
    assert first[3].sets == acc


# --- D54 progression defaults -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("goal", "reps"), [("muscle_gain", 8), ("maintenance", 9), ("wellness", 10), ("cutting", 8)]
)
def test_beginner_linear_main_lifts_use_middle_of_range_rounded_down(goal: str, reps: int) -> None:
    plan = generate_plan(req(3, "full_gym", "beginner", goal), CATALOG)
    main = plan.days[0].exercises[0]
    assert (main.rule, main.reps_min, main.reps_max) == ("linear", reps, reps)
    acc = plan.days[0].exercises[3]
    assert acc.rule == "double" and acc.reps_min != acc.reps_max
    assert all(x.deload_enabled for d in plan.days for x in d.exercises)


def test_non_beginners_use_double_progression_with_ranges() -> None:
    for experience in ("intermediate", "advanced"):
        plan = generate_plan(req(3, "full_gym", experience), CATALOG)
        assert {x.rule for d in plan.days for x in d.exercises} == {"double"}
        assert (plan.days[0].exercises[0].reps_min, plan.days[0].exercises[0].reps_max) == (6, 10)


def test_bodyweight_main_lifts_never_use_linear() -> None:
    plan = generate_plan(req(3, "bodyweight_only", "beginner"), CATALOG)
    bodyweight = [x for x in plan.days[0].exercises if BY_ID[x.exercise_id].type == "bodyweight"]
    assert bodyweight and all(x.rule == "double" for x in bodyweight)


# --- F5.2 / F5.6 avoided exercises -------------------------------------------------------------


def ids(*names: str) -> tuple[str, ...]:
    return tuple(BY_NAME[n].id for n in names)


def test_avoided_exercise_is_replaced_by_same_muscle_and_equipment() -> None:
    assert generate_plan(req(3), CATALOG).days[0].exercises[0].name == "Barbell back squat"
    plan = generate_plan(req(3, avoided=ids("Barbell back squat")), CATALOG)
    assert plan.days[0].exercises[0].name == "Front squat"
    assert "Barbell back squat (avoided) replaced by Front squat" in plan.days[0].explanation
    assert not plan.warnings


def test_avoided_without_same_equipment_alternative_falls_back_to_bodyweight() -> None:
    # Gym calves: one machine exercise; the bodyweight calf raise is the fallback.
    r = req(4, avoided=ids("Standing calf raise"), minutes=90)
    plan = generate_plan(r, CATALOG)
    names = [x.name for d in plan.days for x in d.exercises]
    assert "Standing calf raise" not in names
    assert "Bodyweight calf raise" in names
    assert not plan.warnings
    check_valid(plan, r)


def test_avoided_with_no_alternative_at_all_is_dropped_with_a_warning() -> None:
    glutes = tuple(e.id for e in CATALOG if e.muscle_group == "glutes")
    r = req(4, avoided=glutes, minutes=90)
    plan = generate_plan(r, CATALOG)
    names = {x.name for d in plan.days for x in d.exercises}
    assert not names & {e.name for e in CATALOG if e.muscle_group == "glutes"}
    assert plan.warnings and all("dropped" in w and "Avoided exercise" in w for w in plan.warnings)
    assert len(plan.warnings) == len(set(plan.warnings))
    check_valid(plan, r)


def test_cardio_avoided_everywhere_warns_and_leaves_cardio_out() -> None:
    cardio = tuple(e.id for e in CATALOG if e.muscle_group == "cardio")
    plan = generate_plan(req(3, avoided=cardio), CATALOG)
    assert plan.warnings
    assert not any(x.is_cardio for d in plan.days for x in d.exercises)


# --- F5.3 weekday placement --------------------------------------------------------------------


@pytest.mark.parametrize("preferred", [["sun", "wed"], ["sat", "mon", "thu"], ["fri", "thu"]])
def test_sessions_land_exactly_on_preferred_weekdays_in_week_order(preferred: list[str]) -> None:
    plan = generate_plan(req(len(preferred), preferred=preferred), CATALOG)
    assert [d.weekday for d in plan.days] == sorted(preferred, key=WEEKDAYS.index)


@pytest.mark.parametrize(
    ("days", "preferred"),
    [(3, ["mon", "wed"]), (2, ["mon", "mon"]), (2, ["mon", "xyz"])],
)
def test_invalid_preferred_days_are_rejected(days: int, preferred: list[str]) -> None:
    with pytest.raises(ValueError, match="preferred_days"):
        generate_plan(PlanRequest("beginner", "cutting", days, preferred, 60, "full_gym"), CATALOG)


@pytest.mark.parametrize("days", [1, 7])
def test_unsupported_days_are_rejected(days: int) -> None:
    r = PlanRequest("beginner", "cutting", days, list(WEEKDAYS[:days]), 60, "full_gym")
    with pytest.raises(ValueError, match="days_per_week"):
        generate_plan(r, CATALOG)


# --- split table --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("days", "names"),
    [
        (2, ["Full body A", "Full body B"]),
        (3, ["Full body A", "Full body B", "Full body A"]),
        (4, ["Upper A", "Lower A", "Upper B", "Lower B"]),
        (5, ["Upper", "Lower", "Push", "Pull", "Legs"]),
        (6, ["Push A", "Pull A", "Legs A", "Push B", "Pull B", "Legs B"]),
    ],
)
def test_split_per_days_per_week(days: int, names: list[str]) -> None:
    assert [d.name for d in generate_plan(req(days), CATALOG).days] == names


def test_repeated_days_vary_their_exercises() -> None:
    plan = generate_plan(req(6, minutes=90), CATALOG)
    assert plan.days[0].exercises[0].exercise_id != plan.days[3].exercises[0].exercise_id


def test_longer_sessions_hold_more_exercises() -> None:
    counts = [len(generate_plan(req(3, minutes=m), CATALOG).days[0].exercises) for m in LENGTHS]
    assert counts == sorted(counts) and counts[0] < counts[-1]


# --- F5.4 calibration -------------------------------------------------------------------------


def test_week_one_strength_targets_have_no_weight_and_the_hint() -> None:
    plan = generate_plan(req(3), CATALOG)
    strength = [
        x for d in plan.days for x in d.exercises if BY_ID[x.exercise_id].type == "strength"
    ]
    assert strength
    for x in strength:
        assert x.target_weight_kg is None
        assert x.calibration_hint == CALIBRATION_HINT


# --- D54 duration, short sessions -------------------------------------------------------------


def test_duration_formula_matches_d54() -> None:
    plan = generate_plan(req(2, minutes=60, goal="cutting", experience="beginner"), CATALOG)
    day = plan.days[0]
    sets = sum(x.sets for x in day.exercises if not x.is_cardio)
    expected = sets * (PLAN_REST_SECONDS + WORKING_SECONDS_PER_SET) + 15 * 60 + WARMUP_MINUTES * 60
    assert day.estimated_seconds == expected


def test_thirty_minute_wellness_shortens_cardio_to_keep_a_strength_exercise() -> None:
    plan = generate_plan(req(2, experience="advanced", goal="wellness", minutes=30), CATALOG)
    for d in plan.days:
        assert any(not x.is_cardio for x in d.exercises)
        assert d.estimated_seconds <= 30 * 60
        cardio = next(x for x in d.exercises if x.is_cardio)
        assert cardio.target_seconds == 15 * 60


def test_equipment_mapping_matches_catalog_enum() -> None:
    assert EQUIPMENT_BY_VARIANT["full_gym"] == set(EQUIPMENT)
    assert EQUIPMENT_BY_VARIANT["home_dumbbells"] == {"dumbbell", "bodyweight", "band", "none"}
    assert EQUIPMENT_BY_VARIANT["bodyweight_only"] == {"bodyweight", "none"}


# --- F5.5 determinism / snapshot --------------------------------------------------------------

SNAPSHOT_DAY_1 = [
    ("Barbell back squat", 3, 8, 8, "linear"),
    ("Barbell bench press", 3, 8, 8, "linear"),
    ("Deadlift", 3, 8, 8, "linear"),
    ("Dumbbell lateral raise", 2, 8, 12, "double"),
    ("Lying leg curl", 2, 8, 12, "double"),
    ("Dead bug", 2, 8, 12, "double"),
    ("Barbell curl", 2, 8, 12, "double"),
    ("Overhead dumbbell extension", 2, 8, 12, "double"),
    ("Brisk walking", 1, None, None, "double"),
]


def test_snapshot_beginner_three_day_full_gym() -> None:
    plan = generate_plan(req(3, "full_gym", "beginner", "muscle_gain", 60), CATALOG)
    day = plan.days[0]
    shape = [(x.name, x.sets, x.reps_min, x.reps_max, x.rule) for x in day.exercises]
    assert shape == SNAPSHOT_DAY_1


def test_same_inputs_same_plan() -> None:
    r = req(5, "home_dumbbells", "advanced", "cutting", 75)
    assert asdict(generate_plan(r, CATALOG)) == asdict(generate_plan(r, CATALOG))


def test_catalog_order_does_not_change_the_plan() -> None:
    r = req(4, "full_gym", "intermediate", "recomposition", 60)
    a = generate_plan(r, CATALOG)
    b = generate_plan(r, list(reversed(CATALOG)))
    assert asdict(a) == asdict(b)


# --- property tests ---------------------------------------------------------------------------


@st.composite
def requests(draw: st.DrawFn) -> PlanRequest:
    days = draw(st.integers(2, 6))
    preferred = draw(st.permutations(WEEKDAYS).map(lambda p: list(p[:days])))
    avoided = draw(st.lists(st.sampled_from([e.id for e in CATALOG]), max_size=25, unique=True))
    return PlanRequest(
        experience=draw(st.sampled_from(EXPERIENCES)),
        goal=draw(st.sampled_from(GOALS)),
        days_per_week=days,
        preferred_days=preferred,
        session_minutes=draw(st.sampled_from(LENGTHS)),
        equipment=draw(st.sampled_from(VARIANTS)),
        avoided_exercise_ids=avoided,
    )


@settings(max_examples=300, deadline=None)
@given(requests())
def test_property_valid_deterministic_and_avoiding(r: PlanRequest) -> None:
    plan = generate_plan(r, CATALOG)
    check_valid(plan, r)
    assert asdict(plan) == asdict(generate_plan(r, CATALOG))
