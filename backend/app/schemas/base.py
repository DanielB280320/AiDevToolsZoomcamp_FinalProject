from pydantic import BaseModel, ConfigDict


class RequestModel(BaseModel):
    """Base for every request body: unknown properties are rejected with 422 (openapi.yaml)."""

    model_config = ConfigDict(extra="forbid")


class ResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
