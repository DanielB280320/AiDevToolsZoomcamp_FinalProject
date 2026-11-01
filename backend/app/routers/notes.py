"""Coach notes endpoints (openapi.yaml, tag Notes, F16)."""

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Response

from app.dependencies import CoachAccess, OwnerOrCoachAccess, SessionDep
from app.schemas.notes import Note, NoteInput, NoteList, NoteScope, NoteUpdate
from app.schemas.problem import Problem
from app.services import notes
from app.services.clock import ClockDep

router = APIRouter(tags=["Notes"])

_PROBLEM: dict[str, Any] = {"model": Problem}
_COMMON: dict[int | str, dict[str, Any]] = {400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM}


@router.get(
    "/athletes/{athlete_id}/notes",
    operation_id="listNotes",
    response_model=NoteList,
    responses=_COMMON,
)
def list_notes(
    access: OwnerOrCoachAccess,
    db: SessionDep,
    from_: Annotated[dt.date | None, Query(alias="from")] = None,
    to: dt.date | None = None,
    scope: NoteScope | None = None,
    session_id: uuid.UUID | None = None,
    exercise_id: uuid.UUID | None = None,
) -> NoteList:
    """Newest first. Notes stay visible to the athlete after the link ends."""
    return notes.list_notes(
        db,
        access.athlete,
        from_=from_,
        to=to,
        scope=scope,
        session_id=session_id,
        exercise_id=exercise_id,
    )


@router.post(
    "/athletes/{athlete_id}/notes",
    operation_id="createNote",
    status_code=201,
    response_model=Note,
    responses={**_COMMON, 404: _PROBLEM, 422: _PROBLEM},
)
def create_note(access: CoachAccess, body: NoteInput, db: SessionDep, clock: ClockDep) -> Note:
    return notes.create(db, access.athlete, access.actor, body, clock.now())


@router.put(
    "/athletes/{athlete_id}/notes/{note_id}",
    operation_id="updateNote",
    response_model=Note,
    responses={**_COMMON, 404: _PROBLEM, 422: _PROBLEM},
)
def update_note(
    note_id: uuid.UUID,
    access: OwnerOrCoachAccess,
    body: NoteUpdate,
    db: SessionDep,
    clock: ClockDep,
) -> Note:
    return notes.update(db, access.athlete, access.actor, note_id, body.text, clock.now())


@router.delete(
    "/athletes/{athlete_id}/notes/{note_id}",
    operation_id="deleteNote",
    status_code=204,
    responses={**_COMMON, 404: _PROBLEM},
)
def delete_note(note_id: uuid.UUID, access: OwnerOrCoachAccess, db: SessionDep) -> Response:
    notes.delete(db, access.athlete, access.actor, note_id)
    return Response(status_code=204)
