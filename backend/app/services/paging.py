"""Keyset pagination over `(lower(name), id)` shared by the catalog listings."""

import base64
import binascii
import json
import uuid

from app.errors import ProblemError
from app.schemas.base import contains_nul
from app.schemas.problem import FieldError


def encode_cursor(name: str, row_id: uuid.UUID) -> str:
    raw = json.dumps([name.lower(), str(row_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def bad_cursor() -> ProblemError:
    return ProblemError(
        400,
        "bad_request",
        "One or more parameters are invalid.",
        errors=[
            FieldError(field="cursor", code="invalid_format", message="The cursor is invalid.")
        ],
    )


def decode_cursor(cursor: str) -> tuple[str, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        name, row_id = json.loads(base64.urlsafe_b64decode(padded))
        if not isinstance(name, str) or contains_nul(name):
            raise bad_cursor()
        return name, uuid.UUID(str(row_id))
    except (binascii.Error, ValueError, TypeError):
        raise bad_cursor() from None


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
