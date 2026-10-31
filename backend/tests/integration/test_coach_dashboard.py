"""#48 `GET /coach/athletes` against real Postgres: only active links, F16.5 reasons and order
(owner decisions D83), the fixed query count, and authorization for the endpoint."""

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models import BodyMetric, CoachLink, Suggestion
from app.seed import run_seed
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import NOW, PASSWORD, Api, problem
from tests.integration.test_coach_links import Person, act, person
from tests.integration.test_onboarding import ONBOARD, onboarding

URL = "/api/v1/coach/athletes"
L = "/api/v1/coach-links"


def link_request(who: Person, coach: Person) -> dict[str, Any]:
    r = who.client.post(L, json={"coach_id": str(coach.id)})
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


@dataclass
class World:
    api: Api
    cleo: Person  # the coach under test
    dan: Person  # another coach
    stranger: Any

    def athlete(self, name: str, coach: Person | None = None, approve: bool = True) -> Person:
        who = person(self.api, f"{uuid.uuid4().hex[:8]}@x.test", "athlete", name)
        link = link_request(who, coach or self.cleo)
        if approve:
            assert act(coach or self.cleo, link["id"], "approve").status_code == 200
        return who

    def advance(self, **delta: float) -> None:
        """Move the clock; sessions last 24 h, so the coaches sign in again."""
        self.api.clock.advance(**delta)
        for coach in (self.cleo, self.dan):
            r = coach.client.post(
                "/api/v1/auth/login", json={"email": coach.email, "password": PASSWORD}
            )
            assert r.status_code == 200, r.text

    def items(self, who: Person | None = None) -> list[dict[str, Any]]:
        r = (who or self.cleo).client.get(URL)
        assert r.status_code == 200, r.text
        assert_matches_schema(r.json(), "CoachAthleteList")
        items: list[dict[str, Any]] = r.json()["items"]
        return items

    def by_name(self, name: str) -> dict[str, Any]:
        return next(i for i in self.items() if i["athlete"]["display_name"] == name)

    def log_weight(self, who: Person, day: dt.date) -> None:
        with Session(self.api.app.state.engine) as db:
            db.add(BodyMetric(user_id=who.id, date=day, weight_kg=70, created_at=NOW))
            db.commit()

    def suggest(self, who: Person, rule: str, status: str, decided: dt.datetime | None) -> None:
        with Session(self.api.app.state.engine) as db:
            db.add(
                Suggestion(
                    athlete_id=who.id,
                    kind="progression",
                    status=status,
                    rule=rule,
                    reason="r",
                    inputs={},
                    payload={},
                    created_at=NOW,
                    decided_at=decided,
                )
            )
            db.commit()


@pytest.fixture
def w(api: Api) -> World:
    return World(
        api,
        person(api, "cleo@x.test", "coach", "Cleo Coach"),
        person(api, "dan@x.test", "coach", "Dan Coach"),
        api.new_client(),
    )


# ───────────── authorization and list membership ─────────────


def test_empty_list_for_a_coach_without_athletes(w: World) -> None:
    assert w.items() == []


def test_athlete_is_wrong_role_and_anonymous_is_401(w: World) -> None:
    ana = w.athlete("Ana")
    problem(ana.client.get(URL), 403, "wrong_role")
    problem(w.stranger.get(URL), 401, "not_authenticated")


def test_only_active_links_and_never_another_coachs_athletes(w: World) -> None:
    w.athlete("Active")
    w.athlete("Pending", approve=False)
    declined = person(w.api, "d@x.test", "athlete", "Declined")
    link = link_request(declined, w.cleo)
    assert act(w.cleo, link["id"], "decline").status_code == 200
    ended = w.athlete("Ended")
    with Session(w.api.app.state.engine) as db:
        row = db.query(CoachLink).filter_by(athlete_id=ended.id).one()
        link_id = str(row.id)
    assert act(ended, link_id, "end").status_code == 200
    w.athlete("Dans", coach=w.dan)
    assert [i["athlete"]["display_name"] for i in w.items()] == ["Active"]
    assert [i["athlete"]["display_name"] for i in w.items(w.dan)] == ["Dans"]


def test_ending_a_link_removes_the_athlete_on_the_next_request(w: World) -> None:
    ana = w.athlete("Ana")
    assert len(w.items()) == 1
    link_id = w.items()[0]["link_id"]
    assert act(w.cleo, link_id, "end").status_code == 200
    assert w.items() == []
    assert ana.client.get("/api/v1/me").json()["active_coach"] is None


# ───────────── needs-attention rules (F16.5, D83) ─────────────


def test_summary_fields(w: World) -> None:
    w.athlete("Ana")
    item = w.items()[0]
    assert item["needs_attention"] is False
    assert item["attention_reasons"] == []
    assert item["training_adherence_7d"] is None  # no plan: nothing planned
    assert item["last_log_date"] is None
    assert item["pending_suggestion_count"] == 0
    assert item["linked_since"].startswith("2026-10-22")


def test_never_logged_is_inactive_three_days_after_the_link(w: World) -> None:
    w.athlete("Ana")
    w.advance(days=2)
    assert w.by_name("Ana")["attention_reasons"] == []
    w.advance(days=1)
    item = w.by_name("Ana")
    assert item["attention_reasons"] == ["inactive"] and item["needs_attention"] is True
    assert item["last_log_date"] is None


def test_a_log_clears_inactive_and_sets_last_log_date(w: World) -> None:
    ana = w.athlete("Ana")
    w.advance(days=5)
    assert w.by_name("Ana")["attention_reasons"] == ["inactive"]
    today = (NOW + dt.timedelta(days=4)).date()
    w.log_weight(ana, today)
    item = w.by_name("Ana")
    assert item["last_log_date"] == today.isoformat() and item["attention_reasons"] == []
    w.advance(days=2)  # logged 3 days ago
    assert w.by_name("Ana")["attention_reasons"] == ["inactive"]


@pytest.mark.parametrize(("ago", "expected"), [(14, ["deload"]), (15, [])])
def test_deload_applied_window(w: World, ago: int, expected: list[str]) -> None:
    ana = w.athlete("Ana")
    w.log_weight(ana, NOW.date())
    decided = NOW - dt.timedelta(days=ago)
    w.suggest(ana, "deload", "accepted", decided)
    w.advance(days=0)
    assert w.by_name("Ana")["attention_reasons"] == expected


def test_pending_deload_and_pending_count(w: World) -> None:
    ana = w.athlete("Ana")
    w.log_weight(ana, NOW.date())
    w.suggest(ana, "linear", "pending", None)
    item = w.by_name("Ana")
    assert item["pending_suggestion_count"] == 1 and item["attention_reasons"] == []
    w.suggest(ana, "deload", "pending", None)
    item = w.by_name("Ana")
    assert item["pending_suggestion_count"] == 2 and item["attention_reasons"] == ["deload"]


def test_rejected_deload_does_not_trigger(w: World) -> None:
    ana = w.athlete("Ana")
    w.log_weight(ana, NOW.date())
    w.suggest(ana, "deload", "rejected", NOW)
    assert w.by_name("Ana")["attention_reasons"] == []


def test_adherence_null_without_plan_and_zero_when_sessions_were_missed(w: World) -> None:
    with Session(w.api.app.state.engine) as db:
        run_seed(db)
    ana = w.athlete("Ana")
    assert ana.client.post(ONBOARD, json=onboarding()).status_code == 201
    assert w.by_name("Ana")["training_adherence_7d"] is None  # nothing past is planned yet
    w.advance(days=8)
    w.log_weight(ana, (NOW + dt.timedelta(days=8)).date())  # only inactive is ruled out
    item = w.by_name("Ana")
    assert item["training_adherence_7d"] == 0.0
    assert item["attention_reasons"] == ["low_adherence"]
    assert_matches_schema(item, "CoachAthleteSummary")


def test_order_attention_first_then_name_case_insensitive_then_id(w: World) -> None:
    quiet = w.athlete("zed quiet")
    ok_b = w.athlete("bob")
    ok_a = w.athlete("Alice")
    attention_b = w.athlete("beth")
    for who in (quiet, ok_b, ok_a, attention_b):
        w.log_weight(who, NOW.date())
    w.suggest(quiet, "deload", "pending", None)
    w.suggest(attention_b, "deload", "pending", None)
    names = [i["athlete"]["display_name"] for i in w.items()]
    assert names == ["beth", "zed quiet", "Alice", "bob"]


def test_same_name_ties_break_on_athlete_id(w: World) -> None:
    for _ in range(3):
        w.athlete("Sam")
    ids = [i["athlete"]["id"] for i in w.items()]
    assert ids == sorted(ids)


# ───────────── query count ─────────────


def _count_queries(w: World) -> int:
    statements: list[str] = []

    def record(conn: Any, cursor: Any, statement: str, *rest: Any) -> None:
        statements.append(statement)

    engine = w.api.app.state.engine
    event.listen(engine, "before_cursor_execute", record)
    try:
        assert w.cleo.client.get(URL).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return len(statements)


def test_query_count_does_not_depend_on_the_number_of_clients(w: World) -> None:
    first = w.athlete("A0")
    w.log_weight(first, NOW.date())
    w.suggest(first, "deload", "pending", None)
    _count_queries(w)  # warm-up
    one = _count_queries(w)
    for i in range(1, 10):
        who = w.athlete(f"A{i}")
        w.log_weight(who, NOW.date())
        w.suggest(who, "deload", "accepted", NOW)
    assert len(w.items()) == 10
    assert _count_queries(w) == one
