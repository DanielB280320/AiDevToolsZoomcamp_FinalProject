"""F10.5 / D89: the CSV import parser is pure, all-or-nothing and never echoes cell content."""

import datetime as dt

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.engines.constants import IMPORT_MAX_ERRORS, IMPORT_MAX_ROWS
from app.engines.workout_import import ParseResult, name_key, parse_workouts

TODAY = dt.date(2026, 10, 22)
CATALOG = {"bench press": "strength", "push-up": "bodyweight", "run": "timed"}
HEADER = "date,exercise,set,reps,weight_kg,duration_seconds,distance_m"


def parse(*lines: str, header: str = HEADER) -> ParseResult:
    return parse_workouts("\n".join([header, *lines]) + "\n", CATALOG, TODAY)


def test_valid_rows_of_every_exercise_type() -> None:
    result = parse_workouts(
        f"{HEADER}\n2026-08-03,Bench Press,1,8,60.5,,\n2026-08-03,BENCH PRESS,2,6,62.5,,\n"
        "2026-08-04,push-up,1,15,,,\n2026-08-04,Run,1,,,1800,5000.5\n",
        CATALOG,
        TODAY,
    )
    assert result.ok and result.error_count == 0
    first, _, pushup, run = result.rows
    assert (first.date, first.exercise_key, first.set_no) == (dt.date(2026, 8, 3), "bench press", 1)
    assert (first.reps, first.weight_kg, first.seconds, first.distance_m) == (8, 60.5, None, None)
    assert (pushup.reps, pushup.weight_kg) == (15, None)
    assert (run.reps, run.seconds, run.distance_m) == (None, 1800, 5000.5)
    assert "valid" in result.explanation


def test_bom_blank_lines_and_header_case_are_tolerated() -> None:
    text = (
        "﻿Date,Exercise,Set,Reps,Weight_kg,Duration_seconds,Distance_m\n\n2026-08-03,run,1,,,60,\n"
    )
    # the BOM is stripped by the service (utf-8-sig); the engine sees clean text
    result = parse_workouts(text.lstrip("﻿"), CATALOG, TODAY)
    assert result.ok and len(result.rows) == 1


@pytest.mark.parametrize(
    ("line", "reason"),
    [
        ("2026-8-03,Bench Press,1,8,60,,", "date must be YYYY-MM-DD"),
        ("03/08/2026,Bench Press,1,8,60,,", "date must be YYYY-MM-DD"),
        ("2026-02-30,Bench Press,1,8,60,,", "date must be YYYY-MM-DD"),
        ("2026-10-23,Bench Press,1,8,60,,", "date is in the future"),
        ("1969-12-31,Bench Press,1,8,60,,", "date is too far in the past"),
        ("2026-08-03,Nope,1,8,60,,", "unknown exercise"),
        ("2026-08-03,Bench Press,0,8,60,,", "set must be a whole number from 1 to 30"),
        ("2026-08-03,Bench Press,,8,60,,", "set must be a whole number from 1 to 30"),
        ("2026-08-03,Bench Press,31,8,60,,", "a number is invalid or out of range"),
        ("2026-08-03,Bench Press,1,8.5,60,,", "a number is invalid or out of range"),
        ("2026-08-03,Bench Press,1,8,-5,,", "a number is invalid or out of range"),
        ("2026-08-03,Bench Press,1,8,1001,,", "a number is invalid or out of range"),
        ("2026-08-03,Bench Press,1,8,60 kg,,", "a number is invalid or out of range"),
        ("2026-08-03,Bench Press,1,8,60,,", None),
        ("2026-08-03,Bench Press,1,,60,,", "reps is required"),
        ("2026-08-03,Bench Press,1,8,,,", "weight_kg is required for a strength exercise"),
        ("2026-08-03,Push-Up,1,,,,", "reps is required"),
        (
            "2026-08-03,Push-Up,1,8,,30,",
            "only a timed exercise takes duration_seconds and distance_m",
        ),
        ("2026-08-03,Run,1,,,,", "duration_seconds is required for a timed exercise"),
        ("2026-08-03,Run,1,5,,60,", "a timed exercise takes duration_seconds and distance_m only"),
        ("2026-08-03,Run,1", "wrong number of columns"),
    ],
)
def test_each_invalid_row_is_rejected_with_a_fixed_reason(line: str, reason: str | None) -> None:
    result = parse(line)
    if reason is None:
        assert result.ok
        return
    assert not result.ok
    assert result.rows == []  # all or nothing
    assert [(e.row, e.reason) for e in result.errors] == [(2, reason)]


def test_a_duplicate_set_in_the_file_is_rejected() -> None:
    result = parse("2026-08-03,Bench Press,1,8,60,,", "2026-08-03,bench press,1,6,50,,")
    assert [(e.row, e.reason) for e in result.errors] == [
        (3, "the same set appears twice in the file")
    ]


@pytest.mark.parametrize(
    "text",
    ["", "date,exercise\n2026-08-03,Run\n", f"{HEADER}\n", f"{HEADER}\n\n,,,,,,\n", '"x\n'],
)
def test_header_and_empty_file_problems_are_reported_on_row_1(text: str) -> None:
    result = parse_workouts(text, CATALOG, TODAY)
    assert not result.ok
    assert [e.row for e in result.errors] == [1]


def test_errors_are_capped_at_20_but_all_are_counted() -> None:
    result = parse(*["2026-08-03,Nope,1,8,60,,"] * 45)
    assert len(result.errors) == IMPORT_MAX_ERRORS == 20
    assert result.error_count == 45
    assert [e.row for e in result.errors] == list(range(2, 22))


def test_more_than_the_row_limit_is_rejected() -> None:
    lines = [f"2026-08-03,Bench Press,{n % 30 + 1},8,60,," for n in range(IMPORT_MAX_ROWS + 1)]
    result = parse(*lines)
    assert result.too_many_rows and not result.ok
    exactly = parse(*lines[:IMPORT_MAX_ROWS])
    assert not exactly.too_many_rows  # (duplicates are reported, the limit is not)


def test_name_key_is_case_insensitive_and_trims() -> None:
    assert name_key("  BeNcH Press ") == name_key("bench press")
    assert name_key("Straße") == name_key("STRASSE")


CELL = st.text(alphabet=st.characters(codec="utf-8"), max_size=30)


@given(st.lists(st.lists(CELL, min_size=0, max_size=9), max_size=20))
def test_arbitrary_cells_never_raise_and_never_leak_into_errors(rows: list[list[str]]) -> None:
    secret = "ZQXJ-secret-name"
    lines = [",".join(f'"{c.replace(chr(34), chr(34) * 2)}"' for c in r) for r in rows]
    lines.append(f"2026-08-03,{secret},1,8,60,,")
    result = parse_workouts("\n".join([HEADER, *lines]), CATALOG, TODAY)
    assert result.ok or result.rows == []
    for error in result.errors:
        assert secret not in error.reason
        assert all(cell not in error.reason for cell in ("ZQXJ",))
    assert secret not in result.explanation
    assert len(result.errors) <= IMPORT_MAX_ERRORS
