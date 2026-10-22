"""Account schemas: `SignUpRequest`, `LogInRequest`, `UpdateMeRequest`, `UserRef`, `Me`."""

import datetime as dt
import re
import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, Field, StringConstraints, field_validator, model_validator
from pydantic_core import PydanticCustomError

from app.schemas.base import RequestModel, ResponseModel
from app.services.clock import is_valid_timezone

Role = Literal["athlete", "coach"]
Units = Literal["metric", "imperial"]

# Deliberately simple: one `@`, no whitespace, a dot in the domain. Deliverability is not checked
# and reserved test domains (`x.test`) are accepted.
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _check_email(value: str) -> str:
    if not _EMAIL.fullmatch(value):
        # The message never echoes the value (spec §6.5).
        raise PydanticCustomError("invalid_format", "Enter a valid email address.")
    return value


def _check_timezone(value: str) -> str:
    if not is_valid_timezone(value):
        raise PydanticCustomError(
            "invalid_choice", "Use an IANA time zone name such as Europe/Madrid."
        )
    return value


Email = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=254), AfterValidator(_check_email)
]
Timezone = Annotated[
    str, StringConstraints(min_length=1, max_length=64), AfterValidator(_check_timezone)
]
DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]


class SignUpRequest(RequestModel):
    email: Email
    password: Annotated[str, Field(min_length=10, max_length=128)]
    display_name: DisplayName
    role: Role
    birth_date: dt.date
    units: Units
    timezone: Timezone
    accept_disclaimer: Annotated[bool, Field(strict=True)]


class LogInRequest(RequestModel):
    email: Email
    password: Annotated[str, Field(min_length=1, max_length=128)]


class UpdateMeRequest(RequestModel):
    """Partial update; at least one property (`minProperties: 1`), none of them `null`."""

    display_name: DisplayName | None = None
    units: Units | None = None
    timezone: Timezone | None = None

    @model_validator(mode="before")
    @classmethod
    def _at_least_one_field(cls, data: object) -> object:
        if isinstance(data, dict) and not data:
            raise PydanticCustomError("required", "Provide at least one field to update.")
        return data

    @field_validator("display_name", "units", "timezone", mode="before")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise PydanticCustomError("invalid_type", "Omit the field instead of sending null.")
        return value

    def changes(self) -> dict[str, str]:
        """Only the properties the client sent."""
        changed: dict[str, str] = self.model_dump(exclude_unset=True)
        return changed


class UserRef(ResponseModel):
    id: uuid.UUID
    display_name: str
    role: Role


class Me(ResponseModel):
    """`Me` = `User` + onboarding state, coach link and unread notification count."""

    id: uuid.UUID
    email: str
    display_name: str
    role: Role
    birth_date: dt.date
    units: Units
    timezone: str
    disclaimer_accepted_at: dt.datetime
    created_at: dt.datetime
    onboarding_completed: bool
    active_coach: UserRef | None
    pending_coach_link_id: uuid.UUID | None
    unread_notification_count: Annotated[int, Field(ge=0)]
