"""Sign-up, sign-in with the per-email rate limit, and account settings (spec F1).

Nothing here logs: emails, passwords, display names and tokens must never reach telemetry
(spec §6.5), and exceptions raised from here carry only a stable `code`.
"""

import datetime as dt
import hashlib
import math

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ProblemError
from app.models import SignInFailure, User
from app.schemas.problem import FieldError
from app.schemas.users import Me, SignUpRequest, UpdateMeRequest
from app.services.clock import age_on, local_today
from app.services.passwords import hash_password, needs_rehash, verify_password

MINIMUM_AGE_YEARS = 18  # spec §6.3, F1.1
MAX_FAILED_SIGN_INS = 5  # F1.6: the 6th failed attempt within the window gets 429
SIGN_IN_WINDOW = dt.timedelta(minutes=15)


def _email_taken() -> ProblemError:
    return ProblemError(
        409,
        "email_taken",
        "An account with this email already exists.",
        errors=[FieldError(field="email", code="taken", message="This email is already used.")],
    )


def sign_up(session: Session, request: SignUpRequest, now: dt.datetime) -> User:
    if not request.accept_disclaimer:
        raise ProblemError(
            422,
            "disclaimer_required",
            "Accept the disclaimer to create an account.",
            errors=[
                FieldError(
                    field="accept_disclaimer",
                    code="disclaimer_required",
                    message="You must accept the disclaimer.",
                )
            ],
        )
    today = local_today(now, request.timezone)
    if age_on(request.birth_date, today) < MINIMUM_AGE_YEARS:
        raise ProblemError(
            422,
            "underage",
            "You must be at least 18 years old to use FitWise.",
            errors=[
                FieldError(field="birth_date", code="underage", message="You must be 18 or older.")
            ],
        )
    if _find_by_email(session, request.email) is not None:
        raise _email_taken()

    user = User(
        email=request.email,
        password_hash=hash_password(request.password),
        display_name=request.display_name,
        role=request.role,
        birth_date=request.birth_date,
        units=request.units,
        timezone=request.timezone,
        disclaimer_accepted_at=now,
        created_at=now,
        updated_at=now,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        # A concurrent sign-up won the unique index. The driver message contains the email,
        # so it is dropped here rather than chained into the new exception.
        session.rollback()
        raise _email_taken() from None
    return user


def log_in(session: Session, email: str, password: str, now: dt.datetime) -> User:
    """Return the user for correct credentials, else raise 401 `invalid_credentials`.

    Once `MAX_FAILED_SIGN_INS` failures for this email (case-insensitive, known or not) fall
    inside `SIGN_IN_WINDOW`, every attempt gets 429 `rate_limited` until the oldest of them
    leaves the window, even with the right password: answering 200 there would let an attacker
    keep guessing (proposed decision D49).
    """
    key = _email_key(email)
    window_start = now - SIGN_IN_WINDOW
    # Serialise attempts for the same email so parallel guesses cannot overshoot the limit.
    session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))
    session.execute(delete(SignInFailure).where(SignInFailure.failed_at <= window_start))
    failures = session.scalars(
        select(SignInFailure.failed_at)
        .where(SignInFailure.email_key == key, SignInFailure.failed_at > window_start)
        .order_by(SignInFailure.failed_at)
    ).all()
    if len(failures) >= MAX_FAILED_SIGN_INS:
        session.commit()
        unlocks_at = failures[len(failures) - MAX_FAILED_SIGN_INS] + SIGN_IN_WINDOW
        raise _rate_limited(unlocks_at - now)

    user = _find_by_email(session, email)
    if not verify_password(user.password_hash if user else None, password) or user is None:
        session.add(SignInFailure(email_key=key, failed_at=now))
        session.commit()
        raise ProblemError(401, "invalid_credentials", "The email or password is incorrect.")

    session.execute(delete(SignInFailure).where(SignInFailure.email_key == key))
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    session.commit()
    return user


def update_me(session: Session, user: User, request: UpdateMeRequest, now: dt.datetime) -> User:
    for name, value in request.changes().items():
        setattr(user, name, value)
    user.updated_at = now
    session.commit()
    return user


def me_view(user: User) -> Me:
    """The `Me` body. Onboarding, coach links and notifications arrive in later milestones;
    until then athletes are not onboarded, coaches always are, and the rest is empty."""
    return Me(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        role=user.role,  # type: ignore[arg-type]  # constrained by ck_users_role
        birth_date=user.birth_date,
        units=user.units,  # type: ignore[arg-type]  # constrained by ck_users_units
        timezone=user.timezone,
        disclaimer_accepted_at=user.disclaimer_accepted_at.astimezone(dt.UTC),
        created_at=user.created_at.astimezone(dt.UTC),
        onboarding_completed=user.role == "coach",
        active_coach=None,
        pending_coach_link_id=None,
        unread_notification_count=0,
    )


def _find_by_email(session: Session, email: str) -> User | None:
    return session.scalar(select(User).where(func.lower(User.email) == func.lower(email)))


def _email_key(email: str) -> str:
    """Rate-limit key: never the email itself (spec §6.5)."""
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _rate_limited(wait: dt.timedelta) -> ProblemError:
    seconds = max(1, math.ceil(wait.total_seconds()))
    minutes = math.ceil(seconds / 60)
    return ProblemError(
        429,
        "rate_limited",
        f"Too many failed sign-in attempts. Try again in {minutes} "
        f"minute{'s' if minutes != 1 else ''}.",
        headers={"Retry-After": str(seconds)},
    )
