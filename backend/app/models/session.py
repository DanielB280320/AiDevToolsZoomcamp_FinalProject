"""Training sessions (spec §8, F9): a dated instance of a planned training day.

Rows are created lazily the first time a planned day is viewed or logged (F9 "materialised").
`status` stores only `planned` / `in_progress` / `done`; `missed` is derived on read from the
date in the athlete's time zone, so nothing needs a nightly job. The unique constraint on
(athlete, date) is the database-level "one session per day".
"""

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    false,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SESSION_STATUSES = ("planned", "in_progress", "done")


class TrainingSession(Base):
    __tablename__ = "session"
    __table_args__ = (
        CheckConstraint(f"status IN {SESSION_STATUSES!r}", name="status"),
        CheckConstraint("completion IS NULL OR completion BETWEEN 0 AND 1", name="completion"),
        UniqueConstraint("athlete_id", "date", name="uq_session_athlete_id_date"),
        Index("ix_session_athlete_id_original_date", "athlete_id", "original_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    athlete_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("plan.id"), index=True)
    training_day_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("training_day.id"))
    # Calendar day in the athlete's time zone (not an instant).
    date: Mapped[dt.date] = mapped_column(Date)
    # Planned date before a move; null when the session is on its template day.
    original_date: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="planned", server_default="planned")
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    completion: Mapped[float | None] = mapped_column(Numeric(5, 4, asdecimal=False))
    kcal: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class SetLog(Base):
    """One logged (or skipped) set. Targets are *snapshots* taken when the set was first logged
    (CLAUDE.md rule 7), so later plan edits never rewrite history. `planned_exercise_id` is a
    plain id, not a foreign key, for the same reason. Unique per (session, exercise, set number),
    which makes retries idempotent (F10.1)."""

    __tablename__ = "set_log"
    __table_args__ = (
        UniqueConstraint(
            "session_id", "exercise_id", "set_no", name="uq_set_log_session_exercise_set"
        ),
        CheckConstraint("set_no BETWEEN 1 AND 30", name="set_no"),
        CheckConstraint(
            "skipped OR reps IS NOT NULL OR seconds IS NOT NULL", name="performed_has_values"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("session.id", ondelete="CASCADE"), index=True
    )
    planned_exercise_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("exercise.id", ondelete="RESTRICT")
    )
    set_no: Mapped[int] = mapped_column(Integer)
    skipped: Mapped[bool] = mapped_column(Boolean, server_default=false())
    target_reps: Mapped[int | None] = mapped_column(Integer)
    target_weight_kg: Mapped[float | None] = mapped_column(Numeric(5, 2, asdecimal=False))
    target_seconds: Mapped[int | None] = mapped_column(Integer)
    reps: Mapped[int | None] = mapped_column(Integer)
    weight_kg: Mapped[float | None] = mapped_column(Numeric(6, 2, asdecimal=False))
    seconds: Mapped[int | None] = mapped_column(Integer)
    distance_m: Mapped[float | None] = mapped_column(Numeric(9, 1, asdecimal=False))
    logged_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class ExtraActivity(Base):
    """An off-plan timed/cardio activity (F10, F13.3). `kcal` is fixed at logging time with the
    most recent weight on or before `date`, so a later weigh-in never changes past days."""

    __tablename__ = "extra_activity"
    __table_args__ = (
        CheckConstraint("minutes BETWEEN 1 AND 600", name="minutes"),
        Index("ix_extra_activity_athlete_id_date", "athlete_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    athlete_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    date: Mapped[dt.date] = mapped_column(Date)
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("exercise.id", ondelete="RESTRICT")
    )
    minutes: Mapped[int] = mapped_column(Integer)
    kcal: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
