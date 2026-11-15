"""F11 goal-driven progression (D107): next targets for one weighted exercise after a session.

Pure (ADR 0004): plain inputs in, a `Suggestion` with `rule`, `inputs` and a `reason` out. No
database, HTTP or clock; the athlete's age is computed by the caller and passed in. It replaces
the per-exercise rule / increment / deload settings for set-based strength exercises: the plan's
training goal decides what to do, the equipment decides the plate step.

Rules, from the logged sets (reps and weight) of the working sets (the sets at the planned target
weight; sets beyond the plan are ignored):
- every planned set reached the top of the rep range -> raise the weight and go back to the bottom
  of the range (maintenance and cutting hold the weight instead);
- every planned set reached at least the bottom of the range, not all the top -> add reps (one
  more than the weakest set, capped at the top), weight unchanged;
- a session where a planned set missed the bottom is a failure; three in a row -> deload 10 %,
  rounded down to the plate step. Fewer failures -> hold weight and reps.
The weight step is sized by the plate step, the goal, experience, age, lifestyle and body weight
(`constants.py`), at least one plate step and at most `PROGRESSION_MAX_STEP_PCT` of the weight.

Every suggestion is informative only (spec section 6.3): the athlete accepts or rejects it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.engines.constants import (
    DELOAD_FACTOR,
    DELOAD_FAILING_SESSIONS,
    PROGRESSION_AGE_FACTORS,
    PROGRESSION_BODY_WEIGHT_FACTORS,
    PROGRESSION_EXPERIENCE_FACTOR,
    PROGRESSION_HOLD_GOALS,
    PROGRESSION_LIFESTYLE_FACTOR,
    PROGRESSION_MAX_STEP_PCT,
    PROGRESSION_STEP_PCT_BY_GOAL,
    TRAINING_GOAL_BY_PROFILE_GOAL,
    TRAINING_GOAL_DEFAULT,
    TRAINING_GOAL_REP_RANGES,
    TRAINING_GOALS,
)
from app.engines.progression import (
    Action,
    LoggedSet,
    Suggestion,
    format_weight,
    min_weight_kg,
    plate_step_kg,
    round_step,
)

_EPS = 1e-9


def default_training_goal(profile_goal: str | None) -> str:
    """The training goal a plan without one gets, from the profile goal (D107)."""
    return TRAINING_GOAL_BY_PROFILE_GOAL.get(profile_goal or "", TRAINING_GOAL_DEFAULT)


def resolve_training_goal(stored: str | None, profile_goal: str | None) -> str:
    """The plan's training goal: the stored one, else the profile-goal default (rollback-safe)."""
    return stored if stored in TRAINING_GOALS else default_training_goal(profile_goal)


def recommended_rep_range(goal: str) -> tuple[int, int]:
    return TRAINING_GOAL_REP_RANGES.get(goal, TRAINING_GOAL_REP_RANGES[TRAINING_GOAL_DEFAULT])


@dataclass(frozen=True)
class GoalProgressionInput:
    goal: str
    equipment: str
    sets_planned: int
    logged_sets: Sequence[LoggedSet]
    target_weight_kg: float | None
    reps_min: int | None
    reps_max: int | None
    rule: str = "double"  # passed through to the suggestion (`linear` keeps one rep target)
    consecutive_failures: int = 0  # failing sessions at this weight before this one
    is_first_session: bool = False
    age_years: int | None = None
    experience: str | None = None
    lifestyle: str | None = None
    body_weight_kg: float | None = None
    imperial: bool = False
    plate_step_kg: float | None = None  # overrides the equipment default


def _bracket(table: Sequence[tuple[float, float]], value: float) -> float:
    for upper, factor in table:
        if value < upper:
            return factor
    return table[-1][1]


def step_factors(p: GoalProgressionInput) -> dict[str, float]:
    """The multipliers applied to the goal's base step; unknown inputs count as 1."""
    return {
        "experience": PROGRESSION_EXPERIENCE_FACTOR.get(p.experience or "", 1.0),
        "age": 1.0 if p.age_years is None else _bracket(PROGRESSION_AGE_FACTORS, p.age_years),
        "lifestyle": PROGRESSION_LIFESTYLE_FACTOR.get(p.lifestyle or "", 1.0),
        "body_weight": (
            1.0
            if p.body_weight_kg is None
            else _bracket(PROGRESSION_BODY_WEIGHT_FACTORS, p.body_weight_kg)
        ),
    }


def weight_increase_kg(p: GoalProgressionInput, weight: float, step: float) -> float:
    """How much to add to `weight` (kg): the goal's share of it times the factors, on the plate
    grid, at least one plate step and at most the cap."""
    pct = PROGRESSION_STEP_PCT_BY_GOAL.get(p.goal, 0.0)
    raw = weight * pct
    for factor in step_factors(p).values():
        raw *= factor
    cap = max(step, round_step(weight * PROGRESSION_MAX_STEP_PCT, step, "down"))
    return min(cap, max(step, round_step(raw, step, "nearest")))


def _inputs(p: GoalProgressionInput) -> dict[str, Any]:
    """Stored with the suggestion (F11.4). Age is never stored, only the factor it gave."""
    return {
        "exercise_type": "strength",
        "rule": p.rule,
        "goal": p.goal,
        "equipment": p.equipment,
        "sets_planned": p.sets_planned,
        "target_weight_kg": p.target_weight_kg,
        "reps_min": p.reps_min,
        "reps_max": p.reps_max,
        "consecutive_failures": p.consecutive_failures,
        "is_first_session": p.is_first_session,
        "step_factors": step_factors(p),
        "logged_sets": [
            {"reps": s.reps, "weight_kg": s.weight_kg, "completed": s.completed}
            for s in p.logged_sets
        ],
    }


def suggest(p: GoalProgressionInput) -> Suggestion:
    """Return the suggestion for one weighted exercise after a finished session."""
    inputs = _inputs(p)

    def out(
        action: Action,
        reason: str,
        *,
        weight: float | None = None,
        reps: int | None = None,
        failures: int | None = None,
    ) -> Suggestion:
        kept = p.consecutive_failures if failures is None else failures
        return Suggestion(p.rule, action, weight, reps, None, reason, kept, inputs)

    done = [s for s in p.logged_sets if s.completed]
    if not done:
        return out("none", "Exercise skipped: no suggestion.")
    low, top = p.reps_min, p.reps_max if p.reps_max is not None else p.reps_min
    if low is None or top is None:
        return out("none", "Missing rep targets: no suggestion.")

    step = p.plate_step_kg or plate_step_kg(p.equipment, p.imperial)
    floor_kg = min_weight_kg(p.equipment)

    if p.is_first_session:
        weights = Counter(s.weight_kg for s in done if s.weight_kg is not None)
        if weights:
            used = max(weights, key=lambda w: (weights[w], w))
            w = max(floor_kg, round_step(used, step, "nearest", floor_kg))
            return out(
                "calibrate",
                f"First session: {weights[used]} of {len(done)} sets at "
                f"{format_weight(used, p.imperial, p.equipment)} → target weight "
                f"{format_weight(w, p.imperial, p.equipment)}.",
                weight=w,
                reps=low,
                failures=0,
            )

    target_w = p.target_weight_kg or 0.0
    work = [s for s in done if abs((s.weight_kg or 0.0) - target_w) < 1e-6][: p.sets_planned]
    reps_done = [s.reps or 0 for s in work]
    wtxt = format_weight(target_w, p.imperial, p.equipment)
    complete = len(work) >= p.sets_planned

    if complete and all(r >= top for r in reps_done):
        if p.goal in PROGRESSION_HOLD_GOALS:
            return out(
                "hold",
                f"All {len(work)} sets reached {top} reps at {wtxt}; the {p.goal} goal keeps the "
                "weight → keep.",
                weight=target_w,
                reps=low,
                failures=0,
            )
        grid_base = floor_kg
        w = round_step(target_w + weight_increase_kg(p, target_w, step), step, "nearest", grid_base)
        if w <= target_w + _EPS:  # target off the grid: still move at least one plate step
            w = max(floor_kg, round_step(target_w, step, "down", grid_base)) + step
        return out(
            "increase_weight",
            f"All {len(work)} sets reached {top} reps at {wtxt} → "
            f"{format_weight(w, p.imperial, p.equipment)} × {low} (step sized for your "
            f"{p.goal} goal, experience, age and body).",
            weight=w,
            reps=low,
            failures=0,
        )

    failed = not complete or any(r < low for r in reps_done)
    if not failed:
        nreps = min(top, min(reps_done) + 1)
        return out(
            "increase_reps",
            f"All {len(work)} sets reached at least {low} reps at {wtxt}, not all {top} → "
            f"keep {wtxt} × {nreps}.",
            weight=target_w,
            reps=nreps,
            failures=0,
        )

    count = p.consecutive_failures + 1
    if count >= DELOAD_FAILING_SESSIONS:
        w = max(floor_kg, round_step(target_w * DELOAD_FACTOR, step, "down", floor_kg))
        if w > target_w + _EPS:  # target below the minimum: a deload must never add weight
            return out(
                "hold",
                f"{count} consecutive sessions below {low} reps, but {wtxt} is already below the "
                f"minimum weight → hold at the minimum "
                f"{format_weight(w, p.imperial, p.equipment)}.",
                weight=w,
                reps=low,
                failures=count,
            )
        return out(
            "deload",
            f"{count} consecutive sessions below {low} reps at {wtxt} → deload to "
            f"{format_weight(w, p.imperial, p.equipment)} (90 % rounded down to the plate step).",
            weight=w,
            reps=low,
            failures=0,
        )
    return out(
        "hold",
        f"Not every set reached {low} reps at {wtxt} → keep {wtxt} × {low} "
        f"({count} of {DELOAD_FAILING_SESSIONS} sessions below {low} reps before a deload).",
        weight=target_w,
        reps=low,
        failures=count,
    )
