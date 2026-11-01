"""QA (#49): a coach linked to two athletes cannot reach one athlete's note through the other's
path (404, D84(4)), and notes never leak across athletes in the list or the day view."""

from tests.integration.auth_helpers import problem
from tests.integration.test_authorization_matrix import (
    API,
    World,
    _link,
    _person,
    world,  # noqa: F401  (module fixture reused)
)


def test_a_note_of_another_linked_athlete_is_404_through_the_wrong_path(
    world: World,  # noqa: F811
) -> None:
    kim = _person(world.app, "kim@x.test", "coach")
    hal = _person(world.app, "hal@x.test", "athlete")
    ida = _person(world.app, "ida@x.test", "athlete")
    try:
        for athlete in (hal, ida):
            link = _link(athlete, kim)
            assert kim.client.post(f"{API}/coach-links/{link}/approve").status_code == 200
        hal_url = f"{API}/athletes/{hal.id}/notes"
        ida_url = f"{API}/athletes/{ida.id}/notes"
        body = {"scope": "day", "date": "2026-10-22", "text": "hal only"}
        r = kim.client.post(hal_url, json=body)
        assert r.status_code == 201, r.text
        note_id = r.json()["id"]

        problem(kim.client.put(f"{ida_url}/{note_id}", json={"text": "moved"}), 404, "not_found")
        problem(kim.client.delete(f"{ida_url}/{note_id}"), 404, "not_found")
        assert kim.client.get(ida_url).json()["items"] == []
        assert ida.client.get(f"{API}/athletes/me/notes").json()["items"] == []

        # The note is unchanged and still reachable through the right path.
        listed = hal.client.get(f"{API}/athletes/me/notes").json()["items"]
        assert [(n["id"], n["text"]) for n in listed] == [(note_id, "hal only")]
    finally:
        for person in (kim, hal, ida):
            person.client.__exit__(None, None, None)
