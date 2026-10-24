from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, field_validator
from pydantic_core import PydanticCustomError


def reject_nul(value: str) -> str:
    """Reject U+0000: PostgreSQL text cannot hold it, so it would surface as a 500 (#102).

    The message never echoes the value (spec section 6.5).
    """
    if "\x00" in value:
        raise PydanticCustomError("invalid_format", "Remove the null character (U+0000).")
    return value


def contains_nul(value: str) -> bool:
    return "\x00" in value


# For query/path parameters: `Annotated[str | None, Query(...), NoNul]` (400 per D40).
NoNul = AfterValidator(reject_nul)
NoNulStr = Annotated[str, NoNul]


class RequestModel(BaseModel):
    """Base for every request body: unknown properties are rejected with 422 (openapi.yaml).

    Every string field of every subclass also rejects U+0000 (422 `validation_error` naming the
    field), so new endpoints get the check by default.
    """

    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def _no_nul_in_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            reject_nul(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    reject_nul(item)
        return value


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
