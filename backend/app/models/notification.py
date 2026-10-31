"""`Notification` (spec F17): one in-app message for one user.

`payload` holds ids and dates only (never names or free text, rule 6); the client renders the text
from `type`. A notification that refers to a suggestion is unique per (user, type, suggestion), so
a retried event cannot notify twice (D79.1). It is not a foreign key to `suggestion`: D79.2 keeps
calorie and progression notifications after their suggestion is replaced.
"""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

_JSON = JSON().with_variant(JSONB(), "postgresql")


class Notification(Base):
    __tablename__ = "notification"
    __table_args__ = (
        Index("ix_notification_user_id_created_at_id", "user_id", "created_at", "id"),
        Index(
            "uq_notification_user_id_type_suggestion_id",
            "user_id",
            "type",
            text("(payload ->> 'suggestion_id')"),
            unique=True,
            postgresql_where=text("(payload ->> 'suggestion_id') IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(_JSON)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
