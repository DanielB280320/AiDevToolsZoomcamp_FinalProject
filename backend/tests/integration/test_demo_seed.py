"""#51 `make seed-demo`: counts, charts and coach dashboard populated, sign-in, idempotency,
partial-run recovery, and the prod refusal. The seed runs through the real services against
real Postgres, with the fixed clock of the other integration tests."""

import datetime as dt
import json
import secrets
from collections.abc import Iterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cli import seed_demo as cli
from app.config import Settings
from app.demo_seed import (
    ATHLETE_EMAIL,
    COACH_EMAIL,
    DEMO_PASSWORD,
    HISTORY_DAYS,
    TIMEZONE,
    DemoCounts,
    counts,
    seed_demo,
)
from app.models import Base, CoachLink, Suggestion, User
from app.seed import run_seed
from app.services.clock import local_today
from app.telemetry import build_telemetry
from tests.contract import assert_matches_schema
from tests.integration.auth_helpers import NOW, Api


def telemetry() -> object:
    return build_telemetry(
        Settings(
            database_url="postgresql://u:p@127.0.0.1:9/x",  # type: ignore[arg-type]
            jwt_secret=secrets.token_urlsafe(32),  # type: ignore[arg-type]
            otel_exporter_otlp_endpoint=None,
            _env_file=None,
        )
    )


@pytest.fixture
def seeded(api: Api) -> Iterator[tuple[Api, DemoCounts]]:
    with Session(api.app.state.engine) as db:
        run_seed(db)  # the catalogue the migration step loads
        result, wrote = seed_demo(db, NOW, telemetry())  # type: ignore[arg-type]
        assert wrote
    yield api, result


def row_counts(api: Api) -> dict[str, int]:
    engine = api.app.state.engine
    with engine.connect() as conn:
        return {
            t.name: conn.execute(select(func.count()).select_from(t)).scalar_one()
            for t in Base.metadata.sorted_tables
        }


def check_counts_meet_the_acceptance_numbers(seeded: tuple[Api, DemoCounts]) -> None:
    _, c = seeded
    assert c.users == 2
    assert c.sessions_done >= 20
    assert c.set_logs >= c.sessions_done * 3
    assert c.meal_log_days >= 40
    assert c.weigh_ins >= 8
    assert c.activities >= 1
    assert c.suggestions_pending >= 1 and c.suggestions_decided >= 1


def check_history_has_partial_and_missed_sessions_and_an_active_link(
    seeded: tuple[Api, DemoCounts],
) -> None:
    api, _ = seeded
    with Session(api.app.state.engine) as db:
        athlete = db.scalars(select(User).where(User.email == ATHLETE_EMAIL)).one()
        coach = db.scalars(select(User).where(User.email == COACH_EMAIL)).one()
        today = local_today(NOW, TIMEZONE)
        # Done with completion < 1 (partial), and planned in the past (missed).
        from app.models import TrainingSession

        done = db.scalars(
            select(TrainingSession).where(
                TrainingSession.athlete_id == athlete.id, TrainingSession.status == "done"
            )
        ).all()
        assert any(s.completion is not None and s.completion < 1 for s in done)
        missed = db.scalar(
            select(func.count(TrainingSession.id)).where(
                TrainingSession.athlete_id == athlete.id,
                TrainingSession.status == "planned",
                TrainingSession.date < today,
            )
        )
        assert missed and missed >= 1
        assert min(s.date for s in done) >= today - dt.timedelta(days=HISTORY_DAYS)
        link = db.scalars(select(CoachLink)).one()
        assert (link.coach_id, link.athlete_id, link.status) == (coach.id, athlete.id, "active")
        assert db.scalar(select(func.count(Suggestion.id)).where(Suggestion.kind == "recalc")) == 0


def check_charts_are_populated(seeded: tuple[Api, DemoCounts]) -> None:
    api, _ = seeded
    assert api.login(ATHLETE_EMAIL, DEMO_PASSWORD).status_code == 200
    today = local_today(NOW, TIMEZONE)
    base = "/api/v1/athletes/me/charts"
    # `weeks` accepts 4, 12, 26 or 52 (check_weeks); 12 covers the 8 weeks of history.
    adherence = api.client.get(
        f"{base}/adherence",
        params={"from": str(today - dt.timedelta(days=HISTORY_DAYS - 1)), "to": str(today)},
    )
    assert adherence.status_code == 200, adherence.text
    assert_matches_schema(adherence.json(), "AdherenceChart")
    assert adherence.json()["days"] and len(adherence.json()["weeks"]) >= 8
    assert any(d["training_completion"] is not None for d in adherence.json()["days"])

    for week_start in ("2026-10-12", "2026-10-19"):
        summary = api.client.get(f"{base}/weekly-summary", params={"week_start": week_start})
        assert summary.status_code == 200, summary.text
        body = summary.json()
        assert_matches_schema(body, "WeeklySummary")
        assert body["sessions_planned"] > 0 and body["avg_completion"] is not None
        assert body["sparklines"]["daily_balance_kcal"]

    chart = api.client.get(f"{base}/body", params={"weeks": 12})
    assert chart.status_code == 200, chart.text
    assert_matches_schema(chart.json(), "BodyChart")
    assert sum(p["weight_kg"] is not None for p in chart.json()["points"]) >= 8


def check_coach_dashboard_shows_the_athlete_with_adherence(seeded: tuple[Api, DemoCounts]) -> None:
    api, _ = seeded
    assert api.login(COACH_EMAIL, DEMO_PASSWORD).status_code == 200
    response = api.client.get("/api/v1/coach/athletes")
    assert response.status_code == 200, response.text
    assert_matches_schema(response.json(), "CoachAthleteList")
    (item,) = response.json()["items"]
    assert item["training_adherence_7d"] is not None
    assert item["athlete"]["display_name"] == "Demo Athlete"


def check_demo_credentials_sign_in_and_stranger_is_denied(seeded: tuple[Api, DemoCounts]) -> None:
    api, _ = seeded
    athlete = api.login(ATHLETE_EMAIL, DEMO_PASSWORD)
    assert athlete.status_code == 200
    assert athlete.json()["role"] == "athlete"
    assert (
        api.new_client()
        .post("/api/v1/auth/login", json={"email": ATHLETE_EMAIL, "password": "wrong-password-1"})
        .status_code
        == 401
    )


def test_seeded_demo_meets_every_acceptance_check(seeded: tuple[Api, DemoCounts]) -> None:
    """One seed, many checks: seeding runs the whole app logic for 8 weeks, so it is done once."""
    check_counts_meet_the_acceptance_numbers(seeded)
    check_history_has_partial_and_missed_sessions_and_an_active_link(seeded)
    check_demo_credentials_sign_in_and_stranger_is_denied(seeded)
    check_charts_are_populated(seeded)
    check_coach_dashboard_shows_the_athlete_with_adherence(seeded)


def test_second_run_keeps_row_counts_and_ids(seeded: tuple[Api, DemoCounts]) -> None:
    api, first = seeded
    before = row_counts(api)
    with Session(api.app.state.engine) as db:
        ids = sorted(db.scalars(select(User.id).where(User.email.like("demo.%"))))
        again, wrote = seed_demo(db, NOW + dt.timedelta(days=3), telemetry())  # type: ignore[arg-type]
        assert not wrote and again == first
        assert sorted(db.scalars(select(User.id).where(User.email.like("demo.%")))) == ids
    assert row_counts(api) == before


def test_half_built_demo_is_rebuilt_not_duplicated(api: Api) -> None:
    from app.demo_seed import _sign_up

    with Session(api.app.state.engine) as db:
        run_seed(db)
        _sign_up(db, COACH_EMAIL, "Demo Coach", "coach", NOW)  # a run that died after step 1
        result, wrote = seed_demo(db, NOW, telemetry())  # type: ignore[arg-type]
        assert wrote and result.users == 2
        assert counts(db) == result
        assert db.scalar(select(func.count(User.id)).where(User.email.like("demo.%"))) == 2


def test_cli_refuses_in_prod(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@127.0.0.1:9/x")
    for name in ("APP_ENV", "FITWISE_ENV"):
        monkeypatch.delenv("APP_ENV", raising=False)
        monkeypatch.delenv("FITWISE_ENV", raising=False)
        monkeypatch.setenv(name, "prod")
        assert cli.main() == 1
        assert "refuses to run in prod" in capsys.readouterr().err


def test_cli_run_prints_counts_and_logs_no_health_data(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    json_logs: object,
) -> None:
    from sqlalchemy import create_engine

    engine = create_engine(migrated_database_url)
    with Session(engine) as db:
        run_seed(db)
    engine.dispose()
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_CONNECT_TIMEOUT_SECONDS", "30")  # a loaded CI host
    monkeypatch.delenv("FITWISE_ENV", raising=False)
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "demo data created" in out and ATHLETE_EMAIL in out
    assert cli.main() == 0  # second run
    assert "already present" in capsys.readouterr().out
    logs = json_logs.text  # type: ignore[attr-defined]
    lines = [json.loads(line) for line in logs.splitlines() if line]
    counted = [line for line in lines if line["message"] == "demo seed counts"]
    assert counted and all(isinstance(line["count"], int) for line in counted)
    for secret in (ATHLETE_EMAIL, COACH_EMAIL, DEMO_PASSWORD, "Demo Athlete"):
        assert secret not in logs
