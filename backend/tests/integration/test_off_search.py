"""F6 Open Food Facts search and import against real Postgres and a fake Open Food Facts server:
mapping, cache, flag, degraded mode, import uniqueness, metrics, privacy and authorization."""

import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models import Food
from tests.conftest import Captured, JsonLogs, captured_telemetry, make_settings
from tests.contract import assert_matches_schema
from tests.fake_off import FakeOff, product
from tests.fakes import FakeClock
from tests.integration.auth_helpers import NOW, Api, problem
from tests.integration.test_feature_flags import insert_raw

SEARCH = "/api/v1/foods/search"
IMPORT = "/api/v1/foods/import"
UNAVAILABLE = "Online food search is unavailable — use the library or create a custom food."

YOGURT = product("8410000810004", "Greek yogurt 2%")
OATS = product(
    "5000000000017",
    "Rolled oats",
    brands="Mill Co",
    nutriments={"energy_100g": 1590, "proteins_100g": 13, "carbohydrates_100g": 60, "fat_100g": 7},
    allergens_tags=["en:gluten"],
    ingredients_analysis_tags=["en:vegan"],
)
NO_NUTRITION = product("1234567890", "Mystery yogurt drink", nutriments={})
TOO_RICH = product(
    "1234567891",
    "Impossible yogurt",
    nutriments={
        "energy-kcal_100g": 1200,
        "proteins_100g": 1,
        "carbohydrates_100g": 1,
        "fat_100g": 1,
    },
)
BAD_CODE = product("12ab", "Bad code yogurt")


@pytest.fixture
def off_api(api_factory: Any, fake_off: FakeOff) -> Api:
    fake_off.products = [YOGURT, OATS, NO_NUTRITION, TOO_RICH, BAD_CODE]
    api: Api = api_factory(off_base_url=fake_off.base_url, off_timeout_seconds=0.4)
    assert api.signup().status_code == 201
    return api


def _search(client: TestClient, q: str = "yogurt", **params: Any) -> Any:
    return client.get(SEARCH, params={"q": q, **params})


def _outcomes(captured: Captured) -> dict[str, int]:
    return {
        p.attributes["outcome"]: p.value
        for p in captured.metric_points("fitwise_off_search_total")
        if p.value
    }


def _count(api: Api, code: str) -> int | None:
    with Session(api.app.state.engine) as session:
        return session.scalar(
            select(func.count()).select_from(Food).where(Food.external_code == code)
        )


def _captured_app(database_url: str, fake_off: FakeOff) -> Captured:
    settings = make_settings(database_url, off_base_url=fake_off.base_url, off_timeout_seconds=0.4)
    telemetry, spans, reader = captured_telemetry(settings)
    app = create_app(settings, telemetry)
    app.state.clock = FakeClock(NOW)
    return Captured(app, telemetry, spans, reader)


def test_search_maps_results_and_sends_a_descriptive_user_agent(
    off_api: Api, fake_off: FakeOff
) -> None:
    response = _search(off_api.client)
    assert response.status_code == 200
    body = response.json()
    assert_matches_schema(body, "OffSearchResult")
    assert body["available"] is True
    assert body["unavailable_reason"] is None and body["message"] is None
    # Products without nutrition, with impossible values or with a non-numeric code are skipped.
    assert body["items"] == [
        {
            "code": "8410000810004",
            "name": "Greek yogurt 2%",
            "brand": "Example Dairy",
            "kcal_per_100g": 73,
            "protein_g_per_100g": 9.5,
            "carbs_g_per_100g": 3.6,
            "fat_g_per_100g": 2,
            "imported_food_id": None,
        }
    ]
    (request,) = fake_off.searches()
    assert request.user_agent is not None
    assert request.user_agent.startswith("FitWise/") and "(" in request.user_agent
    assert request.query["search_terms"] == ["yogurt"]


def test_energy_in_kilojoules_is_converted(off_api: Api) -> None:
    items = _search(off_api.client, "oats").json()["items"]
    assert [i["kcal_per_100g"] for i in items] == [380.0]  # 1590 kJ / 4.184


def test_limit_trims_results_from_the_cached_page(off_api: Api, fake_off: FakeOff) -> None:
    fake_off.products = [product(f"90000000{n:04d}", f"Bar {n}") for n in range(30)]
    assert len(_search(off_api.client, "bar").json()["items"]) == 20
    assert len(_search(off_api.client, "bar", limit=5).json()["items"]) == 5
    assert len(fake_off.searches()) == 1


def test_results_are_cached_for_24_hours(off_api: Api, fake_off: FakeOff) -> None:
    first = _search(off_api.client, "Yogurt").json()
    again = _search(off_api.client, "  yogurt ").json()
    assert first == again
    assert len(fake_off.searches()) == 1
    off_api.clock.advance(hours=23, minutes=59)
    assert off_api.login().status_code == 200  # the session itself expires sooner
    _search(off_api.client)
    assert len(fake_off.searches()) == 1
    off_api.clock.advance(minutes=2)
    assert off_api.login().status_code == 200
    assert _search(off_api.client).status_code == 200
    assert len(fake_off.searches()) == 2


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("5xx", "upstream_error"),
        ("garbage", "upstream_error"),
        ("wrong_shape", "upstream_error"),
        ("slow", "timeout"),
    ],
)
def test_upstream_failure_is_a_handled_unavailable_response_not_a_500(
    off_api: Api, fake_off: FakeOff, mode: str, reason: str
) -> None:
    fake_off.mode = mode
    fake_off.delay = 1.0
    response = _search(off_api.client)
    assert response.status_code == 200
    body = response.json()
    assert_matches_schema(body, "OffSearchResult")
    assert body == {
        "available": False,
        "unavailable_reason": reason,
        "message": UNAVAILABLE,
        "items": [],
    }


def test_connection_refused_is_unavailable(api: Api) -> None:
    # off_base_url defaults to a port nothing listens on in tests.
    assert api.signup().status_code == 201
    body = _search(api.client).json()
    assert body["available"] is False and body["unavailable_reason"] == "upstream_error"


def test_failures_are_not_cached_and_search_recovers(off_api: Api, fake_off: FakeOff) -> None:
    fake_off.mode = "5xx"
    assert _search(off_api.client).json()["available"] is False
    fake_off.mode = "ok"
    assert _search(off_api.client).json()["available"] is True
    assert len(fake_off.searches()) == 2


def test_flag_off_disables_search_without_calling_upstream(off_api: Api, fake_off: FakeOff) -> None:
    insert_raw(off_api.app.state.engine, "off_search_enabled", "false")
    body = _search(off_api.client).json()
    assert body == {
        "available": False,
        "unavailable_reason": "disabled",
        "message": UNAVAILABLE,
        "items": [],
    }
    assert fake_off.requests == []
    # The rest of the foods API keeps working.
    assert off_api.client.get("/api/v1/foods").status_code == 200


def test_import_stores_the_product_once_and_reuses_it(off_api: Api, fake_off: FakeOff) -> None:
    assert _search(off_api.client).status_code == 200
    first = off_api.client.post(IMPORT, json={"code": YOGURT["code"]})
    assert first.status_code == 201, first.text
    food = first.json()
    assert_matches_schema(food, "Food")
    assert food["source"] == "openfoodfacts"
    assert food["external_code"] == "8410000810004"
    assert food["owner"] is None
    assert food["brand"] == "Example Dairy"
    assert food["diet_tags"] == ["vegetarian", "pescatarian"]
    assert food["allergen_tags"] == ["lactose"]
    assert (food["kcal_per_100g"], food["protein_g_per_100g"]) == (73, 9.5)

    second = off_api.client.post(IMPORT, json={"code": YOGURT["code"]})
    assert second.status_code == 200
    assert second.json() == food
    assert _count(off_api, YOGURT["code"]) == 1
    # Imported from the search cache: no product lookup upstream, and none for the repeat.
    assert fake_off.lookups() == []

    items = _search(off_api.client).json()["items"]
    assert items[0]["imported_food_id"] == food["id"]
    listed = off_api.client.get("/api/v1/foods", params={"source": "openfoodfacts"}).json()
    assert [f["id"] for f in listed["items"]] == [food["id"]]


def test_import_without_a_prior_search_looks_the_product_up(
    off_api: Api, fake_off: FakeOff
) -> None:
    response = off_api.client.post(IMPORT, json={"code": OATS["code"]})
    assert response.status_code == 201
    assert response.json()["diet_tags"] == ["vegan", "vegetarian", "pescatarian"]
    assert len(fake_off.lookups()) == 1


def test_concurrent_imports_create_one_food(off_api: Api) -> None:
    clients = []
    for _ in range(6):
        client = off_api.new_client()
        client.cookies.update(off_api.client.cookies)
        clients.append(client)
    codes: list[int] = []

    def go(client: TestClient) -> None:
        codes.append(client.post(IMPORT, json={"code": YOGURT["code"]}).status_code)

    threads = [threading.Thread(target=go, args=(c,)) for c in clients]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert codes.count(201) == 1
    assert set(codes) == {200, 201}
    assert _count(off_api, YOGURT["code"]) == 1


def test_import_of_an_imported_food_works_while_the_flag_is_off(off_api: Api) -> None:
    assert off_api.client.post(IMPORT, json={"code": YOGURT["code"]}).status_code == 201
    insert_raw(off_api.app.state.engine, "off_search_enabled", "false")
    off_api.clock.advance(minutes=1)  # past the flag cache TTL
    assert off_api.client.post(IMPORT, json={"code": YOGURT["code"]}).status_code == 200


def test_import_of_an_unknown_product_is_404(off_api: Api) -> None:
    problem(off_api.client.post(IMPORT, json={"code": "99999999"}), 404, "not_found")


def test_import_of_an_unusable_product_is_404(off_api: Api) -> None:
    problem(off_api.client.post(IMPORT, json={"code": TOO_RICH["code"]}), 404, "not_found")
    assert _count(off_api, TOO_RICH["code"]) == 0


@pytest.mark.parametrize("mode", ["5xx", "slow", "garbage"])
def test_import_of_an_uncached_product_while_upstream_is_down_is_503(
    off_api: Api, fake_off: FakeOff, mode: str
) -> None:
    fake_off.mode = mode
    fake_off.delay = 1.0
    response = off_api.client.post(IMPORT, json={"code": YOGURT["code"]})
    body = problem(response, 503, "off_unavailable")
    assert body["detail"] == UNAVAILABLE


def test_import_with_upstream_down_still_uses_the_cached_search_result(
    off_api: Api, fake_off: FakeOff
) -> None:
    _search(off_api.client)
    fake_off.mode = "5xx"
    assert off_api.client.post(IMPORT, json={"code": YOGURT["code"]}).status_code == 201


def test_import_of_a_new_product_while_the_flag_is_off_is_503(
    off_api: Api, fake_off: FakeOff
) -> None:
    insert_raw(off_api.app.state.engine, "off_search_enabled", "false")
    problem(off_api.client.post(IMPORT, json={"code": YOGURT["code"]}), 503, "off_unavailable")
    assert fake_off.requests == []


@pytest.mark.parametrize("code", ["abc", "123", "123456789012345", "", "12 345"])
def test_import_validates_the_code(off_api: Api, code: str) -> None:
    assert off_api.client.post(IMPORT, json={"code": code}).status_code == 422


def test_import_rejects_unknown_fields(off_api: Api) -> None:
    response = off_api.client.post(IMPORT, json={"code": YOGURT["code"], "name": "x"})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "params",
    [{}, {"q": "a"}, {"q": "x" * 101}, {"q": "ok", "limit": 0}, {"q": "ok", "limit": 51}],
)
def test_search_validates_parameters(
    off_api: Api, fake_off: FakeOff, params: dict[str, Any]
) -> None:
    problem(off_api.client.get(SEARCH, params=params), 400, "bad_request")
    assert fake_off.requests == []


def test_search_and_import_need_a_session(api: Api, fake_off: FakeOff) -> None:
    problem(api.client.get(SEARCH, params={"q": "yogurt"}), 401, "not_authenticated")
    problem(api.client.post(IMPORT, json={"code": "8410000810004"}), 401, "not_authenticated")
    assert fake_off.requests == []


def test_a_coach_can_import_and_the_food_is_shared(off_api: Api) -> None:
    coach = off_api.new_client()
    body = {
        "email": "coach@x.test",
        "password": "correct-horse-battery",
        "display_name": "Coach",
        "role": "coach",
        "birth_date": "1985-01-01",
        "units": "metric",
        "timezone": "Europe/Madrid",
        "accept_disclaimer": True,
    }
    assert coach.post("/api/v1/auth/signup", json=body).status_code == 201
    imported = coach.post(IMPORT, json={"code": YOGURT["code"]})
    assert imported.status_code == 201
    # Imported foods have no owner: every user sees the same row, and importing again returns it.
    again = off_api.client.post(IMPORT, json={"code": YOGURT["code"]})
    assert again.status_code == 200 and again.json()["id"] == imported.json()["id"]
    listed = off_api.client.get("/api/v1/foods", params={"source": "openfoodfacts"}).json()
    assert [f["id"] for f in listed["items"]] == [imported.json()["id"]]


def test_search_metric_counts_each_outcome(migrated_database_url: str, fake_off: FakeOff) -> None:
    captured = _captured_app(migrated_database_url, fake_off)
    fake_off.products = [YOGURT]
    with TestClient(captured.app) as client:
        api = Api(app=captured.app, client=client, clock=captured.app.state.clock)
        assert api.signup().status_code == 201
        _search(client)  # ok (upstream)
        _search(client)  # ok (cache)
        fake_off.mode = "5xx"
        _search(client, "other")  # error
        fake_off.mode = "slow"
        fake_off.delay = 1.0
        _search(client, "another")  # timeout
        insert_raw(captured.app.state.engine, "off_search_enabled", "false")
        api.clock.advance(minutes=1)
        _search(client)  # disabled
    assert _outcomes(captured) == {"ok": 2, "error": 1, "timeout": 1, "disabled": 1}


def test_trickled_response_ends_at_the_total_deadline_and_counts_as_timeout(
    migrated_database_url: str, fake_off: FakeOff
) -> None:
    # Every chunk arrives well inside the 0.4 s per-phase limit, but the body takes 4 s in total.
    captured = _captured_app(migrated_database_url, fake_off)
    fake_off.products = [YOGURT]
    fake_off.mode = "trickle"
    fake_off.delay = 4.0
    with TestClient(captured.app) as client:
        api = Api(app=captured.app, client=client, clock=captured.app.state.clock)
        assert api.signup().status_code == 201
        started = time.monotonic()
        response = _search(client)
        elapsed = time.monotonic() - started
    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "unavailable_reason": "timeout",
        "message": UNAVAILABLE,
        "items": [],
    }
    assert 0.3 <= elapsed < 1.5
    assert _outcomes(captured) == {"timeout": 1}


def test_trickled_import_lookup_is_also_bounded(off_api: Api, fake_off: FakeOff) -> None:
    fake_off.mode = "trickle"
    fake_off.delay = 4.0
    started = time.monotonic()
    response = off_api.client.post(IMPORT, json={"code": YOGURT["code"]})
    assert time.monotonic() - started < 1.5
    problem(response, 503, "off_unavailable")


def test_all_outcome_series_exist_from_the_start(captured: Captured) -> None:
    series = {p.attributes["outcome"] for p in captured.metric_points("fitwise_off_search_total")}
    assert series == {"ok", "error", "timeout", "disabled"}


def test_nothing_the_user_searched_reaches_logs_or_spans(
    migrated_database_url: str, fake_off: FakeOff, json_logs: JsonLogs
) -> None:
    captured = _captured_app(migrated_database_url, fake_off)
    fake_off.mode = "5xx"
    with TestClient(captured.app) as client:
        api = Api(app=captured.app, client=client, clock=captured.app.state.clock)
        assert api.signup().status_code == 201
        assert _search(client, "zebra-secret-snack").json()["available"] is False
        fake_off.mode = "slow"
        fake_off.delay = 1.0
        assert _search(client, "zebra-secret-snack-2").json()["available"] is False
    exported = repr([dict(s.attributes or {}) for s in captured.spans()])
    assert "zebra" not in json_logs.text
    assert "zebra" not in exported
    assert json_logs.with_message("open food facts request failed")
