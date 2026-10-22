"""Session JWTs and the `fitwise_session` cookie (spec F1, openapi.yaml `cookieAuth`).

The token holds only the user id (`sub`) and its issue/expiry times. Expiry is checked against
the app clock rather than the system time, so tests can move time forward.
"""

import datetime as dt
import uuid

import jwt

SESSION_COOKIE = "fitwise_session"
SESSION_TTL = dt.timedelta(hours=24)
_ALGORITHM = "HS256"
_COOKIE_ATTRIBUTES = "HttpOnly; SameSite=Lax; Path=/"


def issue_token(user_id: uuid.UUID, now: dt.datetime, secret: str) -> str:
    claims = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + SESSION_TTL).timestamp()),
    }
    return jwt.encode(claims, secret, algorithm=_ALGORITHM)


def read_token(token: str, now: dt.datetime, secret: str) -> uuid.UUID | None:
    """The user id of a valid, unexpired token; `None` for anything else."""
    try:
        claims = jwt.decode(
            token,
            secret,
            algorithms=[_ALGORITHM],
            options={
                "require": ["sub", "iat", "exp"],
                # Time claims are checked below against the app clock.
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
        )
        expires_at = int(claims["exp"])
        issued_at = int(claims["iat"])
        user_id = uuid.UUID(str(claims["sub"]))
    except (jwt.InvalidTokenError, ValueError, TypeError):
        return None
    timestamp = now.timestamp()
    if (
        not issued_at <= timestamp < expires_at
        or expires_at - issued_at > SESSION_TTL.total_seconds()
    ):
        return None
    return user_id


def session_cookie(token: str, *, secure: bool) -> str:
    """`Set-Cookie` value that starts a session (openapi.yaml `SetSessionCookie`)."""
    max_age = int(SESSION_TTL.total_seconds())
    return _with_secure(
        f"{SESSION_COOKIE}={token}; {_COOKIE_ATTRIBUTES}; Max-Age={max_age}", secure
    )


def cleared_session_cookie(*, secure: bool) -> str:
    """`Set-Cookie` value that ends a session (openapi.yaml `ClearSessionCookie`)."""
    return _with_secure(f"{SESSION_COOKIE}=; {_COOKIE_ATTRIBUTES}; Max-Age=0", secure)


def _with_secure(cookie: str, secure: bool) -> str:
    return f"{cookie}; Secure" if secure else cookie
