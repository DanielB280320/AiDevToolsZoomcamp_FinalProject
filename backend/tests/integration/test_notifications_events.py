"""#45 F17.1: the producers that exist today (progression, weekly calories, recalculation) create
exactly one notification per event for the right user and never twice on a retry (D79.1, D79.2)."""

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Notification, Suggestion, User
from app.services import notifications
from tests.integration.auth_helpers import NOW, Api
from tests.integration.test_adaptive_calories import MONDAY, flat_weeks, run_job, weigh
from tests.integration.test_body_metrics import athlete as body_athlete  # noqa: F401
from tests.integration.test_body_metrics import log
from tests.integration.test_rescale_portions import athlete as calories_athlete  # noqa: F401
from tests.integration.test_suggestions import _pending_for, _perform
from tests.integration.test_suggestions import athlete as training_athlete  # noqa: F401
from tests.integration.test_training_log import (
    BASE,
    THU,
    _finish,
    _ids,
    _log,
    _session,
    _stranger,
)

N = "/api/v1/notifications"


def stored(api: Api, type_: str | None = None, user: uuid.UUID | None = None) -> list[Notification]:
    with Session(api.app.state.engine) as db:
        query = select(Notification).order_by(Notification.created_at, Notification.id)
        if type_:
            query = query.where(Notification.type == type_)
        if user:
            query = query.where(Notification.user_id == user)
        return list(db.scalars(query))


def athlete_id(api: Api, email: str = "ana@x.test") -> uuid.UUID:
    with Session(api.app.state.engine) as db:
        return db.scalars(select(User.id).where(User.email == email)).one()


# ───────────── progression (D79.1) ─────────────


def _log_timed(api: Api, sid: str, timed: str) -> None:
    assert _log(api, sid, exercise_id=timed, set_no=1, seconds=600).status_code in (200, 201)


def test_finish_creates_one_notification_per_suggestion_for_the_athlete_only(
    training_athlete: Api,  # noqa: F811
) -> None:
    api = training_athlete
    stranger = _stranger(api)
    earlier = {r.id for r in stored(api)}
    sid, ex, planned, timed = _ids(_session(api, THU))
    for n in (1, 2, 3):
        _log(api, sid, exercise_id=ex, planned_exercise_id=planned, set_no=n, reps=8, weight_kg=50)
    _log_timed(api, sid, timed)
    finished = _finish(api, sid).json()["suggestions"]
    assert len(finished) == 2
    rows = [r for r in stored(api, "progression_suggestion") if r.id not in earlier]
    assert sorted(r.payload["suggestion_id"] for r in rows) == sorted(s["id"] for s in finished)
    assert {r.user_id for r in rows} == {athlete_id(api)}
    assert all(r.read_at is None for r in rows)
    assert stranger.get(N).json() == {"items": [], "unread_count": 0, "next_cursor": None}
    assert api.client.get(N).json()["unread_count"] == 2 + len(earlier)


def test_refinish_notifies_only_newly_created_suggestions(training_athlete: Api) -> None:  # noqa: F811
    api = training_athlete
    sid = _perform(api, THU, reps=8)
    (first,) = _pending_for(api, sid)
    assert api.client.post(f"{BASE}/suggestions/{first['id']}/reject").status_code == 200
    before = {r.id for r in stored(api, "progression_suggestion")}
    assert _finish(api, sid).status_code == 200  # the decided exercise is not suggested again
    assert {r.id for r in stored(api, "progression_suggestion")} == before
    ids = [r.payload["suggestion_id"] for r in stored(api, "progression_suggestion")]
    assert ids.count(first["id"]) == 1


def test_a_recompute_notifies_its_new_suggestion_and_keeps_the_old_notification(
    training_athlete: Api,  # noqa: F811
) -> None:
    api = training_athlete
    sid = _perform(api, THU, reps=8)
    (first,) = _pending_for(api, sid)
    assert _finish(api, sid).status_code == 200
    (second,) = _pending_for(api, sid)
    assert second["id"] != first["id"]
    ids = [r.payload["suggestion_id"] for r in stored(api, "progression_suggestion")]
    assert ids.count(second["id"]) == 1 and ids.count(first["id"]) == 1  # D79.2: kept


def test_notify_path_called_twice_with_the_same_suggestion_leaves_one_row(
    training_athlete: Api,  # noqa: F811
) -> None:
    api = training_athlete
    sid = _perform(api, THU, reps=8)
    (s,) = _pending_for(api, sid)
    with Session(api.app.state.engine) as db:
        again = notifications.notify(
            db, athlete_id(api), "progression_suggestion", {"suggestion_id": s["id"]}, NOW
        )
        db.commit()
    assert again is None
    mine = [
        r for r in stored(api, "progression_suggestion") if r.payload["suggestion_id"] == s["id"]
    ]
    assert len(mine) == 1


def test_accepting_or_rejecting_keeps_the_progression_notification(
    training_athlete: Api,  # noqa: F811
) -> None:
    api = training_athlete
    sid = _perform(api, THU, reps=8)
    (s,) = _pending_for(api, sid)
    assert api.client.post(f"{BASE}/suggestions/{s['id']}/accept").status_code == 200
    assert len([r for r in stored(api, "progression_suggestion")
                if r.payload["suggestion_id"] == s["id"]]) == 1  # fmt: skip


# ───────────── calories (F14) ─────────────


def test_weekly_run_creates_exactly_one_calorie_notification_and_not_again(
    calories_athlete: Api,  # noqa: F811
) -> None:
    api = calories_athlete
    flat_weeks(api)
    assert run_job(api) == 1
    (row,) = stored(api, "calorie_suggestion")
    with Session(api.app.state.engine) as db:
        suggestion = db.scalars(select(Suggestion).where(Suggestion.kind == "calories")).one()
    assert row.payload == {"suggestion_id": str(suggestion.id)}
    assert row.user_id == athlete_id(api) and row.read_at is None
    assert run_job(api) == 0
    assert len(stored(api, "calorie_suggestion")) == 1


def test_no_calorie_suggestion_means_no_notification(calories_athlete: Api) -> None:  # noqa: F811
    api = calories_athlete
    weigh(api, [MONDAY - dt.timedelta(days=i) for i in range(1, 4)])  # fewer than 4 weigh-ins
    assert run_job(api) == 0
    assert stored(api) == []


def test_the_calorie_notification_stays_after_the_suggestion_is_decided(
    calories_athlete: Api,  # noqa: F811
) -> None:
    api = calories_athlete
    flat_weeks(api)
    run_job(api)
    (row,) = stored(api, "calorie_suggestion")
    sid = row.payload["suggestion_id"]
    assert api.client.post(f"/api/v1/suggestions/{sid}/reject").status_code == 200
    assert [r.id for r in stored(api, "calorie_suggestion")] == [row.id]


# ───────────── recalc (F14, D79.2) ─────────────


def unread_recalc(api: Api) -> list[Notification]:
    return [r for r in stored(api, "recalc_prompt") if r.read_at is None]


def test_a_weigh_in_at_two_percent_creates_one_recalc_notification(
    body_athlete: Api,  # noqa: F811
) -> None:
    api = body_athlete
    assert log(api, weight_kg=73.94).json()["recalc_suggestion"] is None  # +1.99 %
    assert stored(api, "recalc_prompt") == []
    suggestion = log(api, weight_kg=73.95).json()["recalc_suggestion"]  # +2.00 %
    (row,) = stored(api, "recalc_prompt")
    assert row.payload == {"suggestion_id": suggestion["id"]}
    assert row.user_id == athlete_id(api) and row.read_at is None
    assert api.client.get(N).json()["unread_count"] == 1


def test_a_newer_recalc_deletes_the_older_unread_notification(body_athlete: Api) -> None:  # noqa: F811
    api = body_athlete
    first = log(api, weight_kg=75.0).json()["recalc_suggestion"]
    second = log(api, weight_kg=76.0).json()["recalc_suggestion"]
    (row,) = unread_recalc(api)
    assert row.payload["suggestion_id"] == second["id"] != first["id"]
    assert len(stored(api, "recalc_prompt")) == 1


def test_a_read_recalc_notification_is_kept_when_replaced(body_athlete: Api) -> None:  # noqa: F811
    api = body_athlete
    first = log(api, weight_kg=75.0).json()["recalc_suggestion"]
    (old,) = stored(api, "recalc_prompt")
    assert api.client.post(f"{N}/{old.id}/read").status_code == 200
    second = log(api, weight_kg=76.0).json()["recalc_suggestion"]
    both = stored(api, "recalc_prompt")
    assert {r.payload["suggestion_id"] for r in both} == {first["id"], second["id"]}
    assert [r.payload["suggestion_id"] for r in unread_recalc(api)] == [second["id"]]


def test_a_weigh_in_below_the_threshold_removes_the_stale_unread_notification(
    body_athlete: Api,  # noqa: F811
) -> None:
    api = body_athlete
    assert log(api, weight_kg=75.0).json()["recalc_suggestion"] is not None
    assert log(api, weight_kg=72.6).json()["recalc_suggestion"] is None  # replaces today's entry
    with Session(api.app.state.engine) as db:
        assert db.scalar(select(func.count()).where(Suggestion.kind == "recalc")) == 0
    assert stored(api, "recalc_prompt") == []


def test_other_users_recalc_notifications_are_untouched(body_athlete: Api) -> None:  # noqa: F811
    api = body_athlete
    log(api, weight_kg=75.0)
    mine = stored(api, "recalc_prompt")
    stranger = api.new_client()
    from tests.integration.auth_helpers import signup_body

    stranger.post("/api/v1/auth/signup", json=signup_body(email="bo@x.test"))
    other = uuid.UUID(stranger.get("/api/v1/me").json()["id"])
    with Session(api.app.state.engine) as db:
        notifications.notify(db, other, "recalc_prompt", {"suggestion_id": uuid.uuid4()}, NOW)
        db.commit()
    log(api, weight_kg=76.0)
    assert len(stored(api, "recalc_prompt", other)) == 1
    assert mine[0].id not in {r.id for r in stored(api, "recalc_prompt", athlete_id(api))}
