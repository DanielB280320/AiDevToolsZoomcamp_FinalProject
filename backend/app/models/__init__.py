"""SQLAlchemy 2 models (spec §8). Import every model module here so Alembic sees it."""

from app.models.athlete import AthleteProfile, BodyMetric, Targets
from app.models.base import Base
from app.models.exercise import Exercise
from app.models.feature_flag import FeatureFlag
from app.models.food import Food, Meal, MealItem
from app.models.plan import Plan, PlanChange, PlannedExercise, TrainingDay
from app.models.session import ExtraActivity, SetLog, TrainingSession
from app.models.user import SignInFailure, User

__all__ = [
    "AthleteProfile",
    "Base",
    "BodyMetric",
    "Exercise",
    "ExtraActivity",
    "FeatureFlag",
    "Food",
    "Meal",
    "MealItem",
    "Plan",
    "PlanChange",
    "PlannedExercise",
    "SetLog",
    "SignInFailure",
    "Targets",
    "TrainingDay",
    "TrainingSession",
    "User",
]
