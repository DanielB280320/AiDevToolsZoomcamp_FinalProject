"""The provisioned user-impact alerts match spec §15.1 (#18) and stay free of user data (rule 6).

Static checks on `observability/grafana/provisioning/alerting/*.yaml`; the live check (Grafana loads
the rules healthy) is `make check-obs`, and the fires-and-resolves test is #97.
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

OBS = Path(__file__).resolve().parents[3] / "observability"
ALERTING = OBS / "grafana" / "provisioning" / "alerting"
DASHBOARDS = OBS / "grafana" / "dashboards"
ROUTES = [
    "/api/v1/sessions/{session_id}/sets",
    "/api/v1/sessions/{session_id}/finish",
    "/api/v1/athletes/{athlete_id}/meal-logs",
]


def _load(name: str) -> Any:
    return yaml.safe_load((ALERTING / name).read_text())


def _rules() -> dict[str, Any]:
    return {r["title"]: r for r in _load("rules.yaml")["groups"][0]["rules"]}


def _expr(rule: dict[str, Any]) -> str:
    return str(rule["data"][0]["model"]["expr"])


def _threshold(rule: dict[str, Any]) -> float:
    return float(rule["data"][2]["model"]["conditions"][0]["evaluator"]["params"][0])


def test_both_rules_exist() -> None:
    assert set(_rules()) == {"KeyJourneyErrors", "KeyJourneyLatency"}


@pytest.mark.parametrize("title", ["KeyJourneyErrors", "KeyJourneyLatency"])
def test_common_contract(title: str) -> None:
    rule = _rules()[title]
    expr = _expr(rule)
    assert rule["noDataState"] == "OK"
    assert rule["labels"]["severity"] == "page"
    assert rule["labels"]["env"] == "prod"
    assert 'env="prod"' in expr
    assert 'method="POST"' in expr
    for route in ROUTES:
        assert route in expr
    ann = rule["annotations"]
    assert ann["route"] == "{{ .Labels.route }}"  # no `$`: Grafana expands $VAR in provisioning
    assert ann["window"]
    assert "externalURL }}d/fitwise-key-journey" in ann["dashboard_url"]
    slug = "key-journey-errors" if title == "KeyJourneyErrors" else "key-journey-latency"
    assert ann["runbook_url"].endswith(f"docs/runbooks/{slug}.md")


def test_error_rule_thresholds() -> None:
    rule = _rules()["KeyJourneyErrors"]
    expr = _expr(rule)
    assert _threshold(rule) == 0.05
    assert 'status=~"5.."' in expr
    assert "[5m]" in expr
    assert "[10m]" not in expr
    assert ">= 20" in expr


def test_latency_rule_thresholds() -> None:
    rule = _rules()["KeyJourneyLatency"]
    expr = _expr(rule)
    assert _threshold(rule) == 1  # seconds
    assert "histogram_quantile(0.95" in expr
    assert "http_server_duration_seconds_bucket" in expr
    assert "[10m]" in expr


def test_routes_are_the_dashboard_routes() -> None:
    text = (DASHBOARDS / "key-journey.json").read_text()
    for route in ROUTES:
        assert route in text


def test_alert_text_carries_no_user_data() -> None:
    """Only route/window/links in labels and annotations (rule 6)."""
    for rule in _rules().values():
        text = " ".join(
            [*map(str, rule["labels"].values()), *map(str, rule["annotations"].values())]
        )
        for template in re.findall(r"\{\{(.*?)\}\}", text):
            assert re.fullmatch(r"\s*(\.Labels\.route|externalURL)\s*", template), template
        assert set(rule["labels"]) == {"severity", "env", "service"}


def test_contact_point_and_policy() -> None:
    contact = _load("contact-points.yaml")["contactPoints"][0]
    receiver = contact["receivers"][0]
    assert receiver["type"] == "webhook"
    assert receiver["settings"]["url"] == "$ONCALL_WEBHOOK_URL"  # from env, never from git
    # Basic-auth credentials the responder requires (#19): env placeholders, never literals.
    assert receiver["settings"]["username"] == "$ONCALL_WEBHOOK_USER"
    assert receiver["settings"]["password"] == "$ONCALL_WEBHOOK_PASSWORD"
    policy = _load("policies.yaml")["policies"][0]
    assert policy["receiver"] == contact["name"]
    assert all(r["receiver"] == contact["name"] for r in policy.get("routes", []))


def test_no_dollar_template_variables_in_provisioning_yaml() -> None:
    """Grafana expands `$VAR` in provisioning files and does not collapse `$$` in alert rules
    (verified live: `{{ $.Labels.route }}` is stored verbatim and does not render), so templates
    use the dot form (`.Labels.route`) and never `$labels` / `$values`."""
    for path in (OBS / "grafana" / "provisioning").rglob("*.yaml"):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            bad = re.findall(r"\$+(?:labels|values|value)\b", line)
            assert not bad, f"{path.name}:{number} `$` template variable: {line.strip()}"
