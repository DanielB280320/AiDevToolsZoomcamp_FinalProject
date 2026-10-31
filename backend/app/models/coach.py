"""`CoachProfile`, `CoachLink` and the `Entitlement` stub (spec §8, F16).

A link is a row per request, so `declined` and `ended` rows stay as history and never block a new
request. The partial unique indexes enforce "one active coach and at most one pending request per
athlete" even under concurrent requests (F16 Linking)."""

import datetime as dt
import uuid

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

LINK_STATUSES = ("pending", "active", "declined", "ended")
LINK_SOURCES = ("request",)
BIO_MAX = 500
ENTITLEMENT_CAN_HAVE_COACH = "can_have_coach"


class CoachProfile(Base):
    __tablename__ = "coach_profile"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    bio: Mapped[str] = mapped_column(String(BIO_MAX), default="")
    discoverable: Mapped[bool] = mapped_column(Boolean, default=True)


class CoachLink(Base):
    __tablename__ = "coach_link"
    __table_args__ = (
        CheckConstraint(f"status IN {LINK_STATUSES!r}", name="status"),
        CheckConstraint(f"source IN {LINK_SOURCES!r}", name="source"),
        Index("ix_coach_link_athlete_id_created_at", "athlete_id", "created_at"),
        Index("ix_coach_link_coach_id_created_at", "coach_id", "created_at"),
        Index(
            "uq_coach_link_athlete_id_active",
            "athlete_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index(
            "uq_coach_link_athlete_id_pending",
            "athlete_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    coach_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    athlete_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16), default="request")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


class Entitlement(Base):
    """Future paid-tier hook. No row means the default (true) in the MVP."""

    __tablename__ = "entitlement"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[bool] = mapped_column(Boolean)
