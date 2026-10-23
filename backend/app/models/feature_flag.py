"""`FeatureFlag` (spec §8): one row per flag that was ever set. No row -> the config default."""

import datetime as dt

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FeatureFlag(Base):
    """A runtime flag value, written only by the ops CLI (`python -m app.cli.flags`).

    `key` and `value` come from the allow-list in `app.config.FEATURE_FLAGS`; `updated_by` is
    an actor label such as `oncall-agent` or `owner`, never a person's name or email.
    """

    __tablename__ = "feature_flag"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(64))
    updated_by: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
