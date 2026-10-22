from app.schemas.base import ResponseModel


class FieldError(ResponseModel):
    """`FieldError` in openapi.yaml."""

    field: str
    code: str
    message: str


class Problem(ResponseModel):
    """RFC 9457 problem details, `Problem` in openapi.yaml."""

    type: str
    title: str
    status: int
    code: str
    detail: str | None = None
    errors: list[FieldError] | None = None
    request_id: str | None = None
