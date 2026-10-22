"""`User` (spec §8) and the failed sign-in log behind the F1.6 rate limit."""

import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, Date, DateTime, Index, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

ROLES = ("athlete", "coach")
UNITS = ("metric", "imperial")


class User(Base):
    """An athlete or coach account. `role` is fixed at sign-up (D9)."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(f"role IN {ROLES!r}", name="role"),
        CheckConstraint(f"units IN {UNITS!r}", name="units"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(60))
    role: Mapped[str] = mapped_column(String(16))
    birth_date: Mapped[dt.date] = mapped_column(Date)
    units: Mapped[str] = mapped_column(String(16))
    timezone: Mapped[str] = mapped_column(String(64))
    disclaimer_accepted_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))


# F1.3: emails are unique case-insensitively; the address itself is stored as typed.
Index("uq_users_lower_email", func.lower(User.email), unique=True)


class SignInFailure(Base):
    """One failed sign-in. Keyed by a SHA-256 of the lower-cased email, never the email itself,
    and kept only for the rate-limit window (F1.6). Unknown emails are counted too, so the
    limit does not reveal whether an account exists."""

    __tablename__ = "sign_in_failures"
    __table_args__ = (
        Index("ix_sign_in_failures_email_key_failed_at", "email_key", "failed_at"),
        Index("ix_sign_in_failures_failed_at", "failed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email_key: Mapped[str] = mapped_column(String(64))
    failed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
