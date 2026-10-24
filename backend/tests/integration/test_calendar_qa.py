"""QA additions for #27: time-zone boundaries of the plan start and of `date_in_past`, a move
whose original day is the only day in the requested range, and a coach on every calendar route."""

import datetime as dt
import uuid

from tests.integration.auth_helpers import Api, problem, signup_body
from tests.integration.test_calendar import BASE, _calendar, _day, _move, _plan, athlete

__all__ = ["athlete"]  # the fixture, re-exported for pytest


def _signup(api: Api, email: str, timezone: str) -> object:
    client = api.new_client()
    body = signup_body(email=email, timezone=timezone)
    assert client.post(f"{BASE}/auth/signup", json=body).status_code == 201
    return client


def _statuses(api: Api, client: object, start: str, end: str) -> dict[str, str]:
    days = _calendar(api, start, end, client).json()["days"]
    return {d["date"]: d["training_status"] for d in days}


def test_plan_start_and_missed_use_the_local_day_at_utc_plus_13_and_minus_11(
    athlete: Api,
) -> None:
    # 11:30 UTC on Thu 22 Oct is Fri 00:30 in Auckland (UTC+13) and Thu 00:30 in Pago Pago (-11).
    created = dt.datetime(2026, 10, 22, 11, 30, tzinfo=dt.UTC)
    athlete.clock.set(dt.datetime(2026, 10, 22, 12, 0, tzinfo=dt.UTC))
    nz = _signup(athlete, "nz2@x.test", "Pacific/Auckland")
    pago = _signup(athlete, "as2@x.test", "Pacific/Pago_Pago")
    _plan(athlete, "nz2@x.test", ["wed", "thu", "fri"], created)
    _plan(athlete, "as2@x.test", ["wed", "thu", "fri"], created)

    nz_days = _statuses(athlete, nz, "2026-10-21", "2026-10-23")
    assert nz_days == {"2026-10-21": "rest", "2026-10-22": "rest", "2026-10-23": "planned"}
    pago_days = _statuses(athlete, pago, "2026-10-21", "2026-10-23")
    assert pago_days == {"2026-10-21": "rest", "2026-10-22": "planned", "2026-10-23": "planned"}

    # Pago Pago's local midnight into Fri 23 is 11:00 UTC on Fri 23.
    athlete.clock.set(dt.datetime(2026, 10, 23, 10, 59, tzinfo=dt.UTC))
    assert _statuses(athlete, pago, "2026-10-22", "2026-10-22") == {"2026-10-22": "planned"}
    athlete.clock.set(dt.datetime(2026, 10, 23, 11, 0, tzinfo=dt.UTC))
    assert _statuses(athlete, pago, "2026-10-22", "2026-10-22") == {"2026-10-22": "missed"}
    assert _day(athlete, "2026-10-22", pago).json()["session"]["status"] == "missed"


def test_date_in_past_flips_at_local_midnight(athlete: Api) -> None:
    athlete.clock.set(dt.datetime(2026, 10, 23, 10, 59, tzinfo=dt.UTC))  # Thu 23:59 in Pago Pago
    pago = _signup(athlete, "as3@x.test", "Pacific/Pago_Pago")
    _plan(athlete, "as3@x.test", ["sat"])
    saturday = _day(athlete, "2026-10-24", pago).json()["session"]["id"]

    moved = _move(athlete, saturday, "2026-10-22", pago)  # local today: allowed
    assert moved.status_code == 200, moved.text
    assert _move(athlete, saturday, "2026-10-24", pago).status_code == 200

    athlete.clock.set(dt.datetime(2026, 10, 23, 11, 0, tzinfo=dt.UTC))  # Fri 00:00 in Pago Pago
    problem(_move(athlete, saturday, "2026-10-22", pago), 409, "date_in_past")


def test_a_range_holding_only_the_original_day_shows_it_as_rest(athlete: Api) -> None:
    thursday = _day(athlete, "2026-10-22").json()["session"]["id"]  # today in the fixture
    assert _move(athlete, thursday, "2026-10-24").status_code == 200
    day = _calendar(athlete, "2026-10-22", "2026-10-22").json()["days"][0]
    assert (day["training_status"], day["session_id"]) == ("rest", None)
    assert _day(athlete, "2026-10-22").json()["session"] is None


def test_a_coach_is_refused_on_every_calendar_route(athlete: Api) -> None:
    friday = _day(athlete, "2026-10-23").json()["session"]["id"]
    coach = athlete.new_client()
    body = signup_body(email="coach@x.test", role="coach")
    assert coach.post(f"{BASE}/auth/signup", json=body).status_code == 201

    problem(_day(athlete, "today", coach), 403, "not_linked")
    problem(_calendar(athlete, "2026-10-19", "2026-10-25", coach), 403, "not_linked")
    problem(coach.get(f"{BASE}/sessions/{friday}"), 403, "not_linked")
    problem(_move(athlete, friday, "2026-10-24", coach), 403, "not_linked")
    problem(_move(athlete, str(uuid.uuid4()), "2026-10-24", athlete.client), 403, "not_linked")
