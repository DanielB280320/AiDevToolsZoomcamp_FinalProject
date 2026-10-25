"""`Suggestion` (spec §8, F11): a proposed change awaiting accept/reject.

`payload` holds the kind-specific body of the API (`ProgressionPayload` for `progression`) and
`inputs` the engine inputs as they were, so a suggestion stays explainable after the plan changes
(F11.4). `session_id` is the finished session a progression suggestion came from;
`planned_exercise_id` and `exercise_id` say which exercise it targets. `planned_exercise_id` is a
plain id, not a foreign key, like on `set_log`: history must survive plan edits (rule 7).
"""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SUGGESTION_KINDS = ("progression", "calories", "recalc")
SUGGESTION_STATUSES = ("pending", "accepted", "rejected")
_JSON = JSON().with_variant(JSONB(), "postgresql")


class Suggestion(Base):
    __tablename__ = "suggestion"
    __table_args__ = (
        CheckConstraint(f"kind IN {SUGGESTION_KINDS!r}", name="kind"),
        CheckConstraint(f"status IN {SUGGESTION_STATUSES!r}", name="status"),
        Index("ix_suggestion_athlete_id_status_created_at", "athlete_id", "status", "created_at"),
        Index("ix_suggestion_session_id_status", "session_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    athlete_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    rule: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str] = mapped_column(Text)
    inputs: Mapped[dict[str, Any]] = mapped_column(_JSON)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSON)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("session.id", ondelete="CASCADE")
    )
    planned_exercise_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    exercise_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("exercise.id", ondelete="RESTRICT")
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
