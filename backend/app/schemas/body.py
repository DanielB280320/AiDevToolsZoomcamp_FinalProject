"""Body-metric request/response schemas (openapi.yaml tag Body)."""

import datetime as dt
from typing import Annotated

from pydantic import Field, model_validator

from app.schemas.athlete import BodyMetric
from app.schemas.base import RequestModel, ResponseModel
from app.schemas.suggestions import Suggestion

Measurement = Annotated[float, Field(ge=20, le=200)]


class BodyMetricInput(RequestModel):
    date: dt.date
    weight_kg: Annotated[float, Field(ge=35, le=300)] | None = None
    body_fat_pct: Annotated[float, Field(ge=3, le=60)] | None = None
    neck_cm: Measurement | None = None
    waist_cm: Measurement | None = None
    hip_cm: Measurement | None = None

    @model_validator(mode="after")
    def _something_to_log(self) -> "BodyMetricInput":
        if self.model_fields_set <= {"date"}:
            raise ValueError("log at least one of weight, body fat or measurements")
        return self


class BodyMetricList(ResponseModel):
    items: list[BodyMetric]


class BodyMetricResult(ResponseModel):
    body_metric: BodyMetric
    recalc_suggestion: Suggestion | None
