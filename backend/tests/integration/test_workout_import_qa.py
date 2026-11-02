"""QA (#57): extra all-or-nothing and contract checks for the CSV import (F10.5, D89, D90)."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import SetLog, TrainingSession
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import Api, problem
from tests.integration.test_workout_import import (
    BASE,
    _count,
    _csv,
    _names,
    _two_days,
    _upload,
    athlete,  # noqa: F401 - pytest fixture
)


def test_a_real_session_day_rejects_the_valid_days_of_the_same_file(athlete: Api) -> None:  # noqa: F811
    n = _names(athlete)
    # Materialise the real (planned) session of "today" (NOW is 2026-10-22).
    assert athlete.client.get(f"{BASE}/athletes/me/days/2026-10-22").status_code == 200
    real_before = _count(athlete, TrainingSession)
    data = _csv(
        f"2026-08-03,{n['strength']},1,8,60,,",
        f"2026-10-22,{n['strength']},1,8,60,,",
        f"2026-08-04,{n['strength']},1,8,60,,",
    )
    body = problem(_upload(athlete.client, data), 422, "invalid_import")
    assert [e["field"] for e in body["errors"]] == ["rows.3"]
    assert n["strength"] not in str(body)
    assert _count(athlete, SetLog) == 0
    assert _count(athlete, TrainingSession) == real_before
    with Session(athlete.app.state.engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(TrainingSession).where(TrainingSession.imported)
            )
            == 0
        )


def test_a_bad_row_after_an_earlier_import_changes_nothing(athlete: Api) -> None:  # noqa: F811
    n = _names(athlete)
    assert _upload(athlete.client, _two_days(athlete)).json() == {"imported": 3, "skipped": 0}
    data = _csv(
        f"2026-08-03,{n['strength']},3,5,70,,",  # new, valid set on an imported day
        f"2026-08-05,{n['strength']},1,8,60,,",  # new, valid day
        "2026-08-05,Not An Exercise,2,8,60,,",
    )
    problem(_upload(athlete.client, data), 422, "invalid_import")
    assert _count(athlete, SetLog) == 3
    assert _count(athlete, TrainingSession) == 2


def test_an_imported_session_matches_the_session_contract(athlete: Api) -> None:  # noqa: F811
    assert _upload(athlete.client, _two_days(athlete)).status_code == 200
    day = athlete.client.get(f"{BASE}/athletes/me/days/2026-08-04").json()["session"]
    detail = athlete.client.get(f"{BASE}/sessions/{day['id']}")
    assert detail.status_code == 200, detail.text
    session = detail.json()
    assert_matches_schema(session, "Session")
    assert session["imported"] is True
    assert session["plan_id"] is None and session["plan_version"] is None
    assert session["training_day_id"] is None and session["training_day_name"] is None
    assert session["completion"] is None and session["status"] == "done"
    for exercise in session["exercises"]:
        for s in exercise["sets"]:
            assert s["target_reps"] is None and s["target_weight_kg"] is None
            assert s["target_seconds"] is None and s["log"] is not None
    with Session(athlete.app.state.engine) as db:
        targets = db.execute(
            select(SetLog.target_reps, SetLog.target_weight_kg, SetLog.target_seconds)
        ).all()
        assert len(targets) == 3 and all(t == (None, None, None) for t in targets)
