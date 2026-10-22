"""Shared RFC 9457 error handling (spec D40, openapi.yaml `Problem`). Every endpoint reuses it.

* Services raise `ProblemError` for expected failures (403 `not_linked`, 409 `email_taken`, ...).
* Request validation errors become 400 `bad_request` when the request line or envelope is
  invalid (query/path/header/cookie parameter, unparseable JSON) and 422 `validation_error` when
  a well-formed JSON body fails validation. Both list the offending fields in `errors[]`.
* Unknown routes and other framework HTTP errors keep their status with a stable `code`.
* Anything else becomes a bare 500 `internal_error`: no stack trace, exception message or request
  data reaches the client, and only the exception type is logged (spec §6.5).
"""

import logging
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.schemas.problem import FieldError, Problem

PROBLEM_MEDIA_TYPE = "application/problem+json"

logger = logging.getLogger(__name__)

# Stable codes for statuses raised by the framework itself (routing, method checks).
_STATUS_CODES: Mapping[int, str] = {
    400: "bad_request",
    401: "not_authenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    406: "not_acceptable",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    429: "rate_limited",
    500: "internal_error",
    503: "not_ready",
}

_DEFAULT_DETAILS: Mapping[str, str] = {
    "bad_request": "The request is invalid.",
    "not_found": "The requested resource was not found.",
    "method_not_allowed": "This method is not allowed for this resource.",
    "validation_error": "Some fields are invalid.",
    "internal_error": "Something went wrong on our side. Please try again later.",
}

# Pydantic error types -> `FieldError.code` values documented in openapi.yaml.
_FIELD_CODES: Mapping[str, str] = {
    "missing": "required",
    "extra_forbidden": "unknown_field",
    "greater_than": "out_of_range",
    "greater_than_equal": "out_of_range",
    "less_than": "out_of_range",
    "less_than_equal": "out_of_range",
    "string_too_short": "too_short",
    "too_short": "too_short",
    "string_too_long": "too_long",
    "too_long": "too_long",
    "literal_error": "invalid_choice",
    "enum": "invalid_choice",
    "string_pattern_mismatch": "invalid_format",
    "json_invalid": "invalid_json",
}

_PARAMETER_LOCATIONS = frozenset({"query", "path", "header", "cookie"})


class ProblemError(Exception):
    """Raise from services/routers to return a `Problem` with a stable `code`."""

    def __init__(
        self,
        status: int,
        code: str,
        detail: str | None = None,
        *,
        title: str | None = None,
        errors: Sequence[FieldError] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.detail = detail
        self.title = title
        self.errors = list(errors) if errors is not None else None
        self.headers = dict(headers) if headers is not None else None


def problem_response(
    status: int,
    code: str,
    detail: str | None = None,
    *,
    title: str | None = None,
    errors: Sequence[FieldError] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    problem = Problem(
        type=f"/problems/{code}",
        title=title or HTTPStatus(status).phrase,
        status=status,
        code=code,
        detail=detail if detail is not None else _DEFAULT_DETAILS.get(code),
        errors=list(errors) if errors is not None else None,
    )
    return JSONResponse(
        problem.model_dump(exclude_none=True),
        status_code=status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=dict(headers) if headers is not None else None,
    )


def _field_code(error_type: str) -> str:
    if error_type in _FIELD_CODES:
        return _FIELD_CODES[error_type]
    if error_type.endswith("_parsing"):
        return "invalid_format"
    if error_type.endswith("_type"):
        return "invalid_type"
    return error_type


def _field_path(loc: Sequence[Any]) -> str:
    parts = [str(part) for part in loc[1:]]
    return ".".join(parts) if parts else str(loc[0]) if loc else ""


def _field_error(error: Mapping[str, Any]) -> FieldError:
    # Only the location, type and message are used: `input` and `ctx` may echo user data.
    return FieldError(
        field=_field_path(error.get("loc", ())),
        code=_field_code(str(error.get("type", "invalid"))),
        message=str(error.get("msg", "Invalid value.")),
    )


def validation_problem(errors: Sequence[Mapping[str, Any]]) -> JSONResponse:
    """Map FastAPI/Pydantic request validation errors to 400 or 422 (spec D40)."""
    parameter_errors = [e for e in errors if e.get("loc", ("",))[0] in _PARAMETER_LOCATIONS]
    if parameter_errors:
        return problem_response(
            400,
            "bad_request",
            "One or more parameters are invalid.",
            errors=[_field_error(e) for e in parameter_errors],
        )
    if any(e.get("type") == "json_invalid" for e in errors):
        return problem_response(400, "bad_request", "The request body is not valid JSON.")
    return problem_response(422, "validation_error", errors=[_field_error(e) for e in errors])


async def _handle_problem_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ProblemError)  # noqa: S101 - registered for ProblemError only
    return problem_response(
        exc.status,
        exc.code,
        exc.detail,
        title=exc.title,
        errors=exc.errors,
        headers=exc.headers,
    )


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101 - registered for it only
    code = _STATUS_CODES.get(exc.status_code)
    if code is None:
        code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_").replace("-", "_")
    detail: str | None = exc.detail if isinstance(exc.detail, str) else None
    if detail == HTTPStatus(exc.status_code).phrase:
        detail = None  # framework default ("Not Found"): use our friendlier default text
    return problem_response(exc.status_code, code, detail, headers=exc.headers)


async def _handle_validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101 - registered for it only
    return validation_problem(exc.errors())


class UnhandledErrorMiddleware:
    """Turn any uncaught exception into a 500 `Problem` without leaking details.

    A plain ASGI middleware (not an `Exception` handler) so the exception is not re-raised to
    the server, which would log a traceback that may contain request data.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            if response_started:
                raise
            logger.error(
                "unhandled exception",
                extra={"error_type": type(exc).__name__, "http_method": scope.get("method")},
            )
            await problem_response(500, "internal_error")(scope, receive, send)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ProblemError, _handle_problem_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_middleware(UnhandledErrorMiddleware)
