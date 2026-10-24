"""F5 Training plan generator: split, exercise choice, sets/reps, cardio, weekday placement.

Pure (ADR 0004): the catalog comes in as plain data, the plan and its `explanation`s go out.
No database, HTTP or clock access; the same inputs always give the same plan (F5.5), because
every choice is a sort over `(rank, name, id)` with no randomness.

How a plan is built (spec F5, D54):
- Days per week pick the split (2-3 full body A/B, 4 upper/lower, 5 ULPPL, 6 PPL x2). Each
  day is an ordered list of slots (muscle group + main/accessory role); the highest-priority
  slots come first, so a short session simply holds fewer exercises.
- A slot takes the best-ranked exercise the equipment variant allows, preferring exercises
  not yet used elsewhere in the plan. An avoided exercise is replaced by one of the same
  muscle group and equipment, else by a bodyweight exercise of the same muscle group, else
  dropped with a warning (F5.6).
- Duration = sum(sets x (rest + 45 s)) + cardio minutes + 5 min warm-up (D54) and never
  exceeds the session length (F5.1).
- Strength targets carry no weight in week 1 (F5.4). Beginners' strength main lifts use
  linear progression with fixed reps at the middle of the range, rounded down (D54).
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import Literal

from app.engines.constants import (
    ACCESSORY_PREFERRED_EQUIPMENT,
    CALIBRATION_HINT,
    CARDIO_STEP_MINUTES,
    EQUIPMENT_BY_VARIANT,
    GOAL_CARDIO_MINUTES,
    GOAL_REP_RANGES,
    MIN_SETS_BY_EXPERIENCE,
    PLAN_MAX_DAYS,
    PLAN_MIN_DAYS,
    PLAN_MIN_EXERCISES_PER_SESSION,
    PLAN_REST_SECONDS,
    PLAN_TIMED_TARGET_SECONDS,
    SETS_BY_EXPERIENCE,
    WARMUP_MINUTES,
    WORKING_SECONDS_PER_SET,
)

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
Rule = Literal["linear", "double"]

# --- inputs ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CatalogExercise:
    """The catalog fields the generator needs (an `Exercise` row, as plain data)."""

    id: str
    name: str
    muscle_group: str
    equipment: str
    type: str  # strength | bodyweight | timed
    met: float
    increment_kg: float = 0.0


@dataclass(frozen=True, slots=True)
class PlanRequest:
    experience: str  # beginner | intermediate | advanced
    goal: str  # muscle_gain | recomposition | cutting | maintenance | wellness
    days_per_week: int
    preferred_days: Sequence[str]  # weekdays, exactly `days_per_week` distinct values
    session_minutes: int
    equipment: str  # full_gym | home_dumbbells | bodyweight_only
    avoided_exercise_ids: Collection[str] = ()


# --- outputs --------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GeneratedExercise:
    exercise_id: str
    name: str
    order: int
    sets: int
    reps_min: int | None
    reps_max: int | None
    target_weight_kg: float | None  # always None in week 1 (calibration, F5.4)
    target_seconds: int | None
    rest_seconds: int
    rule: Rule
    increment_kg: float
    deload_enabled: bool
    calibration_hint: str | None
    is_cardio: bool = False


@dataclass(frozen=True, slots=True)
class GeneratedDay:
    weekday: str
    name: str
    exercises: tuple[GeneratedExercise, ...]
    estimated_seconds: int
    explanation: str


@dataclass(frozen=True, slots=True)
class GeneratedPlan:
    days: tuple[GeneratedDay, ...]
    warnings: tuple[str, ...]
    explanation: str


# --- split templates ------------------------------------------------------------------------
# A slot is (muscle group, role). Order = priority: the first slots survive a short session.

Slot = tuple[str, Literal["main", "accessory"]]
M: Literal["main"] = "main"
A: Literal["accessory"] = "accessory"

_FULL_A: tuple[Slot, ...] = (
    ("quads", M),
    ("chest", M),
    ("back", M),
    ("shoulders", A),
    ("hamstrings", A),
    ("core", A),
    ("biceps", A),
    ("triceps", A),
)
_FULL_B: tuple[Slot, ...] = (
    ("hamstrings", M),
    ("shoulders", M),
    ("back", M),
    ("chest", A),
    ("glutes", A),
    ("core", A),
    ("triceps", A),
    ("biceps", A),
)
_UPPER: tuple[Slot, ...] = (
    ("chest", M),
    ("back", M),
    ("shoulders", M),
    ("back", A),
    ("chest", A),
    ("biceps", A),
    ("triceps", A),
    ("shoulders", A),
)
_LOWER: tuple[Slot, ...] = (
    ("quads", M),
    ("hamstrings", M),
    ("glutes", A),
    ("quads", A),
    ("calves", A),
    ("core", A),
)
_PUSH: tuple[Slot, ...] = (
    ("chest", M),
    ("shoulders", M),
    ("chest", A),
    ("triceps", A),
    ("shoulders", A),
    ("triceps", A),
)
_PULL: tuple[Slot, ...] = (
    ("back", M),
    ("back", A),
    ("biceps", A),
    ("shoulders", A),
    ("back", A),
    ("biceps", A),
)
_LEGS: tuple[Slot, ...] = (
    ("quads", M),
    ("hamstrings", M),
    ("glutes", A),
    ("quads", A),
    ("calves", A),
    ("core", A),
)

_SPLITS: dict[int, tuple[tuple[str, tuple[Slot, ...]], ...]] = {
    2: (("Full body A", _FULL_A), ("Full body B", _FULL_B)),
    3: (("Full body A", _FULL_A), ("Full body B", _FULL_B), ("Full body A", _FULL_A)),
    4: (("Upper A", _UPPER), ("Lower A", _LOWER), ("Upper B", _UPPER), ("Lower B", _LOWER)),
    5: (
        ("Upper", _UPPER),
        ("Lower", _LOWER),
        ("Push", _PUSH),
        ("Pull", _PULL),
        ("Legs", _LEGS),
    ),
    6: (
        ("Push A", _PUSH),
        ("Pull A", _PULL),
        ("Legs A", _LEGS),
        ("Push B", _PUSH),
        ("Pull B", _PULL),
        ("Legs B", _LEGS),
    ),
}
_SPLIT_NAMES = {
    2: "full body (A/B)",
    3: "full body (A/B/A)",
    4: "upper / lower x2",
    5: "upper / lower / push / pull / legs",
    6: "push / pull / legs x2",
}

_STRENGTH_TYPES = frozenset({"strength", "bodyweight"})
_SET_SECONDS = PLAN_REST_SECONDS + WORKING_SECONDS_PER_SET


# --- helpers --------------------------------------------------------------------------------


def _validate(req: PlanRequest) -> None:
    if not PLAN_MIN_DAYS <= req.days_per_week <= PLAN_MAX_DAYS:
        raise ValueError(f"days_per_week must be {PLAN_MIN_DAYS}-{PLAN_MAX_DAYS}")
    if len(set(req.preferred_days)) != len(req.preferred_days) or len(req.preferred_days) != (
        req.days_per_week
    ):
        raise ValueError("preferred_days must be distinct and match days_per_week")
    if any(d not in WEEKDAYS for d in req.preferred_days):
        raise ValueError("preferred_days must be weekdays mon..sun")
    if req.equipment not in EQUIPMENT_BY_VARIANT:
        raise ValueError(f"unknown equipment variant {req.equipment!r}")
    if req.goal not in GOAL_REP_RANGES:
        raise ValueError(f"unknown goal {req.goal!r}")
    if req.experience not in SETS_BY_EXPERIENCE:
        raise ValueError(f"unknown experience {req.experience!r}")
    if req.session_minutes <= 0:
        raise ValueError("session_minutes must be positive")


def _ranked(
    catalog: Sequence[CatalogExercise],
    group: str,
    role: str,
    allowed: frozenset[str],
    preferred: frozenset[str] = frozenset(),
) -> list[CatalogExercise]:
    """Candidates for a slot, best first. Main lifts: heaviest compound (highest MET) first;
    accessories: lightest (isolation) first, after the `preferred` equipment tier (#110).
    Ties break on name, then id."""
    types = _STRENGTH_TYPES if role == M else _STRENGTH_TYPES | {"timed"}
    pool = [
        e for e in catalog if e.muscle_group == group and e.equipment in allowed and e.type in types
    ]
    sign = -1.0 if role == M else 1.0
    tier = preferred if role != M else frozenset()
    return sorted(pool, key=lambda e: (e.equipment not in tier, sign * e.met, e.name.lower(), e.id))


def _choose(
    ranked: list[CatalogExercise],
    all_types: Sequence[CatalogExercise],
    used_day: set[str],
    used_plan: set[str],
    avoided: frozenset[str],
    fallback_types: frozenset[str],
    preferred: frozenset[str] = frozenset(),
) -> tuple[CatalogExercise | None, CatalogExercise | None]:
    """Return (exercise, avoided_original). exercise None = nothing to add.

    `avoided_original` is set when the exercise replaces an avoided one, or when the avoided
    exercise had to be dropped (exercise None).
    """
    pool = [e for e in ranked if e.id not in used_day]
    if not pool:
        return None, None
    if preferred and any(e.equipment in preferred for e in pool):
        # Equipment tier outranks "not yet used in the plan": stay inside the preferred tier.
        pool = [e for e in pool if e.equipment in preferred]
    first = next((e for e in pool if e.id not in used_plan), pool[0])
    if first.id not in avoided:
        return first, None
    same = [e for e in pool if e.equipment == first.equipment and e.id not in avoided]
    if same:
        return next((e for e in same if e.id not in used_plan), same[0]), first
    bodyweight = [
        e
        for e in all_types
        if e.muscle_group == first.muscle_group
        and e.equipment == "bodyweight"
        and e.type in fallback_types
        and e.id not in avoided
        and e.id not in used_day
    ]
    bodyweight.sort(key=lambda e: (e.met, e.name.lower(), e.id))
    if bodyweight:
        return next((e for e in bodyweight if e.id not in used_plan), bodyweight[0]), first
    return None, first


def _cardio_minutes(req: PlanRequest) -> int:
    """Goal cardio minutes, shortened only if the session could not hold one exercise."""
    minutes = GOAL_CARDIO_MINUTES[req.goal]
    min_block = (
        PLAN_MIN_EXERCISES_PER_SESSION * MIN_SETS_BY_EXPERIENCE[req.experience] * (_SET_SECONDS)
    )
    while minutes > 0 and (WARMUP_MINUTES + minutes) * 60 + min_block > req.session_minutes * 60:
        minutes -= CARDIO_STEP_MINUTES
    return max(minutes, 0)


def _build_day(
    name: str,
    weekday: str,
    slots: tuple[Slot, ...],
    req: PlanRequest,
    catalog: Sequence[CatalogExercise],
    used_plan: set[str],
    avoided: frozenset[str],
    cardio_minutes: int,
    warnings: dict[str, None],
) -> GeneratedDay:
    allowed = EQUIPMENT_BY_VARIANT[req.equipment]
    preferred = ACCESSORY_PREFERRED_EQUIPMENT.get(req.equipment, frozenset())
    allowed_catalog = [e for e in catalog if e.equipment in allowed]
    main_sets, acc_sets = SETS_BY_EXPERIENCE[req.experience]
    min_sets = MIN_SETS_BY_EXPERIENCE[req.experience]
    (main_lo, main_hi), (acc_lo, acc_hi) = GOAL_REP_RANGES[req.goal]
    budget = (req.session_minutes - WARMUP_MINUTES - cardio_minutes) * 60
    spent = 0
    used_day: set[str] = set()
    items: list[GeneratedExercise] = []
    notes: list[str] = []

    for group, role in slots:
        if budget - spent < min_sets * _SET_SECONDS:
            break
        ex, original = _choose(
            _ranked(catalog, group, role, allowed, preferred if role != M else frozenset()),
            allowed_catalog,
            used_day,
            used_plan,
            avoided,
            _STRENGTH_TYPES if role == M else _STRENGTH_TYPES | {"timed"},
            preferred if role != M else frozenset(),
        )
        if ex is None:
            if original is not None:
                warnings[
                    f"Avoided exercise '{original.name}' has no alternative and was dropped "
                    f"from {name}."
                ] = None
            continue
        sets = main_sets if role == M else acc_sets
        if spent + sets * _SET_SECONDS > budget:
            sets = min_sets
            if spent + sets * _SET_SECONDS > budget:
                continue
        spent += sets * _SET_SECONDS
        used_day.add(ex.id)
        used_plan.add(ex.id)
        if original is not None:
            notes.append(f"{original.name} (avoided) replaced by {ex.name}")
        lo, hi = (main_lo, main_hi) if role == M else (acc_lo, acc_hi)
        items.append(_exercise(ex, len(items), sets, role, lo, hi, req.experience))

    if cardio_minutes > 0:
        cardio = _cardio(catalog, allowed, used_plan, avoided, len(items), cardio_minutes)
        if cardio is None:
            warnings[f"No cardio exercise is available for {name}; cardio was left out."] = None
        else:
            used_plan.add(cardio.exercise_id)
            items.append(cardio)
            spent += cardio_minutes * 60

    total = WARMUP_MINUTES * 60 + spent
    explanation = (
        f"{name}: {len(items)} exercises, about {round(total / 60)} min of "
        f"{req.session_minutes} min (warm-up {WARMUP_MINUTES} min, cardio "
        f"{cardio_minutes} min, sets x (rest {PLAN_REST_SECONDS} s + "
        f"{WORKING_SECONDS_PER_SET} s work))."
    )
    if notes:
        explanation += " " + "; ".join(notes) + "."
    return GeneratedDay(weekday, name, tuple(items), total, explanation)


def _exercise(
    ex: CatalogExercise, order: int, sets: int, role: str, lo: int, hi: int, experience: str
) -> GeneratedExercise:
    timed = ex.type == "timed"
    linear = role == M and experience == "beginner" and ex.type == "strength"
    reps_min: int | None = None if timed else (lo + hi) // 2 if linear else lo
    reps_max: int | None = None if timed else (lo + hi) // 2 if linear else hi
    return GeneratedExercise(
        exercise_id=ex.id,
        name=ex.name,
        order=order,
        sets=sets,
        reps_min=reps_min,
        reps_max=reps_max,
        target_weight_kg=None,
        target_seconds=PLAN_TIMED_TARGET_SECONDS if timed else None,
        rest_seconds=PLAN_REST_SECONDS,
        rule="linear" if linear else "double",
        increment_kg=ex.increment_kg,
        deload_enabled=True,
        calibration_hint=CALIBRATION_HINT if ex.type == "strength" else None,
    )


def _cardio(
    catalog: Sequence[CatalogExercise],
    allowed: frozenset[str],
    used_plan: set[str],
    avoided: frozenset[str],
    order: int,
    minutes: int,
) -> GeneratedExercise | None:
    pool = sorted(
        (
            e
            for e in catalog
            if e.muscle_group == "cardio" and e.type == "timed" and e.equipment in allowed
        ),
        key=lambda e: (e.name.lower(), e.id),
    )
    ok = [e for e in pool if e.id not in avoided]
    if not ok:
        return None
    ex = next((e for e in ok if e.id not in used_plan), ok[0])
    return GeneratedExercise(
        exercise_id=ex.id,
        name=ex.name,
        order=order,
        sets=1,
        reps_min=None,
        reps_max=None,
        target_weight_kg=None,
        target_seconds=minutes * 60,
        rest_seconds=0,
        rule="double",
        increment_kg=ex.increment_kg,
        deload_enabled=True,
        calibration_hint=None,
        is_cardio=True,
    )


# --- public API -----------------------------------------------------------------------------


def generate_plan(req: PlanRequest, catalog: Sequence[CatalogExercise]) -> GeneratedPlan:
    """Generate the weekly training plan (F5). Raises `ValueError` on invalid input."""
    _validate(req)
    avoided = frozenset(req.avoided_exercise_ids)
    weekdays = sorted(req.preferred_days, key=WEEKDAYS.index)
    cardio_minutes = _cardio_minutes(req)
    used_plan: set[str] = set()
    warnings: dict[str, None] = {}
    days = tuple(
        _build_day(name, weekday, slots, req, catalog, used_plan, avoided, cardio_minutes, warnings)
        for weekday, (name, slots) in zip(weekdays, _SPLITS[req.days_per_week], strict=True)
    )
    (main_lo, main_hi), (acc_lo, acc_hi) = GOAL_REP_RANGES[req.goal]
    explanation = (
        f"{req.days_per_week} days a week gives a {_SPLIT_NAMES[req.days_per_week]} split on "
        f"{', '.join(weekdays)}. Equipment: {req.equipment}. Goal {req.goal}: main lifts "
        f"{main_lo}-{main_hi} reps, accessories {acc_lo}-{acc_hi} reps, {cardio_minutes} min "
        f"cardio per session. {req.experience.capitalize()} sets: "
        f"{SETS_BY_EXPERIENCE[req.experience][0]} on main lifts, "
        f"{SETS_BY_EXPERIENCE[req.experience][1]} on accessories. Progression: "
        + (
            "linear on strength main lifts (fixed reps at the middle of the range), double "
            "progression elsewhere"
            if req.experience == "beginner"
            else "double progression"
        )
        + ", deload on. Week-1 strength weights are empty: calibrate on the first session."
    )
    return GeneratedPlan(days, tuple(warnings), explanation)
