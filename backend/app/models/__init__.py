"""SQLAlchemy 2 models (spec §8). Import every model module here so Alembic sees it."""

from app.models.base import Base
from app.models.exercise import Exercise
from app.models.feature_flag import FeatureFlag
from app.models.user import SignInFailure, User

__all__ = ["Base", "Exercise", "FeatureFlag", "SignInFailure", "User"]
