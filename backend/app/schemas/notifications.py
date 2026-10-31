"""Notification response schemas (openapi.yaml tag Notifications)."""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import Field

from app.schemas.base import ResponseModel

NotificationType = Literal[
    "progression_suggestion",
    "calorie_suggestion",
    "recalc_prompt",
    "coach_note",
    "link_request_received",
    "link_request_approved",
    "link_request_declined",
    "link_ended",
    "plan_edited_by_coach",
    "content_removed",
]

# The keys of the contract's `NotificationPayload`: ids and dates only (rule 6).
PAYLOAD_KEYS = frozenset(
    {"athlete_id", "suggestion_id", "note_id", "link_id", "plan_id", "date", "actor"}
)


class Notification(ResponseModel):
    id: uuid.UUID
    type: NotificationType
    payload: dict[str, Any]
    created_at: dt.datetime
    read_at: dt.datetime | None


class NotificationPage(ResponseModel):
    items: list[Notification]
    unread_count: Annotated[int, Field(ge=0)]
    next_cursor: str | None


class MarkAllReadResult(ResponseModel):
    updated: Annotated[int, Field(ge=0)]
