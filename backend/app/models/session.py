"""Training sessions (spec §8, F9): a dated instance of a planned training day.

Rows are created lazily the first time a planned day is viewed or logged (F9 "materialised").
`status` stores only `planned` / `in_progress` / `done`; `missed` is derived on read from the
date in the athlete's time zone, so nothing needs a nightly job. The unique constraint on
(athlete, date) is the database-level "one session per day".
"""

import datetime as dt
import uuid

from sqlalchemy import (
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
