"""Reusable FastAPI dependencies for authentication and role checks (spec F1.5).

* `CurrentUser` -> the signed-in `User`, or 401 `not_authenticated` for a missing, tampered or
  expired session (or a user that no longer exists). It also binds the user to the request's
  telemetry as `user_hash`.
* `Depends(require_role("coach"))` -> 403 `wrong_role` for users with another role.
"""

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import get_session
from app.errors import ProblemError
from app.models import User
from app.schemas.users import Role
from app.services.clock import ClockDep
from app.services.sessions import SESSION_COOKIE, read_token
from app.telemetry import bind_user

SessionDep = Annotated[Session, Depends(get_session)]

# Named like the contract's security scheme so the generated OpenAPI matches openapi.yaml.
_session_cookie = APIKeyCookie(name=SESSION_COOKIE, scheme_name="cookieAuth", auto_error=False)


def get_settings_from_app(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


SettingsDep = Annotated[Settings, Depends(get_settings_from_app)]


def _not_authenticated() -> ProblemError:
    return ProblemError(401, "not_authenticated", "Sign in to continue.")


def current_user(
    token: Annotated[str | None, Depends(_session_cookie)],
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> User:
    if not token:
        raise _not_authenticated()
    user_id = read_token(token, clock.now(), settings.jwt_secret.get_secret_value())
    if user_id is None:
        raise _not_authenticated()
    user = session.get(User, user_id)
    if user is None:
        raise _not_authenticated()
    bind_user(user.id)  # logs and the server span of this request carry user_hash, never the id
    return user


CurrentUser = Annotated[User, Depends(current_user)]


def require_role(role: Role) -> Callable[[User], User]:
    """Dependency factory: the signed-in user if they have `role`, else 403 `wrong_role`."""

    def dependency(user: CurrentUser) -> User:
        if user.role != role:
            raise ProblemError(403, "wrong_role", f"Only {role}s can do this.")
        return user

    return dependency
