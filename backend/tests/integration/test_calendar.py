"""#27 Calendar API against real Postgres: materialisation, time zones, missed, move (D45),
range errors, authorization and the F9.4 performance budget."""

import datetime as dt
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Exercise, Plan, PlannedExercise, TrainingDay, TrainingSession, User
from app.seed import run_seed
from app.services import calendar as calendar_service
from app.services.plans import NewPlannedExercise, NewTrainingDay, create_plan_version
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import NOW, Api, problem, signup_body

# NOW is Thursday 2026-10-22 09:00 UTC (11:00 in Europe/Madrid). Week: Mon 19 .. Sun 25.
THU = dt.date(2026, 10, 22)
PLAN_CREATED = NOW - dt.timedelta(days=60)
BASE = "/api/v1"


@pytest.fixture
def athlete(api: Api) -> Api:
    with Session(api.app.state.engine) as session:
        run_seed(session)
    assert api.signup().status_code == 201
    _plan(api, "ana@x.test", ["mon", "thu", "fri"])
    return api


def _user_id(api: Api, email: str) -> uuid.UUID:
    with Session(api.app.state.engine) as session:
        return session.scalars(select(User.id).where(User.email == email)).one()


def _plan(api: Api, email: str, weekdays: list[str], created: dt.datetime = PLAN_CREATED) -> Plan:
    with Session(api.app.state.engine) as session:
        exercise = session.scalars(
            select(Exercise).where(Exercise.owner_id.is_(None), Exercise.type == "strength")
        ).first()
        assert exercise is not None
        uid = _user_id(api, email)
        plan = create_plan_version(
            session,
            athlete_id=uid,
            author_id=uid,
            source="generated",
            days=[
                NewTrainingDay(
                    w,
                    f"Day {w}",
                    [
                        NewPlannedExercise(
                            exercise.id,
                            3,
                            90,
                            "linear",
                            2.5,
                            reps_min=8,
                            reps_max=8,
                            target_weight_kg=50.0,
                        )
                    ],
                )
                for w in weekdays
            ],
            now=created,
        )
        session.commit()
        return plan


def _day(api: Api, day: str, client: Any = None, athlete: str = "me") -> Any:
    return (client or api.client).get(f"{BASE}/athletes/{athlete}/days/{day}")


def _calendar(api: Api, start: str, end: str, client: Any = None, athlete: str = "me") -> Any:
    return (client or api.client).get(
        f"{BASE}/athletes/{athlete}/calendar", params={"from": start, "to": end}
    )


def _rows(api: Api) -> list[TrainingSession]:
    with Session(api.app.state.engine) as session:
        rows = list(session.scalars(select(TrainingSession).order_by(TrainingSession.date)))
        session.expunge_all()
        return rows


# ───────────── materialisation ─────────────


def test_viewing_a_planned_day_materialises_one_session_idempotently(athlete: Api) -> None:
    first = _day(athlete, "2026-10-23")
    second = _day(athlete, "2026-10-23")
    assert first.status_code == second.status_code == 200
    body = first.json()
    assert_matches_schema(body, "DayView")
    assert body["session"]["id"] == second.json()["session"]["id"]
    assert body["training_status"] == "planned"
    assert body["session"]["training_day_name"] == "Day fri"
    assert body["session"]["plan_version"] == 1
    assert len(body["session"]["exercises"][0]["sets"]) == 3
    assert len(_rows(athlete)) == 1


def test_concurrent_views_create_a_single_row(athlete: Api) -> None:
    with Session(athlete.app.state.engine) as session:
        user = session.get(User, _user_id(athlete, "ana@x.test"))
        assert user is not None
        session.expunge(user)
    day = dt.date(2026, 10, 30)

    def view(_: int) -> uuid.UUID:
        with Session(athlete.app.state.engine) as session:
            tpl = calendar_service._template(session, user)
            row = calendar_service._materialise(session, user, tpl, day, NOW)
            assert row is not None
            return row.id

    with ThreadPoolExecutor(8) as pool:
        ids = set(pool.map(view, range(8)))
    assert len(ids) == 1
    assert len(_rows(athlete)) == 1


def test_a_day_without_a_training_day_is_a_rest_day(athlete: Api) -> None:
    body = _day(athlete, "2026-10-24").json()  # Saturday
    assert_matches_schema(body, "DayView")
    assert body["session"] is None and body["training_status"] == "rest"
    assert body["weekday"] == "sat"
    assert _rows(athlete) == []


def test_no_plan_means_rest_days(api: Api) -> None:
    assert api.signup().status_code == 201
    assert _day(api, "today").json()["training_status"] == "rest"


# ───────────── time zones (F9.1) ─────────────


def test_today_depends_on_the_users_time_zone(athlete: Api) -> None:
    athlete.clock.set(dt.datetime(2026, 10, 22, 12, 0, tzinfo=dt.UTC))
    auckland = athlete.new_client()  # UTC+13 in October
    pago = athlete.new_client()  # UTC-11
    for client, email, tz in (
        (auckland, "nz@x.test", "Pacific/Auckland"),
        (pago, "as@x.test", "Pacific/Pago_Pago"),
    ):
        assert (
            client.post(
                f"{BASE}/auth/signup", json=signup_body(email=email, timezone=tz)
            ).status_code
            == 201
        )
    assert _day(athlete, "today", auckland).json()["date"] == "2026-10-23"
    assert _day(athlete, "today", pago).json()["date"] == "2026-10-22"
    assert _day(athlete, "today", auckland).json()["is_today"] is True


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        # Madrid is UTC+2: local midnight of Fri 23 Oct is 22:00 UTC on Thu 22.
        (dt.datetime(2026, 10, 22, 21, 59, tzinfo=dt.UTC), "planned"),
        (dt.datetime(2026, 10, 22, 22, 0, tzinfo=dt.UTC), "missed"),
    ],
)
def test_missed_flips_at_local_midnight(athlete: Api, instant: dt.datetime, expected: str) -> None:
    athlete.clock.set(instant)
    day = _day(athlete, "2026-10-22").json()
    cal = _calendar(athlete, "2026-10-22", "2026-10-22").json()["days"][0]
    assert day["training_status"] == cal["training_status"] == expected
    assert day["session"]["status"] == expected


def test_missed_rules_over_a_week(athlete: Api) -> None:
    athlete.clock.set(dt.datetime(2026, 10, 22, 9, 0, tzinfo=dt.UTC))
    days = _calendar(athlete, "2026-10-19", "2026-10-25").json()["days"]
    assert_matches_schema(_calendar(athlete, "2026-10-19", "2026-10-25").json(), "CalendarRange")
    assert [(d["weekday"], d["training_status"]) for d in days] == [
        ("mon", "missed"),  # past, planned, no logs
        ("tue", "rest"),  # rest days are never missed
        ("wed", "rest"),
        ("thu", "planned"),  # today is never missed
        ("fri", "planned"),  # future is never missed
        ("sat", "rest"),
        ("sun", "rest"),
    ]
    assert [d["is_today"] for d in days].count(True) == 1
    assert _rows(athlete) == []  # ranges never write


def test_days_before_the_plan_existed_are_not_missed(athlete: Api) -> None:
    days = _calendar(athlete, "2026-08-17", "2026-08-17").json()["days"]  # a Monday, 66 days ago
    assert days[0]["training_status"] == "rest"


# ───────────── move (F9.2, D45) ─────────────


def _move(api: Api, session_id: str, date: Any, client: Any = None) -> Any:
    return (client or api.client).post(f"{BASE}/sessions/{session_id}/move", json={"date": date})


def _plan_snapshot(api: Api) -> list[tuple[Any, ...]]:
    with Session(api.app.state.engine) as session:
        return [
            *session.execute(
                select(Plan.id, Plan.version, Plan.revision, Plan.active, Plan.updated_at)
            ).all(),
            *session.execute(
                select(TrainingDay.id, TrainingDay.weekday, TrainingDay.name, TrainingDay.position)
            ).all(),
            *session.execute(
                select(PlannedExercise.id, PlannedExercise.sets, PlannedExercise.position)
            ).all(),
        ]


def test_move_shows_on_the_new_day_only_and_leaves_the_template_alone(athlete: Api) -> None:
    friday = _day(athlete, "2026-10-23").json()["session"]["id"]
    before = _plan_snapshot(athlete)

    moved = _move(athlete, friday, "2026-10-25")  # Sunday
    assert moved.status_code == 200, moved.text
    assert_matches_schema(moved.json(), "Session")
    assert moved.json()["date"] == "2026-10-25"
    assert moved.json()["original_date"] == "2026-10-23"

    assert _day(athlete, "2026-10-23").json()["session"] is None
    assert _day(athlete, "2026-10-23").json()["training_status"] == "rest"
    sunday = _day(athlete, "2026-10-25").json()
    assert sunday["session"]["id"] == friday and sunday["training_status"] == "planned"
    days = {d["date"]: d for d in _calendar(athlete, "2026-10-19", "2026-10-25").json()["days"]}
    assert days["2026-10-23"]["training_status"] == "rest"
    assert days["2026-10-23"]["session_id"] is None
    assert days["2026-10-25"]["session_id"] == friday and days["2026-10-25"]["moved"] is True
    assert _plan_snapshot(athlete) == before
    assert len(_rows(athlete)) == 1

    # The week after still has its normal Friday, and moving back clears the marker.
    assert _day(athlete, "2026-10-30").json()["training_status"] == "planned"
    back = _move(athlete, friday, "2026-10-23").json()
    assert back["original_date"] is None and back["date"] == "2026-10-23"


def test_move_rejections(athlete: Api) -> None:
    friday = _day(athlete, "2026-10-23").json()["session"]["id"]
    # Thursday (today) holds a not-yet-materialised template session: still occupied.
    problem(_move(athlete, friday, "2026-10-22"), 409, "day_occupied")
    # Another materialised session on the target day.
    _day(athlete, "2026-10-22")
    problem(_move(athlete, friday, "2026-10-22"), 409, "day_occupied")
    problem(_move(athlete, friday, "2026-10-23"), 409, "day_occupied")  # onto itself
    problem(_move(athlete, friday, "2026-10-20"), 409, "date_in_past")  # Tuesday < today
    problem(_move(athlete, friday, "2026-10-26"), 409, "outside_week")  # next Monday
    problem(_move(athlete, friday, "2026-10-18"), 409, "outside_week")  # Sunday before
    with Session(athlete.app.state.engine) as session:
        row = session.get(TrainingSession, uuid.UUID(friday))
        assert row is not None
        row.status, row.finished_at = "done", NOW
        session.commit()
    problem(_move(athlete, friday, "2026-10-24"), 409, "session_finished")


def test_move_into_a_slot_left_by_another_moved_session_is_allowed(athlete: Api) -> None:
    thursday = _day(athlete, "2026-10-22").json()["session"]["id"]
    friday = _day(athlete, "2026-10-23").json()["session"]["id"]
    assert _move(athlete, thursday, "2026-10-24").status_code == 200
    assert _move(athlete, friday, "2026-10-22").status_code == 200
    assert _day(athlete, "2026-10-22").json()["session"]["id"] == friday


def test_move_validation(athlete: Api) -> None:
    friday = _day(athlete, "2026-10-23").json()["session"]["id"]
    for bad in ("2026-13-45", "not-a-date", 5, None, "2026-10-24\u0000"):
        response = _move(athlete, friday, bad)
        assert response.status_code == 422, bad
        assert response.headers["content-type"] == "application/problem+json"
    nul = athlete.client.post(
        f"{BASE}/sessions/{friday}/move",
        content='{"date": "2026-10-24\\u0000"}',
        headers={"content-type": "application/json"},
    )
    assert nul.status_code == 422
    broken = athlete.client.post(
        f"{BASE}/sessions/{friday}/move", content="{", headers={"content-type": "application/json"}
    )
    assert broken.status_code == 400
    assert (
        athlete.client.post(
            f"{BASE}/sessions/{friday}/move", json={"date": "2026-10-24", "extra": 1}
        ).status_code
        == 422
    )


# ───────────── range ─────────────


def test_range_limits(athlete: Api) -> None:
    ok = _calendar(athlete, "2026-10-01", "2026-11-11")  # exactly 42 days
    assert ok.status_code == 200 and len(ok.json()["days"]) == 42
    problem(_calendar(athlete, "2026-10-01", "2026-11-12"), 400, "range_too_large")
    problem(_calendar(athlete, "2026-10-05", "2026-10-04"), 400, "invalid_range")
    assert _calendar(athlete, "2026-10-05", "2026-10-05").json()["days"][0]["date"] == "2026-10-05"
    assert athlete.client.get(f"{BASE}/athletes/me/calendar").status_code == 400
    assert _calendar(athlete, "nope", "2026-10-05").status_code == 400
    assert _day(athlete, "2026-13-45").status_code == 400
    assert _day(athlete, "garbage").status_code == 400


# ───────────── authorization (D41) ─────────────


def test_authorization(athlete: Api) -> None:
    friday = _day(athlete, "2026-10-23").json()["session"]["id"]
    stranger = athlete.new_client()
    assert (
        stranger.post(f"{BASE}/auth/signup", json=signup_body(email="bo@x.test")).status_code == 201
    )
    ana = str(_user_id(athlete, "ana@x.test"))
    bo = str(_user_id(athlete, "bo@x.test"))

    # The stranger cannot see Ana's data by id, and unknown ids look the same (403).
    for target in (ana, str(uuid.uuid4())):
        problem(_day(athlete, "2026-10-23", stranger, target), 403, "not_linked")
        problem(_calendar(athlete, "2026-10-19", "2026-10-25", stranger, target), 403, "not_linked")
    problem(_day(athlete, "today", athlete.client, bo), 403, "not_linked")
    assert _day(athlete, "2026-10-23", athlete.client, ana).status_code == 200
    assert _day(athlete, "2026-10-23", stranger).json()["session"] is None

    problem(stranger.get(f"{BASE}/sessions/{friday}"), 403, "not_linked")
    problem(_move(athlete, friday, "2026-10-24", stranger), 403, "not_linked")
    problem(stranger.get(f"{BASE}/sessions/{uuid.uuid4()}"), 404, "not_found")
    assert stranger.get(f"{BASE}/sessions/not-a-uuid").status_code == 400
    owner = athlete.client.get(f"{BASE}/sessions/{friday}")
    assert owner.status_code == 200 and owner.json()["id"] == friday
    assert _rows(athlete)[0].date == dt.date(2026, 10, 23)  # unchanged by the rejected move

    anonymous = athlete.new_client()
    problem(_day(athlete, "today", anonymous), 401, "not_authenticated")
    problem(_calendar(athlete, "2026-10-19", "2026-10-25", anonymous), 401, "not_authenticated")
    problem(anonymous.get(f"{BASE}/sessions/{friday}"), 401, "not_authenticated")
    problem(_move(athlete, friday, "2026-10-24", anonymous), 401, "not_authenticated")


def test_a_coach_has_no_calendar_of_their_own(api: Api) -> None:
    assert api.signup(role="coach").status_code == 201
    problem(_day(api, "today"), 403, "not_linked")


# ───────────── F9.4 performance ─────────────


def test_week_and_month_views_p95_under_500ms_with_a_year_of_sessions(athlete: Api) -> None:
    uid = _user_id(athlete, "ana@x.test")
    with Session(athlete.app.state.engine) as session:
        plan = session.scalars(select(Plan)).one()
        plan.created_at = NOW - dt.timedelta(days=400)
        by_weekday = {d.weekday: d for d in plan.training_days}
        day = THU - dt.timedelta(days=365)
        while day <= THU + dt.timedelta(days=30):
            template = by_weekday.get(
                ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[day.weekday()]
            )
            if template:
                session.add(
                    TrainingSession(
                        athlete_id=uid,
                        plan_id=plan.id,
                        training_day_id=template.id,
                        date=day,
                        status="done" if day < THU else "planned",
                        created_at=NOW,
                    )
                )
            day += dt.timedelta(days=1)
        session.commit()
        total = session.scalar(select(func.count()).select_from(TrainingSession))
    assert total and total > 150

    def p95(start: str, end: str) -> float:
        _calendar(athlete, start, end)  # warm-up
        times = []
        for _ in range(50):
            t0 = time.perf_counter()
            response = _calendar(athlete, start, end)
            times.append((time.perf_counter() - t0) * 1000)
            assert response.status_code == 200
        return sorted(times)[int(0.95 * len(times)) - 1]

    assert p95("2026-10-19", "2026-10-25") < 500  # week
    assert p95("2026-09-28", "2026-11-08") < 500  # 6-week month grid
