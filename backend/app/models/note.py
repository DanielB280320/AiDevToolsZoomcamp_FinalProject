"""`CoachNote` (spec F16): a one-way note by a linked coach on a day, a session or an exercise.

Both `athlete_id` and `author_id` cascade on user deletion, so deleting the author's account
removes their notes (F18) and the athlete's removes all notes about them. A note outlives the link
that allowed it: it stays visible to the athlete when the link ends (D84). The text is free text
about health and never reaches logs, metrics or traces (rule 6).
"""

import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

NOTE_SCOPES = ("day", "session", "exercise")
NOTE_TEXT_MAX = 2000


class CoachNote(Base):
    __tablename__ = "coach_note"
    __table_args__ = (
        CheckConstraint(f"scope IN {NOTE_SCOPES!r}", name="scope"),
        CheckConstraint(f"char_length(text) BETWEEN 1 AND {NOTE_TEXT_MAX}", name="text_length"),
        CheckConstraint(
            "(scope = 'day' AND date IS NOT NULL AND session_id IS NULL AND exercise_id IS NULL)"
            " OR (scope = 'session' AND session_id IS NOT NULL AND exercise_id IS NULL)"
            " OR (scope = 'exercise' AND exercise_id IS NOT NULL)",
            name="scope_target",
        ),
        Index("ix_coach_note_athlete_id_created_at", "athlete_id", "created_at"),
        Index("ix_coach_note_session_id", "session_id"),
        Index("ix_coach_note_exercise_id", "exercise_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    athlete_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    author_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(16))
    date: Mapped[dt.date | None] = mapped_column(Date)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("session.id", ondelete="CASCADE")
    )
    exercise_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("exercise.id", ondelete="CASCADE")
    )
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
