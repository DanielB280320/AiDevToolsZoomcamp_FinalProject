"""`/notifications` (openapi.yaml, tag Notifications). Owner only (D79.6)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from app.dependencies import CurrentUser, SessionDep
from app.schemas.base import NoNul
from app.schemas.notifications import MarkAllReadResult, Notification, NotificationPage
from app.schemas.problem import Problem
from app.services import notifications
from app.services.clock import ClockDep

router = APIRouter(prefix="/notifications", tags=["Notifications"])

_PROBLEM = {"model": Problem}


@router.get(
    "",
    operation_id="listNotifications",
    response_model=NotificationPage,
    responses={400: _PROBLEM, 401: _PROBLEM},
)
def list_notifications(
    user: CurrentUser,
    db: SessionDep,
    unread_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, NoNul] = None,
) -> NotificationPage:
    """My notifications, newest first, with the unread count (F17.2)."""
    return notifications.list_notifications(
        db, user, unread_only=unread_only, limit=limit, cursor=cursor
    )


@router.post(
    "/read-all",
    operation_id="markAllNotificationsRead",
    response_model=MarkAllReadResult,
    responses={401: _PROBLEM},
)
def mark_all_read(user: CurrentUser, db: SessionDep, clock: ClockDep) -> MarkAllReadResult:
    return notifications.mark_all_read(db, user, clock.now())


@router.post(
    "/{notification_id}/read",
    operation_id="markNotificationRead",
    response_model=Notification,
    responses={400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM},
)
def mark_read(
    notification_id: uuid.UUID, user: CurrentUser, db: SessionDep, clock: ClockDep
) -> Notification:
    return notifications.mark_read(db, user, notification_id, clock.now())
