"""SQLAlchemy 2 models (spec §8). Import every model module here so Alembic sees it."""

from app.models.athlete import AthleteProfile, BodyMetric, Targets
from app.models.base import Base
from app.models.coach import CoachLink, CoachProfile, Entitlement
from app.models.exercise import Exercise
from app.models.feature_flag import FeatureFlag
from app.models.food import Food, Meal, MealItem
from app.models.meal_log import MealLog, MealLogItem
from app.models.note import CoachNote
from app.models.notification import Notification
from app.models.plan import (
    MealDay,
    Plan,
    PlanChange,
    PlannedExercise,
    PlannedMeal,
    TrainingDay,
)
from app.models.session import ExtraActivity, SetLog, TrainingSession
from app.models.suggestion import Suggestion
from app.models.user import SignInFailure, User

__all__ = [
    "AthleteProfile",
    "Base",
    "BodyMetric",
    "CoachLink",
    "CoachNote",
    "CoachProfile",
    "Entitlement",
    "Exercise",
    "ExtraActivity",
    "FeatureFlag",
    "Food",
    "Meal",
    "MealDay",
    "MealItem",
    "MealLog",
    "MealLogItem",
    "Notification",
    "Plan",
    "PlanChange",
    "PlannedExercise",
    "PlannedMeal",
    "SetLog",
    "SignInFailure",
    "Suggestion",
    "Targets",
    "TrainingDay",
    "TrainingSession",
    "User",
]
