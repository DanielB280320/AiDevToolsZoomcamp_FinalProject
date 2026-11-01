"""Coach note schemas (openapi.yaml, tag Notes)."""

import datetime as dt
import uuid
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.models.note import NOTE_TEXT_MAX
from app.schemas.base import RequestModel, ResponseModel
from app.schemas.plans import ExerciseSummary
from app.schemas.users import UserRef

NoteScope = Literal["day", "session", "exercise"]
NoteText = Annotated[str, Field(min_length=1, max_length=NOTE_TEXT_MAX)]


class NoteInput(RequestModel):
    scope: NoteScope
    date: dt.date | None = None
    session_id: uuid.UUID | None = None
    exercise_id: uuid.UUID | None = None
    text: NoteText

    @model_validator(mode="after")
    def _scope_needs_its_target(self) -> Self:
        needed = {"day": "date", "session": "session_id", "exercise": "exercise_id"}[self.scope]
        if getattr(self, needed) is None:
            raise ValueError(f"{needed} is required when scope is {self.scope}")
        return self


class NoteUpdate(RequestModel):
    text: NoteText


class Note(ResponseModel):
    id: uuid.UUID
    athlete_id: uuid.UUID
    author: UserRef
    scope: NoteScope
    date: dt.date | None
    session_id: uuid.UUID | None
    exercise: ExerciseSummary | None
    text: str
    created_at: dt.datetime
    updated_at: dt.datetime


class NoteList(ResponseModel):
    items: list[Note]
