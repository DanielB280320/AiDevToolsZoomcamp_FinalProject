"""QA additions for #25: the rollback when plan creation fails after its rows are flushed, the
NUL-byte error naming the field, and the athlete `onboarding_completed` flag."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AthleteProfile, BodyMetric, Plan, Targets, TrainingDay
from app.schemas.athlete import AthleteProfileInput, OnboardingBodyMetric, OnboardingRequest
from app.schemas.base import RequestModel
from app.services import plans as plans_service
from tests.integration.auth_helpers import Api, problem
from tests.integration.test_onboarding import (  # noqa: F401 - fixtures
    ME,
    NUL,
    ONBOARD,
    PROFILE,
    TARGETS,
    athlete,
    metric_body,
    onboarding,
    profile_body,
    seeded,
)


def _counts(api: Api) -> dict[str, int]:
    with Session(api.app.state.engine) as session:
        return {
            m.__tablename__: len(session.scalars(select(m)).all())
            for m in (AthleteProfile, BodyMetric, Targets, Plan, TrainingDay)
        }


def test_failure_after_plan_rows_are_flushed_rolls_back_everything(
    athlete: Api,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = plans_service.create_plan_version

    def flush_then_fail(session: Any, **kwargs: Any) -> Any:
        real(session, **kwargs)
        session.flush()  # plan, training_day and planned_exercise rows reach the database
        raise RuntimeError("fail after the plan insert")

    monkeypatch.setattr("app.services.athlete.create_plan_version", flush_then_fail)
    crashing = TestClient(athlete.app, raise_server_exceptions=False)
    crashing.cookies.update(athlete.client.cookies)

    problem(crashing.post(ONBOARD, json=onboarding()), 500, "internal_error")

    assert set(_counts(athlete).values()) == {0}
    problem(athlete.client.get(PROFILE), 404, "not_onboarded")
    problem(athlete.client.get(TARGETS), 404, "not_onboarded")


def test_request_models_use_the_shared_nul_validator() -> None:
    for model in (AthleteProfileInput, OnboardingBodyMetric, OnboardingRequest):
        assert issubclass(model, RequestModel)


def test_nul_byte_error_names_the_field(athlete: Api) -> None:  # noqa: F811
    body = onboarding(profile=profile_body(allergies=[f"nu{NUL}ts"]))
    errors = problem(athlete.client.post(ONBOARD, json=body), 422, "validation_error")["errors"]
    assert errors
    assert all(e["field"].startswith("profile.allergies") for e in errors)
    assert NUL not in repr(errors)  # the value is not echoed


def test_skip_with_measurements_stores_no_body_fat(athlete: Api) -> None:  # noqa: F811
    metric = metric_body(neck_cm=33, waist_cm=80, hip_cm=100)
    result = athlete.client.post(ONBOARD, json=onboarding(metric=metric)).json()
    assert result["body_metric"]["body_fat_pct"] is None
    assert result["targets"]["bmr_formula"] == "mifflin_st_jeor"


def test_onboarding_completed_flips_for_the_athlete(athlete: Api) -> None:  # noqa: F811
    assert athlete.client.get(ME).json()["onboarding_completed"] is False
    assert athlete.client.post(ONBOARD, json=onboarding()).status_code == 201
    assert athlete.client.get(ME).json()["onboarding_completed"] is True
