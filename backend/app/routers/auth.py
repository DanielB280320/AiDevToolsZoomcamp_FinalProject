"""`POST /auth/signup`, `/auth/login`, `/auth/logout` (openapi.yaml, tag Auth)."""

from fastapi import APIRouter, Response, status

from app.dependencies import SessionDep, SettingsDep
from app.schemas.problem import Problem
from app.schemas.users import LogInRequest, Me, SignUpRequest
from app.services import accounts
from app.services.clock import ClockDep
from app.services.sessions import cleared_session_cookie, issue_token, session_cookie

router = APIRouter(prefix="/auth", tags=["Auth"])

_PROBLEM = {"model": Problem}


def _start_session(response: Response, settings: SettingsDep, me: Me, clock: ClockDep) -> None:
    token = issue_token(me.id, clock.now(), settings.jwt_secret.get_secret_value())
    response.headers["Set-Cookie"] = session_cookie(token, secure=settings.session_cookie_secure)


@router.post(
    "/signup",
    operation_id="signUp",
    status_code=status.HTTP_201_CREATED,
    response_model=Me,
    responses={400: _PROBLEM, 409: _PROBLEM, 422: _PROBLEM, 429: _PROBLEM},
)
def sign_up(
    body: SignUpRequest,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> Me:
    """Create an account and start a session (F1.1-F1.4)."""
    me = accounts.me_view(accounts.sign_up(session, body, clock.now()))
    _start_session(response, settings, me, clock)
    return me


@router.post(
    "/login",
    operation_id="logIn",
    response_model=Me,
    responses={400: _PROBLEM, 401: _PROBLEM, 422: _PROBLEM, 429: _PROBLEM},
)
def log_in(
    body: LogInRequest,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> Me:
    """Sign in (F1.6 rate limit: 5 failures per email per 15 min)."""
    me = accounts.me_view(accounts.log_in(session, body.email, body.password, clock.now()))
    _start_session(response, settings, me, clock)
    return me


@router.post(
    "/logout",
    operation_id="logOut",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={400: _PROBLEM},
)
def log_out(settings: SettingsDep) -> Response:
    """Clear the session cookie. Idempotent; works without a session."""
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Set-Cookie": cleared_session_cookie(secure=settings.session_cookie_secure)},
    )
