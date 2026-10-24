"""F11 Progression engine v1: next targets for one exercise after a finished session.

Pure (ADR 0004): plain inputs in, a `Suggestion` with `rule`, `inputs` and a `reason` out. No
database, HTTP or clock. The caller supplies the consecutive-failure counter for the deload
modifier and whether this is the first logged session (calibration). Persistence, accept/reject
and the feature flag live outside the engine (#85).

Definitions used by the rules (spec F11, D56):
- Working sets are the logged sets performed at the planned target weight (mixed weights within a
  session use the planned target weight; sets at other weights are ignored).
- A session is a *success* when the planned number of working sets reached the goal reps (linear:
  target reps; double / bodyweight: max reps; timed: target seconds). Sets beyond the plan are
  ignored.
- A session is a *failure* (for deload) when it was not skipped and the working sets did not reach
  the minimum goal (linear: target reps; double / bodyweight: min reps) on every planned set.
- A skipped exercise (no sets logged) yields no suggestion and leaves the failure counter alone.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.engines.constants import (
    CARDIO_ROUNDING_SECONDS,
    DELOAD_FACTOR,
    DELOAD_FAILING_SESSIONS,
    KG_PER_LB,
    MIN_WEIGHT_KG_BY_EQUIPMENT,
    PLATE_STEP_KG_BY_EQUIPMENT,
    PLATE_STEP_KG_DEFAULT,
    PLATE_STEP_LB,
    TIMED_PROGRESSION_FACTOR,
    TIMED_ROUNDING_SECONDS,
)

Rule = Literal["linear", "double", "manual"]
ExerciseType = Literal["strength", "bodyweight", "timed"]
Action = Literal[
    "none",
    "hold",
    "increase_weight",
    "increase_reps",
    "deload",
    "calibrate",
    "add_weight",
    "harder_variation",
    "increase_duration",
]

_EPS = 1e-9


@dataclass(frozen=True)
class LoggedSet:
    reps: int | None = None
    weight_kg: float | None = None
    seconds: int | None = None
    completed: bool = True


@dataclass(frozen=True)
class ProgressionInput:
    exercise_type: ExerciseType
    rule: Rule
    equipment: str
    sets_planned: int
    logged_sets: Sequence[LoggedSet]
    target_weight_kg: float | None = None
    target_reps: int | None = None  # linear: fixed reps
    reps_min: int | None = None  # double / bodyweight
    reps_max: int | None = None
    target_seconds: int | None = None  # timed
    increment_kg: float = 0.0
    deload_enabled: bool = False
    consecutive_failures: int = 0  # failing sessions at this weight before this one
    is_first_session: bool = False
    allows_added_weight: bool = False
    imperial: bool = False
    region: str | None = None  # "cardio" selects the 1-minute duration rounding
    plate_step_kg: float | None = None  # overrides the equipment default


@dataclass(frozen=True)
class Suggestion:
    rule: str
    action: Action
    weight_kg: float | None
    reps: int | None
    seconds: int | None
    reason: str
    consecutive_failures: int  # counter after this session (reset on success or deload)
    inputs: dict[str, Any] = field(default_factory=dict)


def plate_step_kg(equipment: str, imperial: bool = False) -> float:
    if imperial:
        return PLATE_STEP_LB * KG_PER_LB
    return PLATE_STEP_KG_BY_EQUIPMENT.get(equipment, PLATE_STEP_KG_DEFAULT)


def min_weight_kg(equipment: str) -> float:
    return MIN_WEIGHT_KG_BY_EQUIPMENT.get(equipment, 0.0)


def _round_step(
    value: float, step: float, mode: Literal["nearest", "down"], base: float = 0.0
) -> float:
    """Round onto the grid base + k * step (the plate grid starts at the minimum weight)."""
    n = (value - base) / step
    k = math.floor(n + _EPS) if mode == "down" else math.floor(n + 0.5 + _EPS)
    return base + k * step


def _fmt_w(kg: float, imperial: bool) -> str:
    if imperial:
        return f"{round(kg / KG_PER_LB, 1):g} lb"
    return f"{round(kg, 2):g} kg"


def _inputs(p: ProgressionInput) -> dict[str, Any]:
    return {
        "exercise_type": p.exercise_type,
        "rule": p.rule,
        "equipment": p.equipment,
        "sets_planned": p.sets_planned,
        "target_weight_kg": p.target_weight_kg,
        "target_reps": p.target_reps,
        "reps_min": p.reps_min,
        "reps_max": p.reps_max,
        "target_seconds": p.target_seconds,
        "increment_kg": p.increment_kg,
        "deload_enabled": p.deload_enabled,
        "consecutive_failures": p.consecutive_failures,
        "is_first_session": p.is_first_session,
        "allows_added_weight": p.allows_added_weight,
        "logged_sets": [
            {
                "reps": s.reps,
                "weight_kg": s.weight_kg,
                "seconds": s.seconds,
                "completed": s.completed,
            }
            for s in p.logged_sets
        ],
    }


def _increase(target_w: float, increment: float, step: float, floor_kg: float) -> float:
    """target + one increment on the plate grid, never more than one increment above target."""
    w = _round_step(target_w + increment, step, "nearest", floor_kg)
    if w > target_w + increment + _EPS:
        w = _round_step(target_w + increment, step, "down", floor_kg)
    return max(floor_kg, w)


def suggest(p: ProgressionInput) -> Suggestion:
    """Return the suggestion for one exercise after a finished session."""
    inputs = _inputs(p)

    def out(
        action: Action,
        reason: str,
        *,
        weight: float | None = None,
        reps: int | None = None,
        seconds: int | None = None,
        failures: int | None = None,
    ) -> Suggestion:
        kept = p.consecutive_failures if failures is None else failures
        return Suggestion(p.rule, action, weight, reps, seconds, reason, kept, inputs)

    if p.rule == "manual":
        return out("none", "Manual progression: no suggestions.")
    done = [s for s in p.logged_sets if s.completed]
    if not done:
        return out("none", "Exercise skipped: no suggestion.")

    if p.exercise_type == "timed":
        return _timed(p, done, out)

    step = p.plate_step_kg or plate_step_kg(p.equipment, p.imperial)
    floor_kg = min_weight_kg(p.equipment)

    if p.is_first_session and p.exercise_type == "strength":
        weights = Counter(s.weight_kg for s in done if s.weight_kg is not None)
        if weights:
            used = max(weights, key=lambda w: (weights[w], w))
            w = max(floor_kg, _round_step(used, step, "nearest", floor_kg))
            return out(
                "calibrate",
                f"First session: {weights[used]} of {len(done)} sets at "
                f"{_fmt_w(used, p.imperial)} → target weight {_fmt_w(w, p.imperial)}.",
                weight=w,
                reps=p.target_reps or p.reps_min,
                failures=0,
            )

    target_w = p.target_weight_kg or 0.0
    at_target = [s for s in done if abs((s.weight_kg or 0.0) - target_w) < 1e-6]
    work = at_target[: p.sets_planned]  # sets beyond the plan are ignored
    reps_done = [s.reps or 0 for s in work]
    is_bw = p.exercise_type == "bodyweight"
    linear = p.rule == "linear" and not is_bw
    top = p.target_reps if linear else p.reps_max
    low = p.target_reps if linear else p.reps_min
    if top is None or low is None:
        return out("none", "Missing rep targets: no suggestion.")
    wtxt = _fmt_w(target_w, p.imperial)

    if len(work) >= p.sets_planned and all(r >= top for r in reps_done):
        n = len(work)
        if is_bw:
            if p.allows_added_weight:
                w = _increase(target_w, p.increment_kg, step, floor_kg)
                return out(
                    "add_weight",
                    f"All {n} sets reached {top} reps → add weight: "
                    f"+{_fmt_w(w, p.imperial)} × {low}.",
                    weight=w,
                    reps=low,
                    failures=0,
                )
            return out(
                "harder_variation",
                f"All {n} sets reached {top} reps → ready for a harder variation.",
                reps=low,
                failures=0,
            )
        w = _increase(target_w, p.increment_kg, step, floor_kg)
        if w <= target_w + _EPS:
            return out(
                "hold",
                f"All {n} sets reached {top} reps at {wtxt}; the increment is smaller than the "
                "plate step → keep.",
                weight=target_w,
                reps=top if linear else low,
                failures=0,
            )
        nreps = top if linear else low
        return out(
            "increase_weight",
            f"All {n} sets reached {top} reps at {wtxt} → {_fmt_w(w, p.imperial)} × {nreps}.",
            weight=w,
            reps=nreps,
            failures=0,
        )

    failed = len(work) < p.sets_planned or any(r < low for r in reps_done)
    count = p.consecutive_failures + 1 if failed else 0
    if failed and p.deload_enabled and not is_bw and count >= DELOAD_FAILING_SESSIONS:
        w = max(floor_kg, _round_step(target_w * DELOAD_FACTOR, step, "down", floor_kg))
        return out(
            "deload",
            f"{count} consecutive sessions below {low} reps at {wtxt} → deload to "
            f"{_fmt_w(w, p.imperial)} (90 % rounded down to the plate step).",
            weight=w,
            reps=top if linear else low,
            failures=0,
        )
    if linear:
        return out(
            "hold",
            f"Not all sets reached {top} reps at {wtxt} → keep {wtxt} × {top}.",
            weight=target_w,
            reps=top,
            failures=count,
        )
    nreps = min(top, max(reps_done, default=0) + 1)
    best = max(reps_done, default=0)
    if is_bw:
        return out(
            "increase_reps",
            f"Best set {best} reps → target {nreps} reps.",
            reps=nreps,
            failures=count,
        )
    return out(
        "increase_reps",
        f"Not all sets reached {top} reps at {wtxt}; best set {best} → keep {wtxt} × {nreps}.",
        weight=target_w,
        reps=nreps,
        failures=count,
    )


def _timed(
    p: ProgressionInput, done: list[LoggedSet], out: Callable[..., Suggestion]
) -> Suggestion:
    target = p.target_seconds
    if target is None:
        return out("none", "Missing duration target: no suggestion.")
    cardio = p.equipment == "cardio_machine" or p.region == "cardio"
    step = CARDIO_ROUNDING_SECONDS if cardio else TIMED_ROUNDING_SECONDS
    if len(done) < p.sets_planned or any((s.seconds or 0) < target for s in done):
        return out(
            "hold", f"Not all sets completed at {target} s → keep {target} s.", seconds=target
        )
    new = int(_round_step(target * (1 + TIMED_PROGRESSION_FACTOR), step, "nearest"))
    return out(
        "increase_duration",
        f"All {len(done)} sets completed at {target} s → {new} s (+10 %).",
        seconds=new,
    )
