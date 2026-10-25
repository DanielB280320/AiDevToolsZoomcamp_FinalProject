"""`SetLog` response schema (openapi.yaml), shared by the session and logging responses."""

import datetime as dt
import uuid

from app.schemas.base import ResponseModel


class SetLog(ResponseModel):
    id: uuid.UUID
    session_id: uuid.UUID
    planned_exercise_id: uuid.UUID | None
    exercise_id: uuid.UUID
    set_no: int
    skipped: bool
    target_reps: int | None
    target_weight_kg: float | None
    target_seconds: int | None
    reps: int | None
    weight_kg: float | None
    seconds: int | None
    distance_m: float | None
    logged_at: dt.datetime
