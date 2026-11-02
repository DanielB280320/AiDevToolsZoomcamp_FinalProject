"""F10.5 CSV import of past workouts (D89): parse and validate the file, all or nothing.

Pure (ADR 0004): the text, the athlete's exercise catalog and "today" go in; rows or row errors
come out, with an `explanation`. Nothing is read from a database or a clock here.

Privacy (spec section 6.5): a row error holds the row number and a fixed reason. It never holds
the cell values or the exercise name, so a rejected file cannot leak its content through the
error list. Row 1 is the header, the first data row is row 2 (as in a spreadsheet).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.engines.constants import (
    IMPORT_COLUMNS,
    IMPORT_MAX_ERRORS,
    IMPORT_MAX_ROWS,
    IMPORT_MIN_DATE_YEAR,
)

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_INT = re.compile(r"\d{1,9}")
_DECIMAL = re.compile(r"\d{1,9}(\.\d{1,9})?")

# Ranges mirror `SetLogInput` (reps 0-1000, weight 0-1000 kg, seconds 0-86400, distance <= 1e6).
_MAX_REPS = 1000
_MAX_WEIGHT_KG = 1000
_MAX_SECONDS = 86400
_MAX_DISTANCE_M = 1_000_000
_MAX_SET_NO = 30


def name_key(name: str) -> str:
    """The case-insensitive exact-name key used for the catalog lookup."""
    return name.strip().casefold()


@dataclass(frozen=True, slots=True)
class RowError:
    row: int
    reason: str


@dataclass(frozen=True, slots=True)
class ImportRow:
    row: int
    date: dt.date
    exercise_key: str
    set_no: int
    reps: int | None
    weight_kg: float | None
    seconds: int | None
    distance_m: float | None


@dataclass(frozen=True, slots=True)
class ParseResult:
    rows: list[ImportRow]
    errors: list[RowError]  # capped at IMPORT_MAX_ERRORS
    error_count: int
    too_many_rows: bool
    explanation: str

    @property
    def ok(self) -> bool:
        return self.error_count == 0 and not self.too_many_rows


def _fail(reason: str) -> ParseResult:
    return ParseResult([], [RowError(1, reason)], 1, False, reason)


def _int(cell: str, maximum: int) -> int | None:
    """A whole number within `0..maximum`, `None` for an empty cell; `ValueError` otherwise."""
    if cell == "":
        return None
    if not _INT.fullmatch(cell) or int(cell) > maximum:
        raise ValueError
    return int(cell)


def _decimal(cell: str, maximum: float) -> float | None:
    if cell == "":
        return None
    if not _DECIMAL.fullmatch(cell) or float(cell) > maximum:
        raise ValueError
    return round(float(cell), 2)


def _row(
    row_no: int, cells: list[str], catalog: Mapping[str, str], today: dt.date
) -> ImportRow | str:
    """The validated row, or the (fixed) reason it is rejected."""
    day_text, name, set_text, reps_text, weight_text, seconds_text, distance_text = (
        c.strip() for c in cells
    )
    if not _DATE.fullmatch(day_text):
        return "date must be YYYY-MM-DD"
    try:
        day = dt.date.fromisoformat(day_text)
    except ValueError:
        return "date must be YYYY-MM-DD"
    if day.year < IMPORT_MIN_DATE_YEAR:
        return "date is too far in the past"
    if day > today:
        return "date is in the future"
    kind = catalog.get(name_key(name))
    if kind is None:
        return "unknown exercise"
    try:
        set_no = _int(set_text, _MAX_SET_NO)
        reps = _int(reps_text, _MAX_REPS)
        weight = _decimal(weight_text, _MAX_WEIGHT_KG)
        seconds = _int(seconds_text, _MAX_SECONDS)
        distance = _decimal(distance_text, _MAX_DISTANCE_M)
    except ValueError:
        return "a number is invalid or out of range"
    if set_no is None or set_no < 1:
        return "set must be a whole number from 1 to 30"
    if kind == "timed":
        if seconds is None:
            return "duration_seconds is required for a timed exercise"
        if reps is not None or weight is not None:
            return "a timed exercise takes duration_seconds and distance_m only"
    else:
        if reps is None:
            return "reps is required"
        if kind == "strength" and weight is None:
            return "weight_kg is required for a strength exercise"
        if seconds is not None or distance is not None:
            return "only a timed exercise takes duration_seconds and distance_m"
    return ImportRow(row_no, day, name_key(name), set_no, reps, weight, seconds, distance)


@dataclass
class _Collector:
    rows: list[ImportRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)
    count: int = 0

    def fail(self, row: int, reason: str) -> None:
        self.count += 1
        if len(self.errors) < IMPORT_MAX_ERRORS:
            self.errors.append(RowError(row, reason))


def parse_workouts(text: str, catalog: Mapping[str, str], today: dt.date) -> ParseResult:
    """Validate a workout CSV. `catalog` maps `name_key(name)` to the exercise type
    (`strength`, `bodyweight`, `timed`); `today` is the athlete's local date."""
    reader = csv.reader(io.StringIO(text, newline=""))
    collector = _Collector()
    seen: set[tuple[dt.date, str, int]] = set()
    data_rows = 0
    try:
        header = next(reader, None)
        if header is None:
            return _fail("the file is empty")
        if tuple(c.strip().casefold() for c in header) != IMPORT_COLUMNS:
            return _fail("the header must be " + ",".join(IMPORT_COLUMNS))
        for row_no, cells in enumerate(reader, start=2):
            if not any(c.strip() for c in cells):
                continue  # blank line
            data_rows += 1
            if data_rows > IMPORT_MAX_ROWS:
                return ParseResult(
                    [], [], 0, True, f"more than {IMPORT_MAX_ROWS} rows; split the file"
                )
            if len(cells) != len(IMPORT_COLUMNS):
                collector.fail(row_no, "wrong number of columns")
                continue
            parsed = _row(row_no, cells, catalog, today)
            if isinstance(parsed, str):
                collector.fail(row_no, parsed)
                continue
            key = (parsed.date, parsed.exercise_key, parsed.set_no)
            if key in seen:
                collector.fail(row_no, "the same set appears twice in the file")
                continue
            seen.add(key)
            collector.rows.append(parsed)
    except csv.Error:
        return _fail("the file is not valid CSV")
    if data_rows == 0:
        return _fail("the file has no data rows")
    if collector.count:
        explanation = f"{collector.count} of {data_rows} rows are invalid; nothing is imported"
        return ParseResult([], collector.errors, collector.count, False, explanation)
    return ParseResult(collector.rows, [], 0, False, f"{data_rows} rows are valid")
