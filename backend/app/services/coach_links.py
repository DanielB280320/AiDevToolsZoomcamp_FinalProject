"""Coach profile, search and link lifecycle (spec F16 Linking, D81).

One row per request: `pending` -> `active` | `declined`, and `pending`/`active` -> `ended`. Rows
stay as history, so `declined` and `ended` never block a new request. Access checks elsewhere
must treat only `status == 'active'` as a link. Every transition notifies the other party through
`notify()` in the same transaction; payloads carry the link id and the actor's id and role only
(rule 6). Nothing here logs.
"""

import datetime as dt
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ProblemError
from app.models import CoachLink, CoachProfile, Entitlement, User
from app.models.coach import ENTITLEMENT_CAN_HAVE_COACH
from app.schemas import coach as out
from app.schemas.base import reject_nul
from app.schemas.problem import FieldError
from app.schemas.users import UserRef
from app.services import notifications

SEARCH_MIN_CHARS = 3
SEARCH_LIMIT = 20


# ───────────── entitlement (stub) ─────────────


def can_have_coach(db: Session, user_id: uuid.UUID) -> bool:
    """MVP stub: true for everyone unless a row says otherwise (future paid-tier hook)."""
    value = db.scalar(
        select(Entitlement.value).where(
            Entitlement.user_id == user_id, Entitlement.key == ENTITLEMENT_CAN_HAVE_COACH
        )
    )
    return True if value is None else bool(value)


# ───────────── profile ─────────────


def get_profile(db: Session, coach: User) -> out.CoachProfile:
    row = db.get(CoachProfile, coach.id)
    return out.CoachProfile(
        user_id=coach.id,
        display_name=coach.display_name,
        bio=row.bio if row else "",
        discoverable=row.discoverable if row else True,
    )


def update_profile(db: Session, coach: User, body: out.CoachProfileInput) -> out.CoachProfile:
    row = db.get(CoachProfile, coach.id)
    if row is None:
        row = CoachProfile(user_id=coach.id)
        db.add(row)
    row.bio = body.bio
    row.discoverable = body.discoverable
    db.commit()
    return get_profile(db, coach)


# ───────────── search ─────────────


def _bad_query(message: str) -> ProblemError:
    return ProblemError(
        400,
        "bad_request",
        "One or more parameters are invalid.",
        errors=[FieldError(field="q", code="too_short", message=message)],
    )


def search_coaches(db: Session, q: str) -> out.CoachSearchResultList:
    """Discoverable coaches by display name (contains, case-insensitive) or exact email.

    A coach without a profile row is discoverable (the default). Emails are matched but never
    selected into the result."""
    term = q.strip()
    reject_nul(term)
    if len(term) < SEARCH_MIN_CHARS:
        # A shorter query is only valid as an exact email, and no valid email is that short.
        raise _bad_query(f"Type at least {SEARCH_MIN_CHARS} characters.")
    rows = db.execute(
        select(User.id, User.display_name, func.coalesce(CoachProfile.bio, ""))
        .outerjoin(CoachProfile, CoachProfile.user_id == User.id)
        .where(
            User.role == "coach",
            func.coalesce(CoachProfile.discoverable, True).is_(True),
            or_(
                User.display_name.icontains(term, autoescape=True),
                func.lower(User.email) == term.lower(),
            ),
        )
        .order_by(func.lower(User.display_name), User.id)
        .limit(SEARCH_LIMIT)
    ).all()
    return out.CoachSearchResultList(
        items=[out.CoachSearchResult(id=r[0], display_name=r[1], bio=r[2]) for r in rows]
    )


# ───────────── views ─────────────


def user_ref(user: User) -> UserRef:
    return UserRef(id=user.id, display_name=user.display_name, role=user.role)  # type: ignore[arg-type]


def view(db: Session, link: CoachLink) -> out.CoachLink:
    coach, athlete = db.get(User, link.coach_id), db.get(User, link.athlete_id)
    assert coach is not None and athlete is not None  # noqa: S101 - FKs cascade on delete
    return out.CoachLink(
        id=link.id,
        status=link.status,  # type: ignore[arg-type]  # constrained by ck_coach_link_status
        source="request",
        coach=user_ref(coach),
        athlete=user_ref(athlete),
        created_at=link.created_at,
        updated_at=link.updated_at,
    )


def list_links(db: Session, user: User, status: str | None) -> out.CoachLinkList:
    column = CoachLink.coach_id if user.role == "coach" else CoachLink.athlete_id
    query = select(CoachLink).where(column == user.id)
    if status is not None:
        query = query.where(CoachLink.status == status)
    rows = db.scalars(query.order_by(CoachLink.created_at.desc(), CoachLink.id.desc()))
    return out.CoachLinkList(items=[view(db, row) for row in rows])


def active_coach(db: Session, athlete_id: uuid.UUID) -> User | None:
    return db.scalar(
        select(User)
        .join(CoachLink, CoachLink.coach_id == User.id)
        .where(CoachLink.athlete_id == athlete_id, CoachLink.status == "active")
    )


def pending_link_id(db: Session, athlete_id: uuid.UUID) -> uuid.UUID | None:
    return db.scalar(
        select(CoachLink.id).where(
            CoachLink.athlete_id == athlete_id, CoachLink.status == "pending"
        )
    )


# ───────────── transitions ─────────────


def _link_exists() -> ProblemError:
    return ProblemError(
        409, "link_exists", "You already have a coach or a pending request. End it first."
    )


def _not_pending() -> ProblemError:
    return ProblemError(409, "link_not_pending", "This link request is no longer pending.")


def _actor(user: User) -> dict[str, object]:
    return {"id": user.id, "role": user.role}


def request_link(
    db: Session, athlete: User, coach_id: uuid.UUID, now: dt.datetime
) -> out.CoachLink:
    if not can_have_coach(db, athlete.id):
        raise ProblemError(403, "entitlement_required", "Your plan does not include a coach.")
    coach = db.get(User, coach_id)
    profile = db.get(CoachProfile, coach_id)
    if coach is None or coach.role != "coach" or (profile is not None and not profile.discoverable):
        raise ProblemError(404, "not_found", "This coach was not found.")
    if active_coach(db, athlete.id) is not None or pending_link_id(db, athlete.id) is not None:
        raise _link_exists()
    link = CoachLink(
        id=uuid.uuid4(),
        coach_id=coach_id,
        athlete_id=athlete.id,
        status="pending",
        source="request",
        created_at=now,
        updated_at=now,
    )
    db.add(link)
    notifications.notify(
        db, coach_id, "link_request_received", {"link_id": link.id, "actor": _actor(athlete)}, now
    )
    _commit_or_exists(db)
    return view(db, link)


def _commit_or_exists(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        # The partial unique indexes: a concurrent request or approval won the race.
        db.rollback()
        raise _link_exists() from None


def _locked(db: Session, link_id: uuid.UUID) -> CoachLink:
    link = db.scalar(
        select(CoachLink)
        .where(CoachLink.id == link_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if link is None:
        raise ProblemError(404, "not_found", "This link was not found.")
    return link


def decide(
    db: Session, coach: User, link_id: uuid.UUID, *, approve: bool, now: dt.datetime
) -> out.CoachLink:
    link = _locked(db, link_id)
    if link.coach_id != coach.id:
        raise ProblemError(403, "forbidden", "You do not have access to this link.")
    if link.status != "pending":
        raise _not_pending()
    if approve:
        other = db.scalar(
            select(CoachLink.id).where(
                CoachLink.athlete_id == link.athlete_id, CoachLink.status == "active"
            )
        )
        if other is not None:
            raise _link_exists()
    link.status = "active" if approve else "declined"
    link.updated_at = now
    notifications.notify(
        db,
        link.athlete_id,
        "link_request_approved" if approve else "link_request_declined",
        {"link_id": link.id, "actor": _actor(coach)},
        now,
    )
    _commit_or_exists(db)
    return view(db, link)


def end(db: Session, user: User, link_id: uuid.UUID, now: dt.datetime) -> out.CoachLink:
    link = _locked(db, link_id)
    if user.id not in (link.coach_id, link.athlete_id):
        raise ProblemError(403, "forbidden", "You do not have access to this link.")
    if link.status not in ("pending", "active"):
        raise _not_pending()
    link.status = "ended"
    link.updated_at = now
    other = link.athlete_id if user.id == link.coach_id else link.coach_id
    notifications.notify(db, other, "link_ended", {"link_id": link.id, "actor": _actor(user)}, now)
    db.commit()
    return view(db, link)
