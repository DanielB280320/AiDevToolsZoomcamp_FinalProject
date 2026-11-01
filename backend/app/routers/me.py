"""`GET /me` and `PATCH /me` (openapi.yaml, tag Me)."""

from fastapi import APIRouter, Response, status

from app.dependencies import CurrentUser, SessionDep, SettingsDep
from app.schemas.problem import Problem
from app.schemas.users import DeleteAccountRequest, Me, UpdateMeRequest
from app.services import accounts, data_export
from app.services.clock import ClockDep, local_today
from app.services.sessions import cleared_session_cookie

router = APIRouter(prefix="/me", tags=["Me"])

_PROBLEM = {"model": Problem}


@router.get("", operation_id="getMe", response_model=Me, responses={401: _PROBLEM})
def get_me(user: CurrentUser, session: SessionDep) -> Me:
    return accounts.me_view(session, user)


@router.patch(
    "",
    operation_id="updateMe",
    response_model=Me,
    responses={400: _PROBLEM, 401: _PROBLEM, 422: _PROBLEM},
)
def update_me(body: UpdateMeRequest, user: CurrentUser, session: SessionDep, clock: ClockDep) -> Me:
    """Partial update of display name, units and time zone."""
    return accounts.me_view(session, accounts.update_me(session, user, body, clock.now()))


@router.post(
    "/delete",
    operation_id="deleteMe",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses={400: _PROBLEM, 401: _PROBLEM, 403: _PROBLEM, 422: _PROBLEM},
)
def delete_me(
    body: DeleteAccountRequest,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    clock: ClockDep,
) -> Response:
    """Delete the caller's account and all their data (F18, D48). Always the caller's own."""
    accounts.delete_account(session, user, body.password, clock.now())
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Set-Cookie": cleared_session_cookie(secure=settings.session_cookie_secure)},
    )


@router.get(
    "/export",
    operation_id="exportMyData",
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}, 401: _PROBLEM},
)
def export_my_data(user: CurrentUser, session: SessionDep, clock: ClockDep) -> Response:
    """The caller's own data as a ZIP (F18.1)."""
    day = local_today(clock.now(), user.timezone)
    return Response(
        content=data_export.build_zip(session, user),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="fitwise-export-{day}.zip"'},
    )
