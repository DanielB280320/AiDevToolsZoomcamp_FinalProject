"""#41 Body tracking API (F14) against real Postgres: weigh-ins (201/200 replace, future date),
Navy body fat, the 2 % recalculation suggestion with accept/reject, authorization (owner /
coach / stranger) and no health values in telemetry."""

import datetime as dt
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import BodyMetric, Suggestion, Targets
from app.seed import run_seed
from tests.conftest import JsonLogs, captured_telemetry, make_settings
from tests.contract import assert_matches_schema
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api, field_errors, problem, signup_body
from tests.integration.test_onboarding import (
    ONBOARD,
    TARGETS,
    metric_body,
    onboarding,
    profile_body,
)

BM = "/api/v1/athletes/me/body-metrics"
SUGGESTIONS = "/api/v1/athletes/me/suggestions"
TODAY = "2026-10-22"  # NOW in Europe/Madrid
ONBOARD_WEIGHT = 72.5  # 2 % of it is 1.45 kg: 73.95 kg fires, 73.94 kg does not


@pytest.fixture
def athlete(api: Api) -> Api:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    r = api.client.post(ONBOARD, json=onboarding(metric=metric_body(weight_kg=ONBOARD_WEIGHT)))
    assert r.status_code == 201, r.text
    return api


def log(api: Api, **fields: Any) -> Any:
    fields.setdefault("date", TODAY)
    return api.client.post(BM, json=fields)


# ───────────── weigh-ins ─────────────


def test_new_date_is_201_and_same_date_replaces_with_200(athlete: Api) -> None:
    first = log(athlete, date="2026-10-20", weight_kg=72.0, waist_cm=80)
    assert first.status_code == 201, first.text
    assert_matches_schema(first.json(), "BodyMetricResult")
    assert first.json()["recalc_suggestion"] is None
    second = log(athlete, date="2026-10-20", weight_kg=72.4)
    assert second.status_code == 200, second.text
    assert_matches_schema(second.json(), "BodyMetricResult")
    body = second.json()["body_metric"]
    assert body["id"] == first.json()["body_metric"]["id"]
    assert body["weight_kg"] == 72.4
    assert body["waist_cm"] is None  # the entry is replaced, not merged
    with Session(athlete.app.state.engine) as db:
        rows = db.scalars(select(BodyMetric).where(BodyMetric.date == dt.date(2026, 10, 20))).all()
        assert len(rows) == 1
        assert rows[0].weight_kg == 72.4


def test_logging_today_replaces_the_onboarding_entry(athlete: Api) -> None:
    response = log(athlete, weight_kg=72.6)
    assert response.status_code == 200
    with Session(athlete.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(BodyMetric)) == 1


def test_future_date_is_422(athlete: Api) -> None:
    response = log(athlete, date="2026-10-23", weight_kg=72.0)
    assert field_errors(problem(response, 422, "validation_error")) == {("date", "future_date")}
    # "today" is the athlete's local day: 23:30 UTC on the 22nd is already the 23rd in Madrid
    athlete.clock.set(dt.datetime(2026, 10, 22, 23, 30, tzinfo=dt.UTC))
    assert log(athlete, date="2026-10-23", weight_kg=72.0).status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        {"date": TODAY},
        {"date": TODAY, "weight_kg": 34.9},
        {"date": TODAY, "weight_kg": 300.1},
        {"date": TODAY, "body_fat_pct": 2.9},
        {"date": TODAY, "neck_cm": 19},
        {"date": TODAY, "weight_kg": 70, "extra": 1},
        {"weight_kg": 70},
    ],
)
def test_invalid_bodies_are_422(athlete: Api, body: dict[str, Any]) -> None:
    problem(athlete.client.post(BM, json=body), 422, "validation_error")


def test_not_onboarded_is_404(api: Api) -> None:
    assert api.signup().status_code == 201
    problem(log(api, weight_kg=70), 404, "not_onboarded")


def test_list_range_oldest_first_and_default_window(athlete: Api) -> None:
    for day, kg in (("2026-10-20", 72.0), ("2026-10-18", 72.3), ("2026-07-01", 75.0)):
        assert log(athlete, date=day, weight_kg=kg).status_code == 201
    everything = athlete.client.get(BM, params={"from": "2026-01-01", "to": TODAY})
    assert [m["date"] for m in everything.json()["items"]] == [
        "2026-07-01",
        "2026-10-18",
        "2026-10-20",
        TODAY,
    ]
    default = athlete.client.get(BM)
    assert_matches_schema(default.json(), "BodyMetricList")
    assert [m["date"] for m in default.json()["items"]] == ["2026-10-18", "2026-10-20", TODAY]
    narrow = athlete.client.get(BM, params={"from": "2026-10-19", "to": "2026-10-20"})
    assert [m["date"] for m in narrow.json()["items"]] == ["2026-10-20"]
    problem(
        athlete.client.get(BM, params={"from": "2026-10-21", "to": "2026-10-20"}),
        400,
        "bad_request",
    )
    problem(athlete.client.get(BM, params={"from": "nope"}), 400, "bad_request")


# ───────────── Navy body fat (F3.3) ─────────────


def test_navy_estimate_for_female_needs_hip(athlete: Api) -> None:
    response = log(athlete, weight_kg=72.5, neck_cm=32, waist_cm=75, hip_cm=95)
    body = response.json()["body_metric"]
    assert body["body_fat_method"] == "navy"
    assert 3 <= body["body_fat_pct"] <= 60
    assert body["body_fat_explanation"]
    assert (body["neck_cm"], body["waist_cm"], body["hip_cm"]) == (32, 75, 95)
    no_hip = log(athlete, weight_kg=72.5, neck_cm=32, waist_cm=75).json()["body_metric"]
    assert no_hip["body_fat_pct"] is None and no_hip["body_fat_method"] is None
    assert no_hip["waist_cm"] == 75


def test_navy_for_male_without_hip_and_entered_value_wins(api: Api) -> None:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    r = api.client.post(ONBOARD, json=onboarding(profile=profile_body(sex="male", height_cm=180)))
    assert r.status_code == 201, r.text
    navy = log(api, weight_kg=80, neck_cm=38, waist_cm=85).json()["body_metric"]
    assert navy["body_fat_method"] == "navy"
    entered = log(api, weight_kg=80, body_fat_pct=18.5, neck_cm=38, waist_cm=85).json()
    assert entered["body_metric"]["body_fat_method"] == "entered"
    assert entered["body_metric"]["body_fat_pct"] == 18.5
    assert entered["body_metric"]["body_fat_explanation"] is None


def test_navy_out_of_range_is_ignored(athlete: Api) -> None:
    body = log(athlete, neck_cm=60, waist_cm=40, hip_cm=40).json()["body_metric"]
    assert body["body_fat_pct"] is None and body["body_fat_method"] is None


# ───────────── recalculation suggestion (F14) ─────────────


def test_boundary_1_9_percent_has_no_suggestion_and_2_percent_has(athlete: Api) -> None:
    below = log(athlete, weight_kg=73.94)  # +1.99 %
    assert below.json()["recalc_suggestion"] is None
    at = log(athlete, weight_kg=73.95)  # +2.00 %
    suggestion = at.json()["recalc_suggestion"]
    assert suggestion is not None
    assert_matches_schema(at.json(), "BodyMetricResult")
    assert suggestion["kind"] == "recalc" and suggestion["status"] == "pending"
    assert suggestion["rule"] == "weight_change"
    payload = suggestion["payload"]
    assert payload["weight_used_kg"] == ONBOARD_WEIGHT and payload["new_weight_kg"] == 73.95
    assert payload["change_pct"] == 2.0
    assert set(payload["current"]) == {"kcal", "protein_g", "carbs_g", "fat_g"}
    assert payload["proposed"] != payload["current"]
    assert suggestion["reason"]
    gain = athlete.client.get(SUGGESTIONS, params={"kind": "recalc"}).json()["items"]
    assert [s["id"] for s in gain] == [suggestion["id"]]


def test_weight_loss_of_two_percent_also_fires(athlete: Api) -> None:
    response = log(athlete, weight_kg=71.05)  # -2.00 %
    assert response.json()["recalc_suggestion"]["payload"]["change_pct"] == -2.0


def test_nonweight_entry_and_backdated_entry_create_nothing(athlete: Api) -> None:
    assert log(athlete, waist_cm=80).json()["recalc_suggestion"] is None
    assert log(athlete, weight_kg=80).json()["recalc_suggestion"] is not None
    # an older day is not the current weight
    old = log(athlete, date="2026-10-01", weight_kg=60.0)
    assert old.json()["recalc_suggestion"] is None


def test_new_weigh_in_replaces_the_pending_suggestion(athlete: Api) -> None:
    first = log(athlete, weight_kg=75.0).json()["recalc_suggestion"]
    second = log(athlete, weight_kg=76.0).json()["recalc_suggestion"]
    assert first["id"] != second["id"]
    pending = athlete.client.get(SUGGESTIONS, params={"kind": "recalc"}).json()["items"]
    assert [s["id"] for s in pending] == [second["id"]]
    # back within the threshold: the stale prompt goes away
    assert log(athlete, weight_kg=72.6).json()["recalc_suggestion"] is None
    assert athlete.client.get(SUGGESTIONS, params={"kind": "recalc"}).json()["items"] == []


def _targets(api: Api, day: str) -> dict[str, Any]:
    r = api.client.get(TARGETS, params={"date": day})
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


def test_accept_stores_targets_from_today_and_keeps_past_days(athlete: Api) -> None:
    old = _targets(athlete, TODAY)
    athlete.clock.set(dt.datetime(2026, 10, 25, 9, 0, tzinfo=dt.UTC))
    assert athlete.login().status_code == 200  # the session cookie was issued on the 22nd
    suggestion = log(athlete, date="2026-10-25", weight_kg=76.0).json()["recalc_suggestion"]
    accepted = athlete.client.post(f"/api/v1/suggestions/{suggestion['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    assert_matches_schema(accepted.json(), "Suggestion")
    assert accepted.json()["status"] == "accepted"
    new = _targets(athlete, "2026-10-25")
    assert new["weight_used_kg"] == 76.0
    assert {k: new[k] for k in ("kcal", "protein_g", "carbs_g", "fat_g")} == suggestion["payload"][
        "proposed"
    ]
    assert new["valid_from"] == "2026-10-25"
    assert _targets(athlete, "2026-10-24") == old  # past days unchanged
    assert _targets(athlete, TODAY) == old
    with Session(athlete.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(Targets)) == 2
    # a second weigh-in at the new weight no longer fires
    assert log(athlete, date="2026-10-25", weight_kg=76.1).json()["recalc_suggestion"] is None


def test_reject_leaves_targets_unchanged(athlete: Api) -> None:
    before = _targets(athlete, TODAY)
    suggestion = log(athlete, weight_kg=76.0).json()["recalc_suggestion"]
    rejected = athlete.client.post(f"/api/v1/suggestions/{suggestion['id']}/reject")
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert _targets(athlete, TODAY) == before


@pytest.mark.parametrize("first", ["accept", "reject"])
@pytest.mark.parametrize("second", ["accept", "reject"])
def test_cannot_be_decided_twice(athlete: Api, first: str, second: str) -> None:
    sid = log(athlete, weight_kg=76.0).json()["recalc_suggestion"]["id"]
    assert athlete.client.post(f"/api/v1/suggestions/{sid}/{first}").status_code == 200
    problem(
        athlete.client.post(f"/api/v1/suggestions/{sid}/{second}"),
        409,
        "suggestion_already_decided",
    )


def test_overrides_are_not_allowed_for_recalc(athlete: Api) -> None:
    sid = log(athlete, weight_kg=76.0).json()["recalc_suggestion"]["id"]
    r = athlete.client.post(f"/api/v1/suggestions/{sid}/accept", json={"overrides": {"kcal": 2000}})
    problem(r, 422, "invalid_overrides")
    with Session(athlete.app.state.engine) as db:
        assert db.scalars(select(Suggestion.status)).one() == "pending"


# ───────────── authorization: owner / coach / stranger ─────────────


def _other(api: Api, **overrides: Any) -> TestClient:
    client = api.new_client()
    assert client.post("/api/v1/auth/signup", json=signup_body(**overrides)).status_code == 201
    return client


def _my_id(api: Api) -> str:
    return str(api.client.get("/api/v1/me").json()["id"])


def test_unauthenticated_is_401(athlete: Api) -> None:
    anon = athlete.new_client()
    problem(anon.get(BM), 401, "not_authenticated")
    problem(anon.post(BM, json={"date": TODAY, "weight_kg": 70}), 401, "not_authenticated")


def test_owner_can_use_explicit_id(athlete: Api) -> None:
    url = f"/api/v1/athletes/{_my_id(athlete)}/body-metrics"
    assert athlete.client.get(url).status_code == 200
    assert athlete.client.post(url, json={"date": TODAY, "weight_kg": 72.5}).status_code == 200


def test_stranger_gets_403_on_get_and_post(athlete: Api) -> None:
    url = f"/api/v1/athletes/{_my_id(athlete)}/body-metrics"
    stranger = _other(athlete, email="bo@x.test", display_name="Bo")
    problem(stranger.get(url), 403, "not_linked")
    problem(stranger.post(url, json={"date": TODAY, "weight_kg": 70}), 403, "not_linked")
    with Session(athlete.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(BodyMetric)) == 1


def test_an_unlinked_coach_is_not_linked_on_get_post_and_me(athlete: Api) -> None:
    url = f"/api/v1/athletes/{_my_id(athlete)}/body-metrics"
    coach = _other(athlete, email="co@x.test", display_name="Co", role="coach")
    problem(coach.post(url, json={"date": TODAY, "weight_kg": 70}), 403, "not_linked")
    problem(coach.get(url), 403, "not_linked")
    own = "/api/v1/athletes/me/body-metrics"
    problem(coach.post(own, json={"date": TODAY, "weight_kg": 70}), 403, "wrong_role")
    problem(coach.get(own), 403, "not_linked")
    with Session(athlete.app.state.engine) as db:
        assert db.scalar(select(func.count()).select_from(BodyMetric)) == 1


def test_stranger_cannot_decide_a_recalc_suggestion(athlete: Api) -> None:
    sid = log(athlete, weight_kg=76.0).json()["recalc_suggestion"]["id"]
    stranger = _other(athlete, email="bo@x.test", display_name="Bo")
    problem(stranger.post(f"/api/v1/suggestions/{sid}/accept"), 403, "not_linked")
    problem(stranger.post(f"/api/v1/suggestions/{sid}/reject"), 403, "not_linked")


# ───────────── rule 6: no health values in telemetry ─────────────


def test_no_weights_in_logs_spans_or_metrics(
    migrated_database_url: str, json_logs: JsonLogs
) -> None:
    settings = make_settings(migrated_database_url)
    telemetry, exporter, reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    with TestClient(app) as client, Session(app.state.engine) as session:
        run_seed(session)
        assert client.post("/api/v1/auth/signup", json=signup_body()).status_code == 201
        assert client.post(ONBOARD, json=onboarding()).status_code == 201
        body = {
            "date": TODAY,
            "weight_kg": 74.37,
            "neck_cm": 36.41,
            "waist_cm": 83.29,
            "hip_cm": 97.53,
        }
        r = client.post(BM, json=body)
        sid = r.json()["recalc_suggestion"]["id"]
        assert client.post(f"/api/v1/suggestions/{sid}/accept").status_code == 200
        client.get(BM)
    blob = (
        json_logs.text
        + repr([(dict(s.attributes or {}), s.name) for s in exporter.get_finished_spans()])
        + repr(reader.get_metrics_data())
    )
    # Sentinels with a number-boundary match: a float such as `duration_ms=12.3456...` can contain
    # any short digit run, so a plain substring check was flaky (it must only match a whole number).
    for value in ("74.37", "36.41", "83.29", "97.53"):
        assert not re.search(rf"(?<![\d.]){re.escape(value)}(?!\d)", blob), value
