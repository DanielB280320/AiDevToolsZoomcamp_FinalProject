"""F16.5: the coach "needs attention" rules and ordering (pure engine, #48)."""

import datetime as dt
import itertools
import uuid
from dataclasses import dataclass

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engines.coach_attention import AttentionInput, evaluate, order_athletes

TODAY = dt.date(2026, 10, 31)
RECENT = TODAY - dt.timedelta(days=1)


def make(**kw: object) -> AttentionInput:
    base: dict[str, object] = {
        "today": TODAY,
        "linked_since": TODAY - dt.timedelta(days=30),
        "training_adherence_7d": 1.0,
        "last_log_date": RECENT,
        "deload_pending": False,
        "deload_applied_on": None,
    }
    base.update(kw)
    return AttentionInput(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("adherence", "expected"),
    [
        (0.0, True),
        (0.69, True),
        (0.6999, True),
        (0.70, False),
        (0.71, False),
        (1.0, False),
        (None, False),
    ],
)
def test_low_adherence_boundary(adherence: float | None, expected: bool) -> None:
    result = evaluate(make(training_adherence_7d=adherence))
    assert ("low_adherence" in result.reasons) is expected
    assert result.needs_attention is expected


@pytest.mark.parametrize(
    ("applied_days_ago", "expected"), [(0, True), (13, True), (14, True), (15, False), (60, False)]
)
def test_deload_applied_window(applied_days_ago: int, expected: bool) -> None:
    result = evaluate(make(deload_applied_on=TODAY - dt.timedelta(days=applied_days_ago)))
    assert ("deload" in result.reasons) is expected


def test_deload_pending_triggers_without_age() -> None:
    assert evaluate(make(deload_pending=True)).reasons == ("deload",)


@pytest.mark.parametrize(
    ("days", "expected"), [(0, False), (1, False), (2, False), (3, True), (10, True)]
)
def test_inactive_boundary(days: int, expected: bool) -> None:
    result = evaluate(make(last_log_date=TODAY - dt.timedelta(days=days)))
    assert ("inactive" in result.reasons) is expected


@pytest.mark.parametrize(("days", "expected"), [(2, False), (3, True)])
def test_never_logged_counts_from_link_start(days: int, expected: bool) -> None:
    result = evaluate(make(last_log_date=None, linked_since=TODAY - dt.timedelta(days=days)))
    assert ("inactive" in result.reasons) is expected


def test_all_reasons_together_in_contract_order() -> None:
    result = evaluate(
        make(
            training_adherence_7d=0.2,
            deload_pending=True,
            last_log_date=TODAY - dt.timedelta(days=5),
        )
    )
    assert result.reasons == ("low_adherence", "deload", "inactive")
    assert result.explanation


def test_nothing_needs_attention() -> None:
    result = evaluate(make())
    assert result.reasons == () and not result.needs_attention
    assert result.explanation


@dataclass(frozen=True)
class A:
    attention: bool
    name: str
    id: uuid.UUID
    seq: int = 0


def sort(items: list[A]) -> list[A]:
    return order_athletes(
        items,
        needs_attention=lambda a: a.attention,
        display_name=lambda a: a.name,
        athlete_id=lambda a: a.id,
    )


def test_order_attention_first_then_name_case_insensitive_then_id() -> None:
    low, high = uuid.UUID(int=1), uuid.UUID(int=2)
    items = [
        A(False, "alice", high),
        A(True, "Zoe", low),
        A(False, "Bob", low),
        A(True, "adam", high),
        A(False, "ALICE", low),
    ]
    assert [(a.name, a.id.int) for a in sort(items)] == [
        ("adam", 2),
        ("Zoe", 1),
        ("ALICE", 1),
        ("alice", 2),
        ("Bob", 1),
    ]


athletes = st.lists(
    st.builds(
        A,
        st.booleans(),
        st.sampled_from(["ann", "Ann", "bob", "Bob", "cy", "Ünal"]),
        st.builds(uuid.UUID, int=st.integers(0, 3)),
        st.integers(0, 10_000),
    ),
    max_size=30,
)


@given(athletes)
def test_order_is_a_permutation_attention_first_and_stable(items: list[A]) -> None:
    items = [A(a.attention, a.name, a.id, i) for i, a in enumerate(items)]
    result = sort(items)
    assert sorted(result, key=lambda a: a.seq) == items
    flags = [a.attention for a in result]
    assert flags == sorted(flags, reverse=True)
    for first, second in itertools.pairwise(result):
        if (first.attention, first.name.casefold(), first.id) == (
            second.attention,
            second.name.casefold(),
            second.id,
        ):
            assert first.seq < second.seq
