"""#43 F15: every chart endpoint answers in under 500 ms (p95) with one year of seeded data.

The test seeds the year itself (3 sessions a week with sets, 3 meal logs a day with items, a
weigh-in every day, an extra activity every 5th day) and times each endpoint 25 times through the
full ASGI stack and Postgres. Run `pytest -s tests/integration/test_charts_perf.py` to see the
numbers. Timing tests can be noisy on a loaded machine: rerun on its own before suspecting code.

Marked `perf`: `make test-backend` skips it (`-m "not perf"`) so a noisy runner cannot fail the
build; CI runs it in the non-blocking `backend-perf` job and `make test-backend-perf` runs it alone.
"""

import datetime as dt
import statistics
import time
from typing import Any

import pytest
from sqlalchemy.orm import Session

from tests.integration.auth_helpers import Api
from tests.integration.chart_data import (
    WEEKDAYS,
    add_activity,
    add_meals,
    add_session,
    add_weight,
    seed_plan,
)

TODAY = dt.date(2026, 10, 22)
P95_LIMIT_S = 0.5
RUNS = 25


def p95(samples: list[float]) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))]


@pytest.fixture
def year(api: Api) -> tuple[Api, dict[str, Any]]:
    seed = seed_plan(api, days_ago=400)
    start = TODAY - dt.timedelta(days=364)
    last_session = None
    with Session(api.app.state.engine) as db:
        for n in range(365):
            day = start + dt.timedelta(days=n)
            if WEEKDAYS[day.weekday()] in ("mon", "thu", "fri"):
                weight = 50 + (n % 7)
                last_session = add_session(
                    db,
                    seed,
                    day,
                    sets=[(8, weight, 8, 50), (8, weight, 8, 50), (7, weight, 8, 50)],
                    timed_seconds=500 + n,
                    completion=0.85,
                )
            add_meals(db, seed, day, ("eaten", "adjusted", "eaten"))
            add_weight(db, seed, day, 80 - n / 100, fat=18.0 if n % 7 == 0 else None)
            if n % 5 == 0:
                add_activity(db, seed, day)
        db.commit()
        assert last_session is not None
        ids = {"sid": str(last_session.id), "ex": str(seed.strength_id)}
    return api, ids


@pytest.mark.perf
def test_every_chart_endpoint_p95_is_under_500_ms_with_a_year_of_data(
    year: tuple[Api, dict[str, Any]],
) -> None:
    api, ids = year
    base = "/api/v1/athletes/me/charts"
    start = (TODAY - dt.timedelta(days=370)).isoformat()
    requests: dict[str, tuple[str, dict[str, str | int]]] = {
        "session": (f"{base}/session/{ids['sid']}", {}),
        "exercise 52w": (f"{base}/exercise/{ids['ex']}", {"weeks": 52}),
        "adherence 371d": (f"{base}/adherence", {"from": start, "to": TODAY.isoformat()}),
        "weekly-summary": (f"{base}/weekly-summary", {}),
        "body 52w": (f"{base}/body", {"weeks": 52}),
    }
    for name, (path, params) in requests.items():
        first = api.client.get(path, params=params)
        assert first.status_code == 200, (name, first.text)
        samples = []
        for _ in range(RUNS):
            began = time.perf_counter()
            assert api.client.get(path, params=params).status_code == 200
            samples.append(time.perf_counter() - began)
        print(  # noqa: T201 - evidence for the PR (`pytest -s`)
            f"{name:16s} p50={statistics.median(samples) * 1000:6.1f} ms  "
            f"p95={p95(samples) * 1000:6.1f} ms  max={max(samples) * 1000:6.1f} ms"
        )
        assert p95(samples) < P95_LIMIT_S, name
    body = api.client.get(requests["exercise 52w"][0], params={"weeks": 52}).json()
    assert len(body["points"]) > 100  # the year really was seeded
