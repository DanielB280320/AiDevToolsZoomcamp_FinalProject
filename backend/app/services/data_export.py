"""`GET /me/export` (spec F18.1): a ZIP of the caller's own data.

Every query is scoped to the caller's id, and columns that point at *other* users (the plan author,
the hand editor, the suggestion decider) are left out, so nothing of another user can enter the
archive. Values are metric as stored (rule 5). Nothing here logs (rule 6).
"""

import csv
import datetime as dt
import io
import json
import uuid
import zipfile
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, class_mapper

from app.models import (
    AthleteProfile,
    BodyMetric,
    CoachProfile,
    ExtraActivity,
    Food,
    MealLog,
    MealLogItem,
    Plan,
    PlannedExercise,
    PlannedMeal,
    SetLog,
    Suggestion,
    Targets,
    TrainingSession,
    User,
)

# Columns that reference another user's account.
_OTHER_USER_COLUMNS = frozenset({"created_by", "edited_by", "decided_by"})
_PASSWORD = frozenset({"password_hash"})


def _plain(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.UTC).isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return value


def _names(model: type, drop: frozenset[str]) -> list[str]:
    return [str(c.key) for c in class_mapper(model).column_attrs if c.key not in drop]


def _as_dict(row: Any, drop: frozenset[str] = _OTHER_USER_COLUMNS) -> dict[str, Any]:
    return {n: _plain(getattr(row, n)) for n in _names(type(row), drop)}


def _csv(rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                k: (json.dumps(v, sort_keys=True) if isinstance(v, dict | list) else v)
                for k, v in row.items()
            }
        )
    return out.getvalue().encode()


def _profile(db: Session, user: User) -> dict[str, Any]:
    profile = db.get(AthleteProfile, user.id)
    coach = db.get(CoachProfile, user.id)
    targets = db.scalars(
        select(Targets).where(Targets.user_id == user.id).order_by(Targets.valid_from)
    )
    return {
        "user": _as_dict(user, _PASSWORD),
        "athlete_profile": None if profile is None else _as_dict(profile),
        "targets": [_as_dict(t) for t in targets],
        "coach_profile": None if coach is None else _as_dict(coach),
    }


def _plan_versions(db: Session, user: User) -> list[dict[str, Any]]:
    versions: list[dict[str, Any]] = []
    plans = db.scalars(select(Plan).where(Plan.athlete_id == user.id).order_by(Plan.version))
    for plan in plans:
        item = _as_dict(plan)
        item["training_days"] = []
        for day in plan.training_days:
            day_data = _as_dict(day)
            exercises = db.scalars(
                select(PlannedExercise)
                .where(PlannedExercise.training_day_id == day.id)
                .order_by(PlannedExercise.position)
            )
            day_data["exercises"] = [_as_dict(e) for e in exercises]
            item["training_days"].append(day_data)
        item["meal_days"] = []
        for meal_day in plan.meal_days:
            meal_data = _as_dict(meal_day)
            meals = db.scalars(
                select(PlannedMeal)
                .where(PlannedMeal.meal_day_id == meal_day.id)
                .order_by(PlannedMeal.position)
            )
            meal_data["meals"] = [_as_dict(m) for m in meals]
            item["meal_days"].append(meal_data)
        versions.append(item)
    return versions


def _set_logs(db: Session, user: User) -> bytes:
    rows = db.execute(
        select(SetLog, TrainingSession.date)
        .join(TrainingSession, TrainingSession.id == SetLog.session_id)
        .where(TrainingSession.athlete_id == user.id)
        .order_by(TrainingSession.date, SetLog.exercise_id, SetLog.set_no)
    )
    data = [{"date": _plain(d), **_as_dict(s)} for s, d in rows]
    return _csv(data, ["date", *_names(SetLog, _OTHER_USER_COLUMNS)])


def _meal_logs(db: Session, user: User) -> bytes:
    rows = db.execute(
        select(MealLog, MealLogItem, Food.name)
        .outerjoin(MealLogItem, MealLogItem.meal_log_id == MealLog.id)
        .outerjoin(Food, Food.id == MealLogItem.food_id)
        .where(MealLog.athlete_id == user.id)
        .order_by(MealLog.date, MealLog.logged_at, MealLog.id, MealLogItem.position)
    )
    data = []
    for log, item, food_name in rows:
        entry = _as_dict(log)
        entry["food_id"] = None if item is None else _plain(item.food_id)
        entry["food_name"] = food_name
        entry["grams"] = None if item is None else item.grams
        data.append(entry)
    return _csv(data, [*_names(MealLog, _OTHER_USER_COLUMNS), "food_id", "food_name", "grams"])


def _simple(db: Session, user: User, model: Any, owner: Any, order: Sequence[Any]) -> bytes:
    rows = db.scalars(select(model).where(owner == user.id).order_by(*order))
    return _csv([_as_dict(r) for r in rows], _names(model, _OTHER_USER_COLUMNS))


def build_zip(db: Session, user: User) -> bytes:
    """The archive as bytes: `profile.json`, `plan_versions.json` and five CSVs."""
    files: dict[str, bytes] = {
        "profile.json": json.dumps(_profile(db, user), indent=2, sort_keys=True).encode(),
        "plan_versions.json": json.dumps(
            _plan_versions(db, user), indent=2, sort_keys=True
        ).encode(),
        "set_logs.csv": _set_logs(db, user),
        "meal_logs.csv": _meal_logs(db, user),
        "body_metrics.csv": _simple(db, user, BodyMetric, BodyMetric.user_id, (BodyMetric.date,)),
        "extra_activities.csv": _simple(
            db,
            user,
            ExtraActivity,
            ExtraActivity.athlete_id,
            (ExtraActivity.date, ExtraActivity.created_at),
        ),
        "suggestions.csv": _simple(
            db, user, Suggestion, Suggestion.athlete_id, (Suggestion.created_at,)
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()
