from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from responder.app import create_app
from responder.config import ConfigError, Settings
from responder.store import IncidentStore
from tests.conftest import (
    AUTH,
    EMAIL_LINE,
    PASSWORD,
    StubBackends,
    fixture,
    incident_dirs,
    responder_of,
)


def launched(launcher_log: Path) -> list[str]:
    return launcher_log.read_text().split() if launcher_log.exists() else []


def test_firing_returns_2xx_and_opens_incident(
    client: TestClient, settings: Settings, launcher_log: Path
) -> None:
    response = client.post("/alerts", json=fixture("firing"))
    assert response.status_code == 202
    responder_of(client).wait()
    dirs = incident_dirs(settings)
    assert len(dirs) == 1
    assert launched(launcher_log) == [dirs[0].name]


def test_response_within_1s_even_when_launcher_is_slow(
    settings: Settings, make_client: Callable[[Settings], TestClient], tmp_path: Path
) -> None:
    done = tmp_path / "done"
    slow = replace(
        settings,
        launcher_cmd=("sh", "-c", f"sleep 3; touch {done}", "launcher"),
    )
    client = make_client(slow)
    started = time.monotonic()
    response = client.post("/alerts", json=fixture("firing"))
    elapsed = time.monotonic() - started
    assert response.status_code == 202
    assert elapsed < 1.0
    assert not done.exists()  # the hook is still running in the background
    responder_of(client).wait()
    assert done.exists()


def test_test_notification_is_a_noop(
    client: TestClient, settings: Settings, launcher_log: Path, stubs: StubBackends
) -> None:
    response = client.post("/alerts", json=fixture("test_notification"))
    assert 200 <= response.status_code < 300
    responder_of(client).wait()
    assert incident_dirs(settings) == []
    assert launched(launcher_log) == []
    assert stubs.requests == []


def test_duplicate_firing_does_not_start_second_incident(
    client: TestClient, settings: Settings, launcher_log: Path
) -> None:
    for _ in range(3):
        assert client.post("/alerts", json=fixture("firing")).status_code == 202
    responder_of(client).wait()
    assert len(incident_dirs(settings)) == 1
    assert len(launched(launcher_log)) == 1


def test_resolved_closes_and_new_firing_opens_new_incident(
    client: TestClient, settings: Settings, launcher_log: Path
) -> None:
    client.post("/alerts", json=fixture("firing"))
    responder_of(client).wait()
    assert client.post("/alerts", json=fixture("resolved")).status_code == 202
    (first,) = incident_dirs(settings)
    meta = json.loads((first / "incident.json").read_text())
    assert meta["closed_at"] is not None
    assert not (settings.incidents_dir / "open" / "9d1f0c2a7b3e4a55").exists()

    time.sleep(1.1)  # ids carry a one second timestamp
    client.post("/alerts", json=fixture("firing"))
    responder_of(client).wait()
    assert len(incident_dirs(settings)) == 2
    assert len(launched(launcher_log)) == 2


def test_resolved_without_open_incident_is_harmless(client: TestClient, settings: Settings) -> None:
    assert client.post("/alerts", json=fixture("resolved")).status_code == 202
    assert incident_dirs(settings) == []


def test_open_state_survives_restart(
    settings: Settings, make_client: Callable[[Settings], TestClient], launcher_log: Path
) -> None:
    first = make_client(settings)
    first.post("/alerts", json=fixture("firing"))
    responder_of(first).wait()
    first.close()

    restarted = make_client(settings)  # new process state, same incidents/ directory
    restarted.post("/alerts", json=fixture("firing"))
    responder_of(restarted).wait()
    assert len(incident_dirs(settings)) == 1
    assert len(launched(launcher_log)) == 1

    restarted.post("/alerts", json=fixture("resolved"))
    again = make_client(settings)
    again.post("/alerts", json=fixture("firing"))
    responder_of(again).wait()
    assert len(incident_dirs(settings)) == 2


def test_context_files_written(client: TestClient, settings: Settings, stubs: StubBackends) -> None:
    client.post("/alerts", json=fixture("firing"))
    responder_of(client).wait()
    (incident,) = incident_dirs(settings)
    names = {p.name for p in incident.iterdir()}
    assert {
        "alert.json",
        "prometheus.json",
        "loki.json",
        "tempo.json",
        "capture.json",
        "incident.json",
    } <= names
    alert = json.loads((incident / "alert.json").read_text())
    assert alert["fingerprint"] == "9d1f0c2a7b3e4a55"
    assert alert["labels"]["alertname"] == "KeyJourneyErrors"
    prom = json.loads((incident / "prometheus.json").read_text())
    assert set(prom) == {"error_requests_5xx", "all_requests", "p95_latency_seconds"}
    assert 'route="/api/v1/sessions/{session_id}/finish"' in prom["all_requests"]["query"]
    assert json.loads((incident / "tempo.json").read_text()) == {"trace_ids": ["abc123", "def456"]}
    assert json.loads((incident / "capture.json").read_text()) == {
        "prometheus": "ok",
        "loki": "ok",
        "tempo": "ok",
    }
    # The alert window comes from startsAt (2026-10-24T10:00:00Z) minus the lookback.
    starts = [q["start"][0] for path, q in stubs.requests if path == "/api/v1/query_range"]
    assert float(starts[0]) == 1792836000 - 900


@pytest.mark.parametrize("down", ["prometheus", "loki", "tempo"])
def test_partial_backend_failure_is_recorded_and_others_written(
    down: str, client: TestClient, settings: Settings, stubs: StubBackends, launcher_log: Path
) -> None:
    stubs.down.add(down)
    client.post("/alerts", json=fixture("firing"))
    responder_of(client).wait()
    (incident,) = incident_dirs(settings)
    capture = json.loads((incident / "capture.json").read_text())
    assert capture[down] == "failed: HTTP 503"
    for name in {"prometheus", "loki", "tempo"} - {down}:
        assert capture[name] == "ok"
        assert (incident / f"{name}.json").exists()
    assert not (incident / f"{down}.json").exists()
    assert launched(launcher_log) == [incident.name]  # the launcher still runs


def test_unreachable_backend_is_recorded(
    settings: Settings, make_client: Callable[[Settings], TestClient]
) -> None:
    client = make_client(replace(settings, tempo_url="http://127.0.0.1:1"))
    client.post("/alerts", json=fixture("firing"))
    responder_of(client).wait()
    (incident,) = incident_dirs(settings)
    capture = json.loads((incident / "capture.json").read_text())
    assert capture["tempo"].startswith("failed: ")
    assert capture["loki"] == "ok"


def test_loki_results_stored_as_returned(client: TestClient, settings: Settings) -> None:
    """The responder does not filter: logs are allow-listed at the source (README, spec §6.5)."""
    client.post("/alerts", json=fixture("firing"))
    responder_of(client).wait()
    (incident,) = incident_dirs(settings)
    loki = json.loads((incident / "loki.json").read_text())
    assert loki["result"]["data"]["result"][0]["values"][0][1] == EMAIL_LINE


def test_default_launcher_is_a_noop_that_logs(
    settings: Settings,
    make_client: Callable[[Settings], TestClient],
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = make_client(replace(settings, launcher_cmd=()))
    client.post("/alerts", json=fixture("firing"))
    responder_of(client).wait()
    assert "launcher_noop" in capsys.readouterr().out


def test_logs_carry_no_alert_content(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    client.post("/alerts", json=fixture("firing"))
    responder_of(client).wait()
    client.post("/alerts", json=fixture("test_notification"))
    out = capsys.readouterr().out
    assert "incident_opened" in out and "test_notification" in out
    for secret in (PASSWORD, "More than 5 %", "sessions", "runbook"):
        assert secret not in out
    for line in out.splitlines():
        json.loads(line)


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer abc"},
        {"Authorization": "Basic !!notbase64"},
        {"Authorization": "Basic Z3JhZmFuYTp3cm9uZw=="},  # grafana:wrong
        {"Authorization": "Basic d3Jvbmc6dGVzdC1wYXNzd29yZA=="},  # wrong:test-password
    ],
)
def test_unauthenticated_calls_get_401(
    headers: dict[str, str], client: TestClient, settings: Settings, launcher_log: Path
) -> None:
    client.headers.clear()
    response = client.post("/alerts", json=fixture("firing"), headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")
    assert incident_dirs(settings) == []
    assert launched(launcher_log) == []


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"{}",
        b'{"alerts": "x"}',
        b'{"alerts": [1]}',
        b'{"alerts": [{"status": "firing", "fingerprint": "../../etc"}]}',
        b'{"alerts": [{"status": "firing"}]}',
    ],
)
def test_malformed_payload_is_400(body: bytes, client: TestClient, settings: Settings) -> None:
    response = client.post("/alerts", content=body)
    assert response.status_code == 400
    assert incident_dirs(settings) == []


def test_missing_password_fails_closed() -> None:
    with pytest.raises(ConfigError):
        Settings.from_env({})


def test_loki_query_uses_level_label_not_line_text(
    client: TestClient, stubs: StubBackends, settings: Settings
) -> None:
    client.post("/alerts", json=fixture("firing"))
    responder_of(client).wait()
    assert stubs.bad_queries == []
    (incident,) = incident_dirs(settings)
    assert json.loads((incident / "capture.json").read_text())["loki"] == "ok"


@pytest.mark.parametrize("key", ["labels", "annotations"])
@pytest.mark.parametrize("value", [["x"], [], "", 0, False, "text", 5])
def test_labels_or_annotations_not_object_is_400(
    key: str, value: object, client: TestClient, settings: Settings
) -> None:
    body = fixture("firing")
    body["alerts"][0][key] = value
    assert client.post("/alerts", json=body).status_code == 400
    assert incident_dirs(settings) == []


@pytest.mark.parametrize("key", ["labels", "annotations"])
@pytest.mark.parametrize("missing", [True, False], ids=["missing", "null"])
def test_missing_or_null_labels_or_annotations_are_accepted(
    key: str, missing: bool, client: TestClient, settings: Settings
) -> None:
    body = fixture("firing")
    if missing:
        del body["alerts"][0][key]
    else:
        body["alerts"][0][key] = None
    assert client.post("/alerts", json=body).status_code == 202
    responder_of(client).wait()
    assert len(incident_dirs(settings)) == 1


def test_finished_tasks_are_dropped(client: TestClient) -> None:
    for fp in ("aaa", "bbb", "ccc"):
        body = fixture("firing")
        body["alerts"][0]["fingerprint"] = fp
        client.post("/alerts", json=body)
    responder_of(client).wait()
    deadline = time.monotonic() + 2
    while responder_of(client).futures and time.monotonic() < deadline:
        time.sleep(0.01)
    assert responder_of(client).futures == set()


def test_restart_relaunches_incident_whose_launcher_never_ran(
    settings: Settings, launcher_log: Path
) -> None:
    # A crash after the incident was opened, before the launcher ran: marker and alert.json only.
    store = IncidentStore(settings.incidents_dir)
    incident = store.open_incident("9d1f0c2a7b3e4a55")
    assert incident is not None
    alert = fixture("firing")["alerts"][0]
    (incident.path / "alert.json").write_text(json.dumps(alert))

    with TestClient(create_app(settings), headers=AUTH) as restarted:  # startup resumes it
        responder_of(restarted).wait()
    assert launched(launcher_log) == [incident.id]
    assert (incident.path / "launched").exists()
    assert len(incident_dirs(settings)) == 1

    with TestClient(create_app(settings), headers=AUTH) as again:  # already launched: left alone
        responder_of(again).wait()
    assert launched(launcher_log) == [incident.id]


@pytest.mark.parametrize("content", ["{not json", "[1, 2]", ""])
def test_resume_skips_corrupt_alert_json(
    content: str, settings: Settings, launcher_log: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = IncidentStore(settings.incidents_dir)
    broken = store.open_incident("badbadbad")
    good = store.open_incident("9d1f0c2a7b3e4a55")
    assert broken is not None and good is not None
    (broken.path / "alert.json").write_text(content)
    (good.path / "alert.json").write_text(json.dumps(fixture("firing")["alerts"][0]))

    with TestClient(create_app(settings), headers=AUTH) as restarted:  # must not crash startup
        responder_of(restarted).wait()
    assert launched(launcher_log) == [good.id]
    assert "incident_resume_skipped" in capsys.readouterr().out
