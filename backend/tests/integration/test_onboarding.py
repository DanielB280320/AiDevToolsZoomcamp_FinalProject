"""#25 onboarding, profile and targets against real Postgres: the single transaction, F13.2
planned kcal stored with the plan, Navy handling (F2.6, D55), D46 recompute, authorization
(owner / coach / stranger), the `engine.targets` span and a backward-compatible migration."""

import datetime as dt
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import (
    AthleteProfile,
    BodyMetric,
    Exercise,
    Plan,
    PlannedExercise,
    Targets,
    TrainingDay,
    User,
)
from app.seed import run_seed
from tests.conftest import captured_telemetry, make_settings
from tests.contract import assert_matches_schema
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api, field_errors, problem, signup_body

ONBOARD = "/api/v1/athletes/me/onboarding"
PROFILE = "/api/v1/athletes/me/profile"
TARGETS = "/api/v1/athletes/me/targets"
PLAN = "/api/v1/athletes/me/plan"
ME = "/api/v1/me"
NUL = "\x00"


def profile_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "sex": "female",
        "height_cm": 165,
        "lifestyle": "lightly_active",
        "goal": "cutting",
        "experience": "beginner",
        "days_per_week": 3,
        "preferred_days": ["mon", "wed", "fri"],
        "session_minutes": 45,
        "equipment": "home_dumbbells",
        "avoided_exercise_ids": [],
        "diet": "vegetarian",
        "allergies": ["nuts"],
        "meals_per_day": 4,
    }
    body.update(overrides)
    return body


def metric_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"weight_kg": 72.5, "body_fat_method": "skip"}
    body.update(overrides)
    return body


def onboarding(profile: dict[str, Any] | None = None, metric: dict[str, Any] | None = None) -> Any:
    return {"profile": profile or profile_body(), "body_metric": metric or metric_body()}


@pytest.fixture
def seeded(api: Api) -> Api:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    return api


@pytest.fixture
def athlete(seeded: Api) -> Api:
    assert seeded.signup().status_code == 201
    return seeded


def assert_profile_schema(profile: dict[str, Any]) -> None:
    assert_matches_schema(profile, "AthleteProfile")


def assert_onboarding_schema(result: dict[str, Any]) -> None:
    assert_matches_schema(result, "OnboardingResult")


def _counts(api: Api) -> dict[str, int]:
    with Session(api.app.state.engine) as session:
        return {
            model.__tablename__: len(session.scalars(select(model)).all())
            for model in (AthleteProfile, BodyMetric, Targets, Plan)
        }


def _days_later(api: Api, days: int) -> None:
    """Move the clock on; sessions last 24 h, so sign in again."""
    api.clock.advance(days=days)
    assert api.login().status_code == 200


def _signup_other(api: Api, email: str, role: str = "athlete") -> TestClient:
    browser = api.new_client()
    response = browser.post(
        "/api/v1/auth/signup", json=signup_body(email=email, display_name="Other", role=role)
    )
    assert response.status_code == 201
    return browser


# ───────────── happy path, F2.1, F2.5, GET /me ─────────────


def test_onboarding_creates_profile_metric_targets_and_plan_v1(athlete: Api) -> None:
    assert athlete.client.get(ME).json()["onboarding_completed"] is False

    response = athlete.client.post(ONBOARD, json=onboarding())

    assert response.status_code == 201, response.text
    result = response.json()
    assert_onboarding_schema(result)
    assert result["profile"]["sex"] == "female"
    assert result["body_metric"]["weight_kg"] == 72.5
    assert result["body_metric"]["body_fat_pct"] is None
    assert result["targets"]["bmr_formula"] == "mifflin_st_jeor"
    assert result["plan"]["version"] == 1
    assert result["plan"]["source"] == "generated"
    assert len(result["plan"]["training_days"]) == 3
    assert [d["weekday"] for d in result["plan"]["training_days"]] == ["mon", "wed", "fri"]
    # The follow-up reads return the same data.
    assert athlete.client.get(TARGETS).json() == result["targets"]
    assert athlete.client.get(PLAN).json() == result["plan"]
    profile = athlete.client.get(PROFILE).json()
    assert_profile_schema(profile)
    assert profile == result["profile"]
    assert athlete.client.get(ME).json()["onboarding_completed"] is True
    assert _counts(athlete) == {"athlete_profile": 1, "body_metric": 1, "targets": 1, "plan": 1}


def test_body_metric_is_dated_today_in_the_athletes_time_zone(athlete: Api) -> None:
    # 23:30 UTC on 22 Oct is already 23 Oct in Europe/Madrid (UTC+2).
    athlete.clock.set(dt.datetime(2026, 10, 22, 23, 30, tzinfo=dt.UTC))

    result = athlete.client.post(ONBOARD, json=onboarding()).json()

    assert result["body_metric"]["date"] == "2026-10-23"
    assert result["targets"]["valid_from"] == "2026-10-23"
    assert athlete.client.get(TARGETS).json()["valid_from"] == "2026-10-23"


def test_values_are_stored_in_metric_for_an_imperial_user(seeded: Api) -> None:
    assert seeded.signup(units="imperial").status_code == 201

    assert seeded.client.post(ONBOARD, json=onboarding()).status_code == 201

    with Session(seeded.app.state.engine) as session:
        assert session.scalars(select(AthleteProfile.height_cm)).one() == 165
        assert session.scalars(select(BodyMetric.weight_kg)).one() == 72.5
    assert seeded.client.get(ME).json()["units"] == "imperial"


def test_second_onboarding_is_409_and_changes_nothing(athlete: Api) -> None:
    assert athlete.client.post(ONBOARD, json=onboarding()).status_code == 201
    before = _counts(athlete)

    problem(athlete.client.post(ONBOARD, json=onboarding()), 409, "already_onboarded")

    assert _counts(athlete) == before


def test_reads_before_onboarding_are_404_not_onboarded(athlete: Api) -> None:
    problem(athlete.client.get(PROFILE), 404, "not_onboarded")
    problem(athlete.client.get(TARGETS), 404, "not_onboarded")
    problem(athlete.client.get(PLAN), 404, "not_onboarded")
    problem(athlete.client.put(PROFILE, json=profile_body()), 404, "not_onboarded")


def test_coach_accounts_report_onboarding_completed(seeded: Api) -> None:
    assert seeded.signup(role="coach").status_code == 201
    assert seeded.client.get(ME).json()["onboarding_completed"] is True


# ───────────── single transaction ─────────────


def test_a_failure_in_plan_creation_leaves_no_profile_metric_or_targets(
    athlete: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("plan store down")

    monkeypatch.setattr("app.services.athlete.create_plan_version", failing)
    crashing = TestClient(athlete.app, raise_server_exceptions=False)
    crashing.cookies.update(athlete.client.cookies)

    response = crashing.post(ONBOARD, json=onboarding())

    problem(response, 500, "internal_error")
    assert _counts(athlete) == {"athlete_profile": 0, "body_metric": 0, "targets": 0, "plan": 0}
    assert athlete.client.get(ME).json()["onboarding_completed"] is False
    monkeypatch.undo()
    assert athlete.client.post(ONBOARD, json=onboarding()).status_code == 201


# ───────────── F13.2 planned kcal stored with the plan ─────────────


def _expected_kcal(exercise: Exercise, planned: PlannedExercise, weight: float) -> float:
    """MET x 3.5 x kg / 200 x minutes, written out independently of the engine."""
    if exercise.type == "timed":
        minutes = planned.sets * (planned.target_seconds or 0) / 60
    else:
        minutes = planned.sets * (planned.rest_seconds + 45) / 60
    return float(exercise.met) * 3.5 * weight / 200 * minutes


def _half_up(value: float) -> int:
    return int(value + 0.5)


def test_plan_stores_planned_kcal_per_exercise_and_day_from_the_new_weight(athlete: Api) -> None:
    weight = 80.0
    result = athlete.client.post(
        ONBOARD, json=onboarding(metric=metric_body(weight_kg=weight))
    ).json()

    with Session(athlete.app.state.engine) as session:
        days = session.scalars(select(TrainingDay)).all()
        assert days
        weekly_exact = 0.0
        for day in days:
            day_exact = 0.0
            for planned in day.exercises:
                exercise = session.get(Exercise, planned.exercise_id)
                assert exercise is not None
                exact = _expected_kcal(exercise, planned, weight)
                assert planned.planned_kcal == _half_up(exact), exercise.name
                assert planned.planned_kcal > 0
                day_exact += exact
            assert day.planned_kcal == _half_up(day_exact)
            weekly_exact += day_exact
    assert [d["planned_kcal"] for d in result["plan"]["training_days"]] == [
        d.planned_kcal for d in sorted(days, key=lambda d: ["mon", "wed", "fri"].index(d.weekday))
    ]
    # F3.4: the targets use the same planned weekly kcal / 7.
    assert result["targets"]["planned_exercise_kcal_per_day"] == _half_up(weekly_exact / 7)
    assert athlete.client.get(PLAN).json()["training_days"][0]["planned_kcal"] > 0


def test_planned_kcal_scales_with_the_entered_weight(athlete: Api) -> None:
    light = athlete.client.post(ONBOARD, json=onboarding(metric=metric_body(weight_kg=50))).json()
    other = _signup_other(athlete, "heavy@x.test")
    heavy = other.post(ONBOARD, json=onboarding(metric=metric_body(weight_kg=100))).json()

    light_total = sum(d["planned_kcal"] for d in light["plan"]["training_days"])
    heavy_total = sum(d["planned_kcal"] for d in heavy["plan"]["training_days"])
    assert heavy_total == pytest.approx(light_total * 2, abs=3)


# ───────────── telemetry ─────────────


class _Recorder(SpanProcessor):
    """Sees spans before the exporter's allow-list filter, so the test checks what the code set."""

    def __init__(self) -> None:
        self.spans: list[ReadableSpan] = []

    def on_end(self, span: ReadableSpan) -> None:
        self.spans.append(span)


def test_engine_targets_span_carries_no_body_metrics(
    migrated_database_url: str,
) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, exporter, _ = captured_telemetry(settings)
    raw = _Recorder()
    telemetry.tracer_provider.add_span_processor(raw)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    with TestClient(app) as client, Session(app.state.engine) as session:
        run_seed(session)
        assert client.post("/api/v1/auth/signup", json=signup_body()).status_code == 201
        body = onboarding(metric=metric_body(weight_kg=73.37, body_fat_method="entered"))
        body["body_metric"]["body_fat_pct"] = 21.77
        body["profile"]["height_cm"] = 171.5
        assert client.post(ONBOARD, json=body).status_code == 201

    for spans in (raw.spans, exporter.get_finished_spans()):
        engine_spans = [s for s in spans if s.name == "engine.targets"]
        assert len(engine_spans) == 1
        attributes = dict(engine_spans[0].attributes or {})
        assert attributes == {}  # no weight, height, body fat, age, sex, goal or kcal
        assert not any(str(v) for v in attributes.values())
    server = [s for s in exporter.get_finished_spans() if "athletes" in s.name]
    assert server
    blob = repr([(dict(s.attributes or {}), s.name) for s in exporter.get_finished_spans()])
    for secret in ("73.37", "21.77", "171.5"):
        assert secret not in blob


# ───────────── F2.3, F2.4, NUL bytes ─────────────


@pytest.mark.parametrize(
    ("where", "field", "value"),
    [
        ("profile", "height_cm", 119.9),
        ("profile", "height_cm", 230.1),
        ("body_metric", "weight_kg", 34.9),
        ("body_metric", "weight_kg", 300.1),
        ("body_metric", "body_fat_pct", 2.9),
        ("body_metric", "body_fat_pct", 60.1),
        ("body_metric", "neck_cm", 19.9),
        ("body_metric", "waist_cm", 200.1),
        ("body_metric", "hip_cm", 19.9),
    ],
)
def test_implausible_values_are_422_with_field_errors(
    athlete: Api, where: str, field: str, value: float
) -> None:
    body = onboarding(metric=metric_body(body_fat_method="entered", body_fat_pct=20))
    body[where][field] = value

    response = athlete.client.post(ONBOARD, json=body)

    assert field_errors(problem(response, 422, "validation_error")) == {
        (f"{where}.{field}", "out_of_range")
    }
    assert _counts(athlete)["athlete_profile"] == 0


def test_boundary_values_are_accepted(athlete: Api) -> None:
    body = onboarding(
        profile=profile_body(height_cm=120),
        metric=metric_body(weight_kg=35, body_fat_method="entered", body_fat_pct=3),
    )
    assert athlete.client.post(ONBOARD, json=body).status_code == 201


def test_preferred_days_must_match_days_per_week(athlete: Api) -> None:
    body = onboarding(profile=profile_body(days_per_week=3, preferred_days=["mon", "wed"]))

    errors = field_errors(problem(athlete.client.post(ONBOARD, json=body), 422, "validation_error"))

    assert [f for f, _ in errors] == ["profile.preferred_days"]
    duplicate = onboarding(profile=profile_body(preferred_days=["mon", "mon", "fri"]))
    problem(athlete.client.post(ONBOARD, json=duplicate), 422, "validation_error")
    problem(
        athlete.client.put(PROFILE, json=profile_body(preferred_days=["mon"])),
        422,
        "validation_error",
    )


def test_body_fat_method_needs_its_inputs(athlete: Api) -> None:
    entered = onboarding(metric=metric_body(body_fat_method="entered"))
    assert field_errors(
        problem(athlete.client.post(ONBOARD, json=entered), 422, "validation_error")
    ) == {("body_metric.body_fat_pct", "required")}
    navy_female = onboarding(metric=metric_body(body_fat_method="navy", neck_cm=33, waist_cm=80))
    assert field_errors(
        problem(athlete.client.post(ONBOARD, json=navy_female), 422, "validation_error")
    ) == {("body_metric.hip_cm", "required")}
    skip_with_fat = onboarding(metric=metric_body(body_fat_pct=20))
    assert field_errors(
        problem(athlete.client.post(ONBOARD, json=skip_with_fat), 422, "validation_error")
    ) == {("body_metric.body_fat_pct", "not_allowed")}
    assert _counts(athlete)["athlete_profile"] == 0


def test_unknown_avoided_exercise_is_422(athlete: Api) -> None:
    body = onboarding(profile=profile_body(avoided_exercise_ids=[str(uuid.uuid4())]))
    assert field_errors(
        problem(athlete.client.post(ONBOARD, json=body), 422, "validation_error")
    ) == {("profile.avoided_exercise_ids", "invalid_choice")}


def test_nul_bytes_in_request_strings_are_422(athlete: Api) -> None:
    body = onboarding(profile=profile_body(sex=f"fe{NUL}male"))
    problem(athlete.client.post(ONBOARD, json=body), 422, "validation_error")
    body = onboarding(profile=profile_body(allergies=[f"nu{NUL}ts"]))
    problem(athlete.client.post(ONBOARD, json=body), 422, "validation_error")
    problem(
        athlete.client.put(PROFILE, json=profile_body(diet=f"vegan{NUL}")), 422, "validation_error"
    )
    assert _counts(athlete)["athlete_profile"] == 0


def test_unknown_properties_are_422(athlete: Api) -> None:
    body = onboarding()
    body["profile"]["shoe_size"] = 40
    problem(athlete.client.post(ONBOARD, json=body), 422, "validation_error")


# ───────────── Navy (F2.6, D55) ─────────────


def test_navy_in_range_stores_the_estimate_and_uses_katch_mcardle(athlete: Api) -> None:
    metric = metric_body(body_fat_method="navy", neck_cm=33, waist_cm=80, hip_cm=102)

    result = athlete.client.post(ONBOARD, json=onboarding(metric=metric)).json()

    stored = result["body_metric"]
    assert stored["body_fat_method"] == "navy"
    assert 3 <= stored["body_fat_pct"] <= 60
    assert stored["body_fat_explanation"]
    assert (stored["neck_cm"], stored["waist_cm"], stored["hip_cm"]) == (33, 80, 102)
    assert result["targets"]["bmr_formula"] == "katch_mcardle"
    assert result["targets"]["body_fat_pct_used"] == stored["body_fat_pct"]


def test_navy_result_above_60_is_ignored_and_targets_use_mifflin(athlete: Api) -> None:
    # Plausible tape values (each 20-200 cm) that the Navy formula turns into more than 60 %.
    profile = profile_body(height_cm=150)
    metric = metric_body(body_fat_method="navy", neck_cm=20, waist_cm=190, hip_cm=190)

    response = athlete.client.post(ONBOARD, json=onboarding(profile, metric))

    assert response.status_code == 201, response.text
    result = response.json()
    stored = result["body_metric"]
    assert (stored["body_fat_pct"], stored["body_fat_method"]) == (None, None)
    assert stored["waist_cm"] == 190
    targets = result["targets"]
    assert targets["bmr_formula"] == "mifflin_st_jeor"
    assert targets["body_fat_pct_used"] is None
    assert "out of range" in targets["explanation"]
    assert "ignored" in targets["explanation"]
    assert "Mifflin-St Jeor" in targets["explanation"]
    assert athlete.client.get(TARGETS).json()["explanation"] == targets["explanation"]
    assert athlete.client.get(ME).json()["onboarding_completed"] is True


def test_navy_result_below_3_or_undefined_is_ignored_too(athlete: Api, seeded: Api) -> None:
    male = profile_body(sex="male", height_cm=175)
    below = metric_body(body_fat_method="navy", neck_cm=38, waist_cm=40)
    result = athlete.client.post(ONBOARD, json=onboarding(male, below)).json()
    assert result["body_metric"]["body_fat_pct"] is None
    assert result["targets"]["bmr_formula"] == "mifflin_st_jeor"
    assert "ignored" in result["targets"]["explanation"]

    other = _signup_other(seeded, "undefined@x.test")
    undefined = metric_body(body_fat_method="navy", neck_cm=50, waist_cm=40)
    second = other.post(ONBOARD, json=onboarding(male, undefined))
    assert second.status_code == 201
    assert second.json()["targets"]["bmr_formula"] == "mifflin_st_jeor"
    assert "ignored" in second.json()["targets"]["explanation"]


# ───────────── profile GET / PUT (D46) ─────────────


def test_put_recomputes_targets_from_today_and_keeps_earlier_rows(athlete: Api) -> None:
    first = athlete.client.post(ONBOARD, json=onboarding()).json()["targets"]
    _days_later(athlete, 3)

    response = athlete.client.put(PROFILE, json=profile_body(goal="muscle_gain"))

    assert response.status_code == 200, response.text
    update = response.json()
    assert_profile_schema(update["profile"])
    assert_matches_schema(update["targets"], "Targets")
    assert update["targets_changed"] is True
    assert update["profile"]["goal"] == "muscle_gain"
    assert update["targets"]["valid_from"] == "2026-10-25"
    assert update["targets"]["kcal"] > first["kcal"]
    assert (
        update["targets"]["planned_exercise_kcal_per_day"] == first["planned_exercise_kcal_per_day"]
    )
    with Session(athlete.app.state.engine) as session:
        rows = session.scalars(select(Targets).order_by(Targets.valid_from)).all()
        assert [r.valid_from.isoformat() for r in rows] == ["2026-10-22", "2026-10-25"]
        assert rows[0].kcal == first["kcal"]
    assert athlete.client.get(TARGETS).json() == update["targets"]
    assert athlete.client.get(TARGETS, params={"date": "2026-10-23"}).json() == first
    assert athlete.client.get(TARGETS, params={"date": "2026-10-25"}).json() == update["targets"]
    assert athlete.client.get(TARGETS, params={"date": "2026-01-01"}).json() == first
    problem(athlete.client.get(TARGETS, params={"date": "not-a-date"}), 400, "bad_request")


def test_put_on_the_same_day_replaces_that_days_row(athlete: Api) -> None:
    athlete.client.post(ONBOARD, json=onboarding())

    update = athlete.client.put(PROFILE, json=profile_body(lifestyle="active")).json()

    assert update["targets_changed"] is True
    with Session(athlete.app.state.engine) as session:
        assert len(session.scalars(select(Targets)).all()) == 1
    assert update["targets"]["lifestyle_factor"] == 1.45


def test_put_without_a_target_relevant_change_keeps_targets(athlete: Api) -> None:
    first = athlete.client.post(ONBOARD, json=onboarding()).json()["targets"]
    _days_later(athlete, 1)

    resp = athlete.client.put(PROFILE, json=profile_body(diet="vegan", meals_per_day=5))
    update = resp.json()

    assert update["targets_changed"] is False
    assert update["targets"] == first
    assert update["profile"]["diet"] == "vegan"
    with Session(athlete.app.state.engine) as session:
        assert len(session.scalars(select(Targets)).all()) == 1


def test_put_uses_the_latest_weight_and_does_not_regenerate_the_plan(athlete: Api) -> None:
    athlete.client.post(ONBOARD, json=onboarding())
    _days_later(athlete, 1)
    with Session(athlete.app.state.engine) as session:
        uid = session.scalars(select(User.id)).one()
        session.add(
            BodyMetric(
                user_id=uid,
                date=dt.date(2026, 10, 23),
                weight_kg=70,
                created_at=athlete.clock.now(),
            )
        )
        session.commit()

    update = athlete.client.put(PROFILE, json=profile_body(goal="maintenance")).json()

    assert update["targets"]["weight_used_kg"] == 70
    with Session(athlete.app.state.engine) as session:
        # D74: the new targets rescale meal portions as plan version 2; the training days are
        # carried over unchanged (never regenerated)
        plans = session.scalars(select(Plan).order_by(Plan.version)).all()
        assert [p.version for p in plans] == [1, 2]
        old, new = plans
        assert [
            (d.weekday, d.name, [e.exercise_id for e in d.exercises]) for d in old.training_days
        ] == [(d.weekday, d.name, [e.exercise_id for e in d.exercises]) for d in new.training_days]


def test_put_with_unknown_avoided_exercise_is_422(athlete: Api) -> None:
    athlete.client.post(ONBOARD, json=onboarding())
    body = profile_body(avoided_exercise_ids=[str(uuid.uuid4())])
    assert field_errors(
        problem(athlete.client.put(PROFILE, json=body), 422, "validation_error")
    ) == {("avoided_exercise_ids", "invalid_choice")}


# ───────────── authorization: owner / coach / stranger ─────────────


@pytest.fixture
def onboarded(athlete: Api) -> Api:
    assert athlete.client.post(ONBOARD, json=onboarding()).status_code == 201
    return athlete


def _athlete_id(api: Api) -> str:
    return str(api.client.get(ME).json()["id"])


def test_another_athletes_id_is_403_on_every_operation(onboarded: Api) -> None:
    victim = _athlete_id(onboarded)
    stranger = _signup_other(onboarded, "stranger@x.test")
    base = f"/api/v1/athletes/{victim}"

    for response in (
        stranger.get(f"{base}/profile"),
        stranger.get(f"{base}/targets"),
        stranger.get(f"{base}/plan"),
        stranger.put(f"{base}/profile", json=profile_body()),
        stranger.post(f"{base}/onboarding", json=onboarding()),
    ):
        problem(response, 403, "not_linked")
    # The victim's data is untouched.
    assert onboarded.client.get(PROFILE).json()["goal"] == "cutting"


def test_unknown_athlete_id_is_403_not_404_and_malformed_is_400(onboarded: Api) -> None:
    problem(onboarded.client.get(f"/api/v1/athletes/{uuid.uuid4()}/profile"), 403, "not_linked")
    problem(onboarded.client.get("/api/v1/athletes/not-a-uuid/profile"), 400, "bad_request")


def test_coach_cannot_put_or_onboard_and_has_no_profile_of_their_own(onboarded: Api) -> None:
    victim = _athlete_id(onboarded)
    coach = _signup_other(onboarded, "coach@x.test", role="coach")

    problem(coach.put(f"/api/v1/athletes/{victim}/profile", json=profile_body()), 403, "not_linked")
    problem(coach.get(f"/api/v1/athletes/{victim}/profile"), 403, "not_linked")  # no link yet (#47)
    problem(coach.put(PROFILE, json=profile_body()), 403, "wrong_role")
    problem(coach.post(ONBOARD, json=onboarding()), 403, "wrong_role")
    problem(coach.get(PROFILE), 404, "not_onboarded")
    assert onboarded.client.get(PROFILE).json()["goal"] == "cutting"


def test_requests_without_a_session_are_401(onboarded: Api) -> None:
    anonymous = onboarded.new_client()
    for response in (
        anonymous.get(PROFILE),
        anonymous.get(TARGETS),
        anonymous.put(PROFILE, json=profile_body()),
        anonymous.post(ONBOARD, json=onboarding()),
    ):
        problem(response, 401, "not_authenticated")


# ───────────── migration: backward compatible ─────────────


def test_previous_release_can_still_insert_plan_rows_without_planned_kcal(athlete: Api) -> None:
    """Expand-only (D50): the new `planned_kcal` columns default to 0, so a release that does
    not know them (a rollback) inserts plan rows unchanged."""
    athlete.client.post(ONBOARD, json=onboarding())
    with Session(athlete.app.state.engine) as session:
        uid = session.scalars(select(User.id)).one()
        plan_id = uuid.uuid4()
        day_id = uuid.uuid4()
        session.execute(
            text(
                "INSERT INTO plan (id, athlete_id, version, source, active, revision, created_by,"
                " created_at, updated_at) VALUES (:p, :u, 2, 'custom', false, 0, :u, now(), now())"
            ),
            {"p": plan_id, "u": uid},
        )
        session.execute(
            text(
                'INSERT INTO training_day (id, plan_id, weekday, name, "order")'
                " VALUES (:d, :p, 'mon', 'Old release', 0)"
            ),
            {"d": day_id, "p": plan_id},
        )
        session.commit()
        assert (
            session.scalars(select(TrainingDay.planned_kcal).where(TrainingDay.id == day_id)).one()
            == 0
        )


def test_onboarding_writes_no_health_data_to_logs(athlete: Api, json_logs: Any) -> None:
    body = onboarding(metric=metric_body(weight_kg=73.37, body_fat_method="entered"))
    body["body_metric"]["body_fat_pct"] = 21.77
    body["profile"]["height_cm"] = 171.5
    assert athlete.client.post(ONBOARD, json=body).status_code == 201
    athlete.client.put(PROFILE, json=profile_body(goal="muscle_gain"))
    athlete.client.post(ONBOARD, json=body)  # 409

    for secret in ("73.37", "21.77", "171.5", "vegetarian", "nuts", "cutting"):
        assert secret not in json_logs.text
