"""CSV import of past workouts (spec F10.5, D89).

The file is validated as a whole by the pure engine (`engines/workout_import.py`); only a fully
valid file reaches the database, in one transaction. Each imported date gets one finished,
plan-less session flagged `imported`; its sets have no targets. Re-uploading a file is
idempotent by (date, exercise, set number): existing sets are skipped and counted.

Nothing here logs row content: the one log line carries the number of imported sets (spec 6.5).
"""

import datetime as dt
import uuid
from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.engines.constants import IMPORT_MAX_BYTES, IMPORT_MAX_ERRORS, IMPORT_MAX_ROWS
from app.engines.workout_import import ImportRow, RowError, name_key, parse_workouts
from app.errors import ProblemError
from app.models import Exercise, SetLog, TrainingSession, User
from app.schemas.logging import WorkoutImportResult
from app.schemas.problem import FieldError
from app.services import training_log
from app.services.calendar import utc_midnight_after
from app.services.clock import local_today
from app.telemetry import get_logger

log = get_logger(__name__)


def _invalid(errors: list[RowError], detail: str) -> ProblemError:
    # `rows.<n>`: row n of the file (row 1 is the header). The message is a fixed phrase.
    return ProblemError(
        422,
        "invalid_import",
        detail,
        errors=[
            FieldError(field=f"rows.{e.row}", code="invalid_row", message=e.reason) for e in errors
        ],
    )


def _catalog(db: Session, user: User) -> dict[str, tuple[uuid.UUID, str]]:
    """Exercises visible to the athlete by name key; a seed exercise wins over a custom one."""
    rows = db.execute(
        select(Exercise.id, Exercise.name, Exercise.type)
        .where(or_(Exercise.owner_id.is_(None), Exercise.owner_id == user.id))
        .order_by(Exercise.owner_id.is_not(None), Exercise.created_at, Exercise.id)
    )
    catalog: dict[str, tuple[uuid.UUID, str]] = {}
    for exercise_id, name, kind in rows:
        catalog.setdefault(name_key(name), (exercise_id, kind))
    return catalog


def _midday(day: dt.date, timezone: str, now: dt.datetime) -> dt.datetime:
    """Local midday of `day` as a UTC instant, never later than `now`."""
    start = utc_midnight_after(day - dt.timedelta(days=1), timezone)
    return min(start + dt.timedelta(hours=12), now)


def import_workouts(db: Session, user: User, raw: bytes, now: dt.datetime) -> WorkoutImportResult:
    if len(raw) > IMPORT_MAX_BYTES:
        raise ProblemError(413, "file_too_large", "The file may be at most 2 MB.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _invalid([RowError(1, "the file must be UTF-8")], "The file is not valid.") from None
    catalog = _catalog(db, user)
    types = {key: kind for key, (_, kind) in catalog.items()}
    parsed = parse_workouts(text, types, local_today(now, user.timezone))
    if parsed.too_many_rows:
        raise ProblemError(
            422, "too_many_rows", f"The file may have at most {IMPORT_MAX_ROWS} rows."
        )
    if not parsed.ok:
        raise _invalid(parsed.errors, "Nothing was imported: fix the listed rows and try again.")

    by_date: dict[dt.date, list[ImportRow]] = defaultdict(list)
    for row in parsed.rows:
        by_date[row.date].append(row)

    # A day that already holds a real (planned or logged) session is not touched.
    existing = {
        s.date: s
        for s in db.scalars(
            select(TrainingSession).where(
                TrainingSession.athlete_id == user.id, TrainingSession.date.in_(list(by_date))
            )
        )
    }
    blocked = sorted(
        (
            RowError(rows[0].row, "that day already has a workout that was not imported")
            for day, rows in by_date.items()
            if day in existing and not existing[day].imported
        ),
        key=lambda e: e.row,
    )
    if blocked:
        raise _invalid(blocked[:IMPORT_MAX_ERRORS], "Nothing was imported.")

    imported = skipped = 0
    try:
        for day, rows in sorted(by_date.items()):
            session = existing.get(day)
            if session is None:
                when = _midday(day, user.timezone, now)
                session = TrainingSession(
                    id=uuid.uuid4(),
                    athlete_id=user.id,
                    plan_id=None,
                    training_day_id=None,
                    date=day,
                    status="done",
                    imported=True,
                    started_at=when,
                    finished_at=when,
                    created_at=now,
                )
                db.add(session)
                db.flush()
            have = {
                (exercise_id, set_no)
                for exercise_id, set_no in db.execute(
                    select(SetLog.exercise_id, SetLog.set_no).where(SetLog.session_id == session.id)
                )
            }
            for row in rows:
                exercise_id = catalog[row.exercise_key][0]
                if (exercise_id, row.set_no) in have:
                    skipped += 1
                    continue
                db.add(
                    SetLog(
                        session_id=session.id,
                        exercise_id=exercise_id,
                        set_no=row.set_no,
                        skipped=False,
                        reps=row.reps,
                        weight_kg=row.weight_kg,
                        seconds=row.seconds,
                        distance_m=row.distance_m,
                        logged_at=now,
                    )
                )
                imported += 1
            db.flush()
            training_log.recompute(db, session)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ProblemError(
            409, "import_conflict", "A workout changed while importing. Try again."
        ) from None
    log.info("workouts imported", outcome="ok", count=imported)
    return WorkoutImportResult(imported=imported, skipped=skipped)
