"""The one place that decides who may act on an athlete's data (spec F16.1/F16.4, D41).

Rules, from the `x-fitwise-access` value of the operation in `openapi.yaml`:

* `owner`: the athlete themselves. A coach with an active link gets 403 `wrong_role` (coaches
  cannot log or change the profile, F16.4).
* `owner-or-coach`: the athlete, or a coach with an `active` coach link (read and write).

A coach calling `me` has no data of their own: 403 `wrong_role` on `owner` operations, 403
`not_linked` on `owner-or-coach` ones. Everything else (no link, `pending`/`declined`/`ended`
link, other athlete, an unknown id) is 403 `not_linked` with the same body, so ids cannot be
enumerated (D41). A malformed id is 400. Only `status == 'active'` counts as a link and it is
queried on every request, so ending a link takes effect immediately. Nothing here logs.
"""

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ProblemError
from app.models import CoachLink, User

Rule = Literal["owner", "owner-or-coach"]


@dataclass(frozen=True)
class AthleteAccess:
    """`actor` is the signed-in caller, `athlete` the owner of the data being accessed."""

    actor: User
    athlete: User

    @property
    def by_coach(self) -> bool:
        return self.actor.id != self.athlete.id


def not_linked() -> ProblemError:
    return ProblemError(403, "not_linked", "You do not have access to this athlete.")


def has_active_link(db: Session, coach_id: uuid.UUID, athlete_id: uuid.UUID) -> bool:
    return (
        db.scalar(
            select(CoachLink.id).where(
                CoachLink.coach_id == coach_id,
                CoachLink.athlete_id == athlete_id,
                CoachLink.status == "active",
            )
        )
        is not None
    )


def resolve(db: Session, actor: User, athlete_id: str | uuid.UUID, rule: Rule) -> AthleteAccess:
    """The caller's access to `athlete_id` (`me`, a UUID, or a UUID object) under `rule`."""
    if athlete_id == "me":
        if actor.role != "athlete":  # a coach has no data of their own
            if rule == "owner":
                raise ProblemError(403, "wrong_role", "Only athletes can do this.")
            raise not_linked()
        return AthleteAccess(actor, actor)
    try:
        target_id = athlete_id if isinstance(athlete_id, uuid.UUID) else uuid.UUID(athlete_id)
    except ValueError:
        raise ProblemError(400, "bad_request", "The athlete id is invalid.") from None
    if actor.role == "athlete":
        if target_id != actor.id:
            raise not_linked()
        return AthleteAccess(actor, actor)
    target = db.get(User, target_id)
    if target is None or target.role != "athlete" or not has_active_link(db, actor.id, target_id):
        raise not_linked()
    if rule == "owner":
        raise ProblemError(403, "wrong_role", "Coaches cannot log or change the athlete's data.")
    return AthleteAccess(actor, target)
