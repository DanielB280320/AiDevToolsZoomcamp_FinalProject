"""Coach notes (spec F16, D84): create, list, edit and delete.

Access is decided before this module (`CoachAccess` for create, `OwnerOrCoachAccess` for the rest);
here only the note's own rules live: the target must belong to the athlete (404 otherwise), and
only the author may edit or delete (403 `forbidden`). Creating a note adds one `coach_note`
notification in the same transaction (`notify`). The note text is never logged, put in a metric or
a span, or copied into the notification (rule 6): nothing in this module logs.
"""

import datetime as dt
import uuid
from collections.abc import Collection, Sequence

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.errors import ProblemError
from app.models import CoachNote, Exercise, TrainingSession, User
from app.schemas import notes as out
from app.services.notifications import notify


def _not_found() -> ProblemError:
    return ProblemError(404, "not_found", "The note's target was not found.")


def view_many(db: Session, rows: Sequence[CoachNote]) -> list[out.Note]:
    """Views of `rows` in their order, with the authors and exercises loaded in two queries."""
    author_ids = {r.author_id for r in rows}
    exercise_ids = {r.exercise_id for r in rows if r.exercise_id is not None}
    authors = (
        {u.id: u for u in db.scalars(select(User).where(User.id.in_(author_ids)))}
        if author_ids
        else {}
    )
    exercises = (
        {e.id: e for e in db.scalars(select(Exercise).where(Exercise.id.in_(exercise_ids)))}
        if exercise_ids
        else {}
    )
    result = []
    for row in rows:
        author = authors[row.author_id]
        exercise = exercises.get(row.exercise_id) if row.exercise_id else None
        result.append(
            out.Note.model_validate(
                {
                    "id": row.id,
                    "athlete_id": row.athlete_id,
                    "author": {
                        "id": author.id,
                        "display_name": author.display_name,
                        "role": author.role,
                    },
                    "scope": row.scope,
                    "date": row.date,
                    "session_id": row.session_id,
                    "exercise": (
                        {
                            "id": exercise.id,
                            "name": exercise.name,
                            "type": exercise.type,
                            "equipment": exercise.equipment,
                            "muscle_group": exercise.muscle_group,
                        }
                        if exercise
                        else None
                    ),
                    "text": row.text,
                    "created_at": row.created_at,
                    "updated_at": row.updated_at,
                }
            )
        )
    return result


def create(
    db: Session, athlete: User, author: User, body: out.NoteInput, now: dt.datetime
) -> out.Note:
    day: dt.date | None = None
    session_id: uuid.UUID | None = None
    exercise_id: uuid.UUID | None = None
    if body.scope == "day":
        day = body.date
    else:
        if body.session_id is not None:
            session = db.get(TrainingSession, body.session_id)
            if session is None or session.athlete_id != athlete.id:
                raise _not_found()
            session_id, day = session.id, session.date
        if body.scope == "exercise":
            exercise = db.get(Exercise, body.exercise_id) if body.exercise_id is not None else None
            if exercise is None or exercise.owner_id not in (None, athlete.id):
                raise _not_found()
            exercise_id = exercise.id
    row = CoachNote(
        id=uuid.uuid4(),
        athlete_id=athlete.id,
        author_id=author.id,
        scope=body.scope,
        date=day,
        session_id=session_id,
        exercise_id=exercise_id,
        text=body.text,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    payload: dict[str, object] = {
        "note_id": row.id,
        "actor": {"id": author.id, "role": author.role},
    }
    if day is not None:
        payload["date"] = day
    notify(db, athlete.id, "coach_note", payload, now)
    db.commit()
    return view_many(db, [row])[0]


def list_notes(
    db: Session,
    athlete: User,
    *,
    from_: dt.date | None,
    to: dt.date | None,
    scope: str | None,
    session_id: uuid.UUID | None,
    exercise_id: uuid.UUID | None,
) -> out.NoteList:
    query = select(CoachNote).where(CoachNote.athlete_id == athlete.id)
    if from_ is not None:
        query = query.where(CoachNote.date >= from_)
    if to is not None:
        query = query.where(CoachNote.date <= to)
    if scope is not None:
        query = query.where(CoachNote.scope == scope)
    if session_id is not None:
        query = query.where(CoachNote.session_id == session_id)
    if exercise_id is not None:
        query = query.where(CoachNote.exercise_id == exercise_id)
    rows = db.scalars(query.order_by(CoachNote.created_at.desc(), CoachNote.id.desc())).all()
    return out.NoteList(items=view_many(db, rows))


def for_day(
    db: Session,
    athlete_id: uuid.UUID,
    day: dt.date,
    session_id: uuid.UUID | None,
    exercise_ids: Collection[uuid.UUID],
) -> list[out.Note]:
    """Notes of a day view: on the day, on its session, and on its exercises (a note on an
    exercise with no session is standing: it shows wherever that exercise is trained)."""
    anchors = [and_(CoachNote.scope == "day", CoachNote.date == day)]
    if session_id is not None:
        anchors.append(and_(CoachNote.scope == "session", CoachNote.session_id == session_id))
        anchors.append(and_(CoachNote.scope == "exercise", CoachNote.session_id == session_id))
    if exercise_ids:
        anchors.append(
            and_(
                CoachNote.scope == "exercise",
                CoachNote.session_id.is_(None),
                CoachNote.exercise_id.in_(exercise_ids),
            )
        )
    rows = db.scalars(
        select(CoachNote)
        .where(CoachNote.athlete_id == athlete_id, or_(*anchors))
        .order_by(CoachNote.created_at.desc(), CoachNote.id.desc())
    ).all()
    return view_many(db, rows)


def _own(db: Session, athlete: User, actor: User, note_id: uuid.UUID) -> CoachNote:
    row = db.get(CoachNote, note_id)
    if row is None or row.athlete_id != athlete.id:
        raise ProblemError(404, "not_found", "The note was not found.")
    if row.author_id != actor.id:
        raise ProblemError(403, "forbidden", "Only the author can change this note.")
    return row


def update(
    db: Session, athlete: User, actor: User, note_id: uuid.UUID, text: str, now: dt.datetime
) -> out.Note:
    row = _own(db, athlete, actor, note_id)
    row.text = text
    row.updated_at = now
    db.commit()
    return view_many(db, [row])[0]


def delete(db: Session, athlete: User, actor: User, note_id: uuid.UUID) -> None:
    row = _own(db, athlete, actor, note_id)
    db.delete(row)
    db.commit()
