"""In-app notifications (spec F17, D79).

`notify` is the only way producers write a notification. It adds the row in the caller's
transaction (it never commits), so an event that rolls back leaves no notification, and it is
idempotent per (user, type, `payload.suggestion_id`): the unique index turns a retry into a no-op.

Nothing here logs: payloads carry ids and dates only, and no food, meal or user name ever reaches a
notification, a log line, a metric or a span (rule 6).
"""

import base64
import binascii
import datetime as dt
import json
import uuid
from collections.abc import Collection
from typing import Any

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.errors import ProblemError
from app.models import Food, Meal, MealDay, MealItem, Notification, Plan, PlannedMeal, User
from app.schemas import notifications as out
from app.schemas.problem import FieldError


def notify(
    db: Session,
    user_id: uuid.UUID,
    type_: out.NotificationType,
    payload: dict[str, Any],
    now: dt.datetime,
) -> uuid.UUID | None:
    """Add one unread notification for `user_id` in the caller's transaction.

    Returns its id, or `None` when the same (user, type, suggestion) was already notified.
    Payload keys outside the contract's `NotificationPayload` are a programming error."""
    unknown = set(payload) - out.PAYLOAD_KEYS
    if unknown:
        raise ValueError(f"unknown notification payload keys: {sorted(unknown)}")
    stored = json.loads(json.dumps(payload, default=str))
    return db.scalar(
        insert(Notification)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            type=type_,
            payload=stored,
            created_at=now,
            read_at=None,
        )
        .on_conflict_do_nothing()
        .returning(Notification.id)
    )


def discard_unread_for_suggestions(
    db: Session, user_id: uuid.UUID, type_: out.NotificationType, suggestion_ids: Collection[Any]
) -> None:
    """Delete the still-unread notifications about the given (replaced) suggestions (D79.2)."""
    ids = [str(i) for i in suggestion_ids]
    if not ids:
        return
    db.execute(
        delete(Notification).where(
            Notification.user_id == user_id,
            Notification.type == type_,
            Notification.read_at.is_(None),
            Notification.payload["suggestion_id"].as_string().in_(ids),
        )
    )


# ───────────── content removed (D66, D71) ─────────────


def users_with_content_removed_by(db: Session, deleted_user_id: uuid.UUID) -> list[uuid.UUID]:
    """The other users whose meals lose an item (a custom food of the deleted user) or whose meal
    plans lose a planned meal (a meal of the deleted user). Run before the delete."""
    owners = select(Meal.owner_id).where(
        Meal.id.in_(
            select(MealItem.meal_id)
            .join(Food, Food.id == MealItem.food_id)
            .where(Food.owner_id == deleted_user_id)
        ),
        Meal.owner_id.is_not(None),
    )
    planners = (
        select(Plan.athlete_id)
        .join(MealDay, MealDay.plan_id == Plan.id)
        .join(PlannedMeal, PlannedMeal.meal_day_id == MealDay.id)
        .join(Meal, Meal.id == PlannedMeal.meal_id)
        .where(Meal.owner_id == deleted_user_id)
    )
    found = set(db.scalars(owners)) | set(db.scalars(planners))
    found.discard(deleted_user_id)
    if not found:
        return []
    return sorted(db.scalars(select(User.id).where(User.id.in_(found))))


def notify_content_removed(db: Session, deleted_user_id: uuid.UUID, now: dt.datetime) -> int:
    """One `content_removed` notification per affected user, however many rows are affected.

    Must run before the user is deleted (the triggers of D66 and D71 remove the rows during the
    delete). Writes in the caller's transaction; returns how many users were notified."""
    users = users_with_content_removed_by(db, deleted_user_id)
    for user_id in users:
        notify(db, user_id, "content_removed", {}, now)
    return len(users)


# ───────────── read side ─────────────


def unread_count(db: Session, user_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        or 0
    )


def view(row: Notification) -> out.Notification:
    return out.Notification(
        id=row.id,
        type=row.type,  # type: ignore[arg-type]
        payload=row.payload,
        created_at=row.created_at,
        read_at=row.read_at,
    )


def _bad_cursor() -> ProblemError:
    return ProblemError(
        400,
        "bad_request",
        "One or more parameters are invalid.",
        errors=[
            FieldError(field="cursor", code="invalid_format", message="The cursor is invalid.")
        ],
    )


def _encode(row: Notification) -> str:
    raw = json.dumps([row.created_at.isoformat(), str(row.id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(cursor: str) -> tuple[dt.datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        created_at, row_id = json.loads(base64.urlsafe_b64decode(padded))
        parsed = dt.datetime.fromisoformat(created_at)
        if parsed.tzinfo is None:
            raise ValueError
        return parsed, uuid.UUID(str(row_id))
    except (binascii.Error, ValueError, TypeError):
        raise _bad_cursor() from None


def list_notifications(
    db: Session, user: User, *, unread_only: bool, limit: int, cursor: str | None
) -> out.NotificationPage:
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.read_at.is_(None))
    if cursor:
        at, last_id = _decode(cursor)
        query = query.where(
            or_(
                Notification.created_at < at,
                and_(Notification.created_at == at, Notification.id < last_id),
            )
        )
    rows = list(
        db.scalars(
            query.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1)
        )
    )
    page = rows[:limit]
    return out.NotificationPage(
        items=[view(r) for r in page],
        unread_count=unread_count(db, user.id),
        next_cursor=_encode(page[-1]) if len(rows) > limit else None,
    )


def mark_read(
    db: Session, user: User, notification_id: uuid.UUID, now: dt.datetime
) -> out.Notification:
    """Idempotent: the first `read_at` is kept. Another user's or an unknown id is 403 (D41)."""
    row = db.scalar(
        select(Notification)
        .where(Notification.id == notification_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.user_id != user.id:
        raise ProblemError(403, "forbidden", "You do not have access to this notification.")
    if row.read_at is None:
        row.read_at = now
        db.commit()
    return view(row)


def mark_all_read(db: Session, user: User, now: dt.datetime) -> out.MarkAllReadResult:
    result = db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=now)
    )
    db.commit()
    return out.MarkAllReadResult(updated=result.rowcount)  # type: ignore[attr-defined]
