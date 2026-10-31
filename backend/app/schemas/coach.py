"""Coach profile, search and link schemas (openapi.yaml, tag Coach)."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import Field

from app.models.coach import BIO_MAX
from app.schemas.base import RequestModel, ResponseModel
from app.schemas.users import UserRef

CoachLinkStatus = Literal["pending", "active", "declined", "ended"]


class CoachProfileInput(RequestModel):
    bio: Annotated[str, Field(max_length=BIO_MAX)]
    discoverable: bool = True


class CoachProfile(ResponseModel):
    user_id: uuid.UUID
    display_name: str
    bio: str
    discoverable: bool


class CoachSearchResult(ResponseModel):
    """Never contains the coach's email (F16.2)."""

    id: uuid.UUID
    display_name: str
    bio: str


class CoachSearchResultList(ResponseModel):
    items: Annotated[list[CoachSearchResult], Field(max_length=20)]


class CoachLinkRequest(RequestModel):
    coach_id: uuid.UUID


class CoachLink(ResponseModel):
    id: uuid.UUID
    status: CoachLinkStatus
    source: Literal["request"]
    coach: UserRef
    athlete: UserRef
    created_at: dt.datetime
    updated_at: dt.datetime


class CoachLinkList(ResponseModel):
    items: list[CoachLink]
