"""The payload checks of the fires-and-resolves test (#97) agree with the provisioned rules.

`observability/alert-test/driver.py` validates what Grafana's webhook delivers. These tests build
payloads from the real annotations in `rules.yaml` (templates rendered by hand) so a change to a
rule that the driver would reject fails here, long before the 30-minute live run.
"""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

OBS = Path(__file__).resolve().parents[3] / "observability"
ROUTE = "/api/v1/sessions/{session_id}/sets"


def _driver() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "alert_test_driver", OBS / "alert-test" / "driver.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(alertname: str, status: str) -> dict[str, Any]:
    rules = yaml.safe_load((OBS / "grafana/provisioning/alerting/rules.yaml").read_text())
    rule = next(r for r in rules["groups"][0]["rules"] if r["title"] == alertname)
    notes = {
        k: v.replace("{{ .Labels.route }}", ROUTE).replace("{{ externalURL }}", "http://grafana/")
        for k, v in rule["annotations"].items()
    }
    alert = {
        "status": status,
        "labels": {"alertname": alertname, **rule["labels"], "route": ROUTE},
        "annotations": notes,
        "startsAt": "2026-10-25T10:00:00Z",
        "endsAt": "2026-10-25T10:20:00Z" if status == "resolved" else "0001-01-01T00:00:00Z",
    }
    return {"status": status, "alerts": [alert]}


@pytest.mark.parametrize("alertname", ["KeyJourneyErrors", "KeyJourneyLatency"])
@pytest.mark.parametrize("status", ["firing", "resolved"])
def test_payload_built_from_the_rules_passes(alertname: str, status: str) -> None:
    assert _driver().check_payload(_payload(alertname, status), alertname, status) == []


def test_payload_problems_are_reported() -> None:
    driver = _driver()
    payload = _payload("KeyJourneyErrors", "firing")
    alert = payload["alerts"][0]
    alert["labels"]["env"] = "dev"
    del alert["annotations"]["runbook_url"]
    problems = driver.check_payload(payload, "KeyJourneyErrors", "resolved")
    assert len(problems) >= 4
    assert driver.check_payload(payload, "KeyJourneyLatency", "firing") == [
        "no alert named KeyJourneyLatency"
    ]


def test_alert_older_than_the_fault_is_rejected() -> None:
    driver = _driver()
    payload = _payload("KeyJourneyLatency", "firing")  # startsAt 10:00:00
    after = driver.parse_time("2026-10-25T10:05:00Z")
    before = driver.parse_time("2026-10-25T09:59:00Z")
    assert driver.check_payload(payload, "KeyJourneyLatency", "firing", before) == []
    [problem] = driver.check_payload(payload, "KeyJourneyLatency", "firing", after)
    assert "earlier than" in problem
