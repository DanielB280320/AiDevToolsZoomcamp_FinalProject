"""F11 progression engine v1: table-driven rule tests and property tests."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engines.progression import (
    LoggedSet,
    ProgressionInput,
    min_weight_kg,
    plate_step_kg,
    suggest,
)


def sets(reps: list[int], weight: float | None = 40.0) -> list[LoggedSet]:
    return [LoggedSet(reps=r, weight_kg=weight) for r in reps]


def dbl(logged: list[LoggedSet], **kw: object) -> ProgressionInput:
    base: dict[str, object] = {
        "exercise_type": "strength",
        "rule": "double",
        "equipment": "machine",
        "sets_planned": 3,
        "target_weight_kg": 40.0,
        "reps_min": 8,
        "reps_max": 12,
        "increment_kg": 2.5,
    }
    base.update(kw)
    return ProgressionInput(logged_sets=logged, **base)  # type: ignore[arg-type]


def lin(logged: list[LoggedSet], **kw: object) -> ProgressionInput:
    base: dict[str, object] = {
        "exercise_type": "strength",
        "rule": "linear",
        "equipment": "barbell",
        "sets_planned": 3,
        "target_weight_kg": 60.0,
        "target_reps": 5,
        "increment_kg": 2.5,
    }
    base.update(kw)
    return ProgressionInput(logged_sets=logged, **base)  # type: ignore[arg-type]


# (id, input, action, weight, reps, failures_after)
CASES = [
    ("double_top", dbl(sets([12, 12, 12])), "increase_weight", 42.5, 8, 0),
    ("double_partial_reps", dbl(sets([10, 9, 9])), "increase_reps", 40.0, 11, 0),
    ("double_best_capped", dbl(sets([12, 12, 11])), "increase_reps", 40.0, 12, 0),
    ("double_fewer_sets", dbl(sets([12, 12])), "increase_reps", 40.0, 12, 1),
    ("double_extra_sets_ok", dbl(sets([12, 12, 12, 12])), "increase_weight", 42.5, 8, 0),
    ("double_extra_set_short", dbl(sets([12, 12, 12, 10])), "increase_reps", 40.0, 12, 0),
    (
        "double_mixed_weights_use_target",
        dbl(sets([12, 12], 40.0) + sets([12], 30.0)),
        "increase_reps",
        40.0,
        12,
        1,
    ),
    ("double_below_min_fails", dbl(sets([7, 8, 8])), "increase_reps", 40.0, 9, 1),
    ("linear_success", lin(sets([5, 5, 5], 60.0)), "increase_weight", 62.5, 5, 0),
    ("linear_fail_keeps", lin(sets([5, 5, 4], 60.0)), "hold", 60.0, 5, 1),
    (
        "linear_prior_failures_count",
        lin(sets([5, 4, 4], 60.0), consecutive_failures=1),
        "hold",
        60.0,
        5,
        2,
    ),
    (
        "linear_success_resets_counter",
        lin(sets([5, 5, 5], 60.0), consecutive_failures=2),
        "increase_weight",
        62.5,
        5,
        0,
    ),
    ("linear_no_increment", lin(sets([5, 5, 5], 60.0), increment_kg=0.0), "hold", 60.0, 5, 0),
    (
        "linear_unrounded_increment_capped",
        lin(sets([5, 5, 5], 60.0), increment_kg=1.0),
        "hold",
        60.0,
        5,
        0,
    ),
    (
        "deload_third_failure",
        lin(
            sets([4, 4, 4], 100.0),
            target_weight_kg=100.0,
            deload_enabled=True,
            consecutive_failures=2,
        ),
        "deload",
        90.0,
        5,
        0,
    ),
    (
        "deload_rounds_down",
        lin(
            sets([3, 3, 3], 62.5),
            target_weight_kg=62.5,
            deload_enabled=True,
            consecutive_failures=2,
        ),
        "deload",
        55.0,
        5,
        0,
    ),
    (
        "deload_disabled",
        lin(sets([4, 4, 4], 100.0), target_weight_kg=100.0, consecutive_failures=2),
        "hold",
        100.0,
        5,
        3,
    ),
    (
        "deload_floor_empty_bar",
        lin(
            sets([1, 1, 1], 20.0),
            target_weight_kg=20.0,
            deload_enabled=True,
            consecutive_failures=2,
        ),
        "deload",
        20.0,
        5,
        0,
    ),
    ("manual_none", dbl(sets([12, 12, 12]), rule="manual"), "none", None, None, 0),
    ("skipped_none", dbl([], consecutive_failures=2), "none", None, None, 2),
    (
        "calibration_most_sets",
        lin(sets([5], 20.0) + sets([5, 5], 22.5), is_first_session=True, target_weight_kg=None),
        "calibrate",
        22.5,
        5,
        0,
    ),
    (
        "calibration_tie_heaviest",
        lin(sets([5, 5], 20.0) + sets([5, 5], 25.0), is_first_session=True, target_weight_kg=None),
        "calibrate",
        25.0,
        5,
        0,
    ),
    (
        "calibration_barbell_min",
        lin(sets([5, 5, 5], 10.0), is_first_session=True, target_weight_kg=None),
        "calibrate",
        20.0,
        5,
        0,
    ),
    (
        "calibration_dumbbell_rounds",
        dbl(
            sets([10, 10, 10], 13.0),
            equipment="dumbbell",
            is_first_session=True,
            target_weight_kg=None,
        ),
        "calibrate",
        14.0,
        8,
        0,
    ),
    (
        "bodyweight_reps",
        dbl(
            sets([10, 9, 9], None),
            exercise_type="bodyweight",
            equipment="bodyweight",
            target_weight_kg=None,
            reps_min=6,
            reps_max=15,
        ),
        "increase_reps",
        None,
        11,
        0,
    ),
    (
        "bodyweight_top_added",
        dbl(
            sets([15, 15, 15], None),
            exercise_type="bodyweight",
            equipment="bodyweight",
            target_weight_kg=None,
            reps_min=6,
            reps_max=15,
            allows_added_weight=True,
            increment_kg=2.5,
        ),
        "add_weight",
        2.5,
        6,
        0,
    ),
    (
        "bodyweight_top_harder",
        dbl(
            sets([15, 15, 15], None),
            exercise_type="bodyweight",
            equipment="bodyweight",
            target_weight_kg=None,
            reps_min=6,
            reps_max=15,
        ),
        "harder_variation",
        None,
        6,
        0,
    ),
]


@pytest.mark.parametrize(
    ("name", "inp", "action", "weight", "reps", "failures"), CASES, ids=[c[0] for c in CASES]
)
def test_rules(
    name: str,
    inp: ProgressionInput,
    action: str,
    weight: float | None,
    reps: int | None,
    failures: int,
) -> None:
    s = suggest(inp)
    assert s.action == action
    assert s.weight_kg == weight
    assert s.reps == reps
    assert s.consecutive_failures == failures
    assert s.reason
    assert s.inputs["rule"] == inp.rule


def timed(secs: list[int], target: int = 30, **kw: object) -> ProgressionInput:
    base: dict[str, object] = {
        "exercise_type": "timed",
        "rule": "double",
        "equipment": "none",
        "sets_planned": 3,
        "target_seconds": target,
    }
    base.update(kw)
    return ProgressionInput(logged_sets=[LoggedSet(seconds=x) for x in secs], **base)  # type: ignore[arg-type]


def test_timed_hold_rounds_to_5s() -> None:
    s = suggest(timed([40, 40, 40], 40))
    assert (s.action, s.seconds) == ("increase_duration", 45)


def test_cardio_rounds_to_minute() -> None:
    s = suggest(timed([1200], 1200, equipment="cardio_machine", sets_planned=1))
    assert s.seconds == 1320


def test_timed_incomplete_holds() -> None:
    s = suggest(timed([30, 30], 30))
    assert (s.action, s.seconds) == ("hold", 30)


def test_reason_example_and_inputs_stored() -> None:
    s = suggest(dbl(sets([12, 12, 12])))
    assert s.reason == "All 3 sets reached 12 reps at 40 kg → 42.5 kg × 8."
    assert s.inputs["logged_sets"][0] == {
        "reps": 12,
        "weight_kg": 40.0,
        "seconds": None,
        "completed": True,
    }


def test_imperial_reason_in_pounds() -> None:
    s = suggest(dbl(sets([12, 12, 12]), imperial=True))
    assert "lb" in s.reason


def test_defaults() -> None:
    assert plate_step_kg("dumbbell") == 2.0
    assert plate_step_kg("barbell") == 2.5
    assert min_weight_kg("barbell") == 20.0
    assert min_weight_kg("machine") == 0.0


# ---- property tests ----

rep_lists = st.lists(st.integers(0, 20), min_size=0, max_size=6)


@st.composite
def inputs(draw: st.DrawFn) -> ProgressionInput:
    equipment = draw(st.sampled_from(["barbell", "dumbbell", "machine", "cable"]))
    step = plate_step_kg(equipment, draw(st.booleans()))
    target = max(min_weight_kg(equipment), draw(st.integers(0, 80)) * step)
    rule = draw(st.sampled_from(["linear", "double"]))
    reps_min = draw(st.integers(1, 10))
    reps_max = draw(st.integers(reps_min, 20))
    reps = draw(rep_lists)
    wts = draw(
        st.lists(st.sampled_from([target, target + step]), min_size=len(reps), max_size=len(reps))
    )
    return ProgressionInput(
        exercise_type="strength",
        rule=rule,  # type: ignore[arg-type]
        equipment=equipment,
        sets_planned=draw(st.integers(1, 5)),
        logged_sets=[LoggedSet(reps=r, weight_kg=w) for r, w in zip(reps, wts, strict=True)],
        target_weight_kg=target,
        target_reps=reps_max,
        reps_min=reps_min,
        reps_max=reps_max,
        increment_kg=draw(st.sampled_from([0.0, 1.0, 2.0, 2.5, 5.0])),
        deload_enabled=draw(st.booleans()),
        consecutive_failures=draw(st.integers(0, 4)),
        plate_step_kg=step,
    )


@given(inputs())
def test_never_more_than_one_increment_and_never_below_min(inp: ProgressionInput) -> None:
    s = suggest(inp)
    if s.weight_kg is None:
        return
    assert s.weight_kg <= (inp.target_weight_kg or 0) + inp.increment_kg + 1e-6
    if s.action in {"increase_weight", "deload"}:
        assert s.weight_kg >= min_weight_kg(inp.equipment) - 1e-9


@given(inputs())
def test_deload_on_plate_grid_and_below_target(inp: ProgressionInput) -> None:
    s = suggest(inp)
    if s.action == "deload":
        step = inp.plate_step_kg or 2.5
        assert s.weight_kg is not None
        assert s.weight_kg >= min_weight_kg(inp.equipment)
        assert s.weight_kg <= max(inp.target_weight_kg or 0, min_weight_kg(inp.equipment))
        assert abs(
            s.weight_kg / step - round(s.weight_kg / step)
        ) < 1e-6 or s.weight_kg == min_weight_kg(inp.equipment)
        assert s.consecutive_failures == 0


@given(inputs())
def test_deterministic(inp: ProgressionInput) -> None:
    assert suggest(inp) == suggest(inp)


@given(
    st.lists(
        st.tuples(st.sampled_from([10.0, 12.5, 15.0, 20.0, 22.5]), st.integers(1, 10)),
        min_size=1,
        max_size=6,
    ),
    st.sampled_from(["barbell", "dumbbell", "machine"]),
)
def test_calibration_never_below_min_and_uses_modal_weight(
    ws: list[tuple[float, int]], eq: str
) -> None:
    logged = [LoggedSet(reps=r, weight_kg=w) for w, r in ws]
    s = suggest(
        ProgressionInput(
            exercise_type="strength",
            rule="linear",
            equipment=eq,
            sets_planned=3,
            logged_sets=logged,
            target_reps=5,
            is_first_session=True,
        )
    )
    assert s.action == "calibrate" and s.weight_kg is not None
    assert s.weight_kg >= min_weight_kg(eq)
    counts: dict[float, int] = {}
    for w, _ in ws:
        counts[w] = counts.get(w, 0) + 1
    best = max(counts, key=lambda w: (counts[w], w))
    assert s.weight_kg >= min(min_weight_kg(eq), best) and s.weight_kg <= max(
        best, min_weight_kg(eq)
    ) + plate_step_kg(eq)


@given(st.booleans(), st.sampled_from([0.0, 2.5]))
def test_bodyweight_top_follows_allows_added_weight(allows: bool, inc: float) -> None:
    s = suggest(
        ProgressionInput(
            exercise_type="bodyweight",
            rule="double",
            equipment="bodyweight",
            sets_planned=2,
            logged_sets=sets([15, 15], None),
            reps_min=6,
            reps_max=15,
            increment_kg=inc,
            allows_added_weight=allows,
        )
    )
    assert s.action == ("add_weight" if allows else "harder_variation")
