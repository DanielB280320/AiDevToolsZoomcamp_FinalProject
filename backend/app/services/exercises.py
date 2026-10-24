"""Exercise catalog: search with keyset pagination, and custom exercises (spec F4).

Visibility (F4.3, D47): seed exercises, the caller's own custom exercises, and custom exercises
of the caller's active-link counterpart. Links arrive with #47; until then the last part is
empty, so a custom exercise is returned to its creator only.

Nothing here logs: exercise names are user content (spec §6.5).
"""

import base64
import binascii
import json
import uuid

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ProblemError
from app.models import Exercise, User
from app.schemas.exercises import Exercise as ExerciseOut
from app.schemas.exercises import ExerciseInput, ExercisePage
from app.schemas.problem import FieldError
from app.schemas.users import UserRef


def _view(exercise: Exercise, owner: User | None) -> ExerciseOut:
    return ExerciseOut.model_validate(
        {
            "id": exercise.id,
            "name": exercise.name,
            "muscle_group": exercise.muscle_group,
            "equipment": exercise.equipment,
            "type": exercise.type,
            "met": exercise.met,
            "increment_kg": exercise.increment_kg,
            "region": exercise.region,
            "allows_added_weight": exercise.allows_added_weight,
            "is_custom": exercise.owner_id is not None,
            "owner": (
                UserRef.model_validate(
                    {"id": owner.id, "display_name": owner.display_name, "role": owner.role}
                )
                if owner is not None
                else None
            ),
        }
    )


def _encode_cursor(exercise: Exercise) -> str:
    raw = json.dumps([exercise.name.lower(), str(exercise.id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _bad_cursor() -> ProblemError:
    return ProblemError(
        400,
        "bad_request",
        "One or more parameters are invalid.",
        errors=[
            FieldError(field="cursor", code="invalid_format", message="The cursor is invalid.")
        ],
    )


def _decode_cursor(cursor: str) -> tuple[str, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        name, exercise_id = json.loads(base64.urlsafe_b64decode(padded))
        return str(name) if isinstance(name, str) else _no_name(), uuid.UUID(str(exercise_id))
    except (binascii.Error, ValueError, TypeError):
        raise _bad_cursor() from None


def _no_name() -> str:
    raise ValueError("cursor has no name")


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_exercises(
    session: Session,
    user: User,
    *,
    q: str | None,
    muscle_group: str | None,
    equipment: str | None,
    type_: str | None,
    region: str | None,
    limit: int,
    cursor: str | None,
) -> ExercisePage:
    visible = or_(Exercise.owner_id.is_(None), Exercise.owner_id == user.id)
    statement = select(Exercise, User).outerjoin(User, User.id == Exercise.owner_id).where(visible)
    if q and q.strip():
        statement = statement.where(
            func.lower(Exercise.name).like(f"%{_escape_like(q.strip().lower())}%", escape="\\")
        )
    for column, value in (
        (Exercise.muscle_group, muscle_group),
        (Exercise.equipment, equipment),
        (Exercise.type, type_),
        (Exercise.region, region),
    ):
        if value is not None:
            statement = statement.where(column == value)
    if cursor:
        last_name, last_id = _decode_cursor(cursor)
        statement = statement.where(
            tuple_(func.lower(Exercise.name), Exercise.id) > tuple_(last_name, last_id)
        )
    rows = session.execute(
        statement.order_by(func.lower(Exercise.name), Exercise.id).limit(limit + 1)
    ).all()
    page = rows[:limit]
    next_cursor = _encode_cursor(page[-1][0]) if len(rows) > limit else None
    return ExercisePage(items=[_view(e, o) for e, o in page], next_cursor=next_cursor)


def _name_taken() -> ProblemError:
    return ProblemError(
        409,
        "exercise_name_taken",
        "An exercise with this name already exists.",
        errors=[FieldError(field="name", code="taken", message="This name is already used.")],
    )


def create_exercise(session: Session, user: User, body: ExerciseInput) -> ExerciseOut:
    """Create a custom exercise owned by `user`. 409 when the name (case-insensitive) is already
    a seed exercise or one of the caller's own exercises."""
    clash = session.scalar(
        select(Exercise.id)
        .where(
            func.lower(Exercise.name) == body.name.lower(),
            or_(Exercise.owner_id.is_(None), Exercise.owner_id == user.id),
        )
        .limit(1)
    )
    if clash is not None:
        raise _name_taken()
    exercise = Exercise(owner_id=user.id, **body.model_dump())
    session.add(exercise)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()  # a concurrent request won the unique index; drop the driver message
        raise _name_taken() from None
    return _view(exercise, user)
