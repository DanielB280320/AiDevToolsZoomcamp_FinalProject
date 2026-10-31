"""#42 F14 weekly adaptive calorie suggestion: job, list hint, accept (D74), authorization."""

import datetime as dt
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import BodyMetric, Suggestion, Targets, User
from app.services import adaptive_calories, clock
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import NOW, Api, problem, signup_body
from tests.integration.test_rescale_portions import (
    ME,
    TODAY,
    _rescale_check,
    _target_kcal,
    _versions,
    athlete,  # noqa: F401 - fixture
)

SUGGESTIONS = f"{ME}/suggestions"
MONDAY = dt.date(2026, 10, 19)  # the week of NOW (Thursday 2026-10-22)
WEEK1 = MONDAY - dt.timedelta(days=14)  # 2026-10-05
WEEK2 = MONDAY - dt.timedelta(days=7)


def weigh(api: Api, days: list[dt.date], kg: float = 72.5) -> None:
    with Session(api.app.state.engine) as db:
        uid = db.scalars(select(User.id)).one()
        db.execute(delete(BodyMetric).where(BodyMetric.user_id == uid))
        db.add_all(BodyMetric(user_id=uid, date=d, weight_kg=kg, created_at=NOW) for d in days)
        db.commit()


def every_day(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def run_job(api: Api) -> int:
    with Session(api.app.state.engine) as db:
        return adaptive_calories.run_weekly(db, NOW)


def listing(api: Api, **params: str) -> dict[str, Any]:
    r = api.client.get(SUGGESTIONS, params=params)
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    assert_matches_schema(body, "SuggestionList")
    return body


def flat_weeks(api: Api) -> None:
    """A flat weight for three weeks: a cutting athlete is losing too slowly."""
    weigh(api, every_day(WEEK1 - dt.timedelta(days=6), MONDAY - dt.timedelta(days=1)))


def test_slow_cut_creates_a_pending_minus_150_suggestion(athlete: Api) -> None:  # noqa: F811
    flat_weeks(athlete)
    current = _target_kcal(athlete)
    assert run_job(athlete) == 1
    body = listing(athlete, kind="calories")
    assert body["weigh_in_hint"] is None
    (item,) = body["items"]
    assert_matches_schema(item, "Suggestion")
    assert item["status"] == "pending" and item["rule"] == "adaptive_calories"
    payload = item["payload"]
    assert payload["current_kcal"] == current
    assert payload["proposed_kcal"] == current - 150
    assert payload["delta_kcal"] == -150
    assert payload["expected_weekly_change_pct"] == -0.75
    assert payload["tolerance_pct"] == 0.25
    assert payload["observed_weekly_change_pct"] == [0.0, 0.0]
    assert payload["applied_kcal"] is None and payload["floor_applied"] is False
    assert "150" in item["reason"]
    assert item["inputs"]["evaluated_on"] == "2026-10-19"


def test_job_is_idempotent_within_a_week(athlete: Api) -> None:  # noqa: F811
    flat_weeks(athlete)
    assert run_job(athlete) == 1
    assert run_job(athlete) == 0
    assert len(listing(athlete, kind="calories")["items"]) == 1


def test_on_track_athlete_gets_nothing(athlete: Api) -> None:  # noqa: F811
    # losing 0.75 % a week: 72.5 -> 71.96 -> 71.42 -> 70.88, one weigh-in per day
    days = every_day(WEEK1 - dt.timedelta(days=6), MONDAY - dt.timedelta(days=1))
    with Session(athlete.app.state.engine) as db:
        uid = db.scalars(select(User.id)).one()
        db.execute(delete(BodyMetric).where(BodyMetric.user_id == uid))
        for d in days:
            kg = 72.5 * (1 - 0.0075 * ((d - days[0]).days / 7))
            db.add(BodyMetric(user_id=uid, date=d, weight_kg=round(kg, 2), created_at=NOW))
        db.commit()
    assert run_job(athlete) == 0
    assert listing(athlete, kind="calories")["items"] == []


@pytest.mark.parametrize(("w1_days", "w2_days"), [(3, 7), (7, 3), (0, 0)])
def test_fewer_than_four_weigh_ins_gives_a_hint_and_no_suggestion(
    athlete: Api,  # noqa: F811
    w1_days: int,
    w2_days: int,
) -> None:
    pre = every_day(WEEK1 - dt.timedelta(days=6), WEEK1 - dt.timedelta(days=1))
    weigh(
        athlete,
        pre
        + every_day(WEEK1, WEEK1)[:0]
        + [WEEK1 + dt.timedelta(days=i) for i in range(w1_days)]
        + [WEEK2 + dt.timedelta(days=i) for i in range(w2_days)],
    )
    assert run_job(athlete) == 0
    body = listing(athlete)
    assert body["items"] == []
    hint = body["weigh_in_hint"]
    assert hint["evaluated_on"] == "2026-10-19" and hint["required_per_week"] == 4
    assert hint["weeks"] == [
        {"week_start": "2026-10-05", "weigh_ins": w1_days},
        {"week_start": "2026-10-12", "weigh_ins": w2_days},
    ]


def test_accept_changes_today_and_future_only(athlete: Api) -> None:  # noqa: F811
    flat_weeks(athlete)
    assert run_job(athlete) == 1
    sid = listing(athlete, kind="calories")["items"][0]["id"]
    before = _target_kcal(athlete)
    with Session(athlete.app.state.engine) as db:
        rows_before = db.scalars(select(Targets.valid_from)).all()

    def trigger(api: Api) -> Any:
        return api.client.post(f"/api/v1/suggestions/{sid}/accept")

    _rescale_check(athlete, trigger, "calories")  # future rescaled via #171, past unchanged
    assert _target_kcal(athlete) == before - 150
    with Session(athlete.app.state.engine) as db:
        row = db.scalars(
            select(Targets).where(Targets.valid_from == dt.date.fromisoformat(TODAY))
        ).one()
        assert row.kcal == before - 150
        assert set(db.scalars(select(Targets.valid_from)).all()) >= set(rows_before)
        assert db.scalars(select(Suggestion.status).where(Suggestion.id == sid)).one() == "accepted"
    body = athlete.client.get(f"{ME}/suggestions", params={"status": "accepted"}).json()
    assert body["items"][0]["payload"]["applied_kcal"] == before - 150


def test_reject_changes_nothing(athlete: Api) -> None:  # noqa: F811
    flat_weeks(athlete)
    run_job(athlete)
    sid = listing(athlete, kind="calories")["items"][0]["id"]
    before, versions = _target_kcal(athlete), _versions(athlete)
    assert athlete.client.post(f"/api/v1/suggestions/{sid}/reject").status_code == 200
    assert _target_kcal(athlete) == before and _versions(athlete) == versions


def test_a_new_week_replaces_the_stale_pending_suggestion(athlete: Api) -> None:  # noqa: F811
    flat_weeks(athlete)
    run_job(athlete)
    nxt = NOW + dt.timedelta(days=7)
    weigh(
        athlete,
        every_day(
            WEEK1 - dt.timedelta(days=6) + dt.timedelta(days=7), MONDAY + dt.timedelta(days=6)
        ),
    )
    with Session(athlete.app.state.engine) as db:
        assert adaptive_calories.run_weekly(db, nxt) == 1
    items = listing(athlete, kind="calories")["items"]
    assert len(items) == 1 and items[0]["inputs"]["evaluated_on"] == "2026-10-26"


def test_floor_blocks_a_decrease(athlete: Api) -> None:  # noqa: F811
    flat_weeks(athlete)
    with Session(athlete.app.state.engine) as db:
        t = db.scalars(select(Targets)).one()
        t.kcal = t.floor_kcal + 100
        db.commit()
    assert run_job(athlete) == 0
    assert listing(athlete, kind="calories")["items"] == []


def test_coach_and_stranger_cannot_read_or_decide(athlete: Api) -> None:  # noqa: F811
    flat_weeks(athlete)
    run_job(athlete)
    with Session(athlete.app.state.engine) as db:
        uid = db.scalars(select(User.id)).one()
        sid = db.scalars(select(Suggestion.id)).one()
    for email, role in (("bo@x.test", "athlete"), ("coach@x.test", "coach")):
        other = athlete.new_client()
        assert (
            other.post("/api/v1/auth/signup", json=signup_body(email=email, role=role)).status_code
            == 201
        )
        problem(other.get(f"/api/v1/athletes/{uid}/suggestions"), 403, "not_linked")
        problem(other.post(f"/api/v1/suggestions/{sid}/accept"), 403, "not_linked")
        problem(other.post(f"/api/v1/suggestions/{sid}/reject"), 403, "not_linked")
    assert listing(athlete, kind="calories")["items"][0]["status"] == "pending"


def test_monday_is_decided_in_the_athletes_time_zone(athlete: Api) -> None:  # noqa: F811
    """01:00 UTC Monday 2026-10-26 is still Sunday in Los Angeles and already Monday in Auckland;
    the Tuesday run reaches Los Angeles' Monday, so the double run covers every zone."""
    flat_weeks(athlete)
    monday_utc = dt.datetime(2026, 10, 26, 1, 0, tzinfo=dt.UTC)
    tuesday_utc = monday_utc + dt.timedelta(days=1)
    with Session(athlete.app.state.engine) as db:
        user = db.scalars(select(User)).one()
        for tz, now, want in (
            ("America/Los_Angeles", monday_utc, dt.date(2026, 10, 19)),
            ("Pacific/Auckland", monday_utc, dt.date(2026, 10, 26)),
            ("America/Los_Angeles", tuesday_utc, dt.date(2026, 10, 26)),
        ):
            user.timezone = tz
            ev = adaptive_calories.evaluate(db, user, clock.local_today(now, tz))
            assert ev is not None and ev.evaluated_on == want, tz


def test_athletes_without_targets_are_skipped(api: Api) -> None:
    assert api.signup().status_code == 201
    assert run_job(api) == 0
