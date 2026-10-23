"""QA regression guards for the local observability stack (#17; spec §11, §14, §6.5; ADR 0006).

These read the committed configuration only (no running stack) and lock in what the acceptance
criteria and CLAUDE.md rule 6 rely on:

- no telemetry pipeline can reach an exporter without passing its privacy processor first, and no
  extra pipeline can be added that bypasses the gate;
- only the backend ships its logs to the collector (fluentd driver), so no other container's
  output reaches Loki;
- Grafana credentials come from the environment (required, no default) and anonymous access is off;
- retention is set for Prometheus, Loki and Tempo;
- datasources and dashboards are provisioned from files and cannot be edited in the UI, and the
  trace_id links (exemplar -> Tempo -> Loki -> Tempo) are configured;
- every application query on the dashboards filters by `env`.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
OBS = ROOT / "observability"
COMPOSE_OBS = ROOT / "compose.observability.yaml"
DASHBOARDS = OBS / "grafana" / "dashboards"

GATES = {"traces": "transform/traces", "metrics": "transform/metrics", "logs": "transform/logs"}
OBS_SERVICES = ("otel-collector", "prometheus", "loki", "tempo", "grafana")


def _yaml(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded


@pytest.fixture(scope="module")
def collector() -> dict[str, Any]:
    return _yaml(OBS / "collector" / "config.yaml")


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return _yaml(COMPOSE_OBS)


# --- collector: privacy gate cannot be bypassed --------------------------------------------------


def test_every_pipeline_is_gated_by_its_privacy_processor(collector: dict[str, Any]) -> None:
    pipelines: dict[str, Any] = collector["service"]["pipelines"]
    assert pipelines, "no pipelines configured"
    for name, pipeline in pipelines.items():
        signal = name.split("/")[0]
        assert signal in GATES, f"unexpected pipeline type {name!r}"
        processors: list[str] = pipeline["processors"]
        gate = GATES[signal]
        assert gate in processors, f"pipeline {name!r} exports without {gate}"
        # Nothing that batches or reshapes before the gate except the memory limiter.
        assert processors[: processors.index(gate)] in ([], ["memory_limiter"]), (
            f"pipeline {name!r}: {processors[: processors.index(gate)]} run before {gate}"
        )


def test_log_drop_filter_runs_before_export(collector: dict[str, Any]) -> None:
    processors: list[str] = collector["service"]["pipelines"]["logs"]["processors"]
    assert processors.index("filter/unparsed_logs") > processors.index("transform/logs")
    assert processors[-1] == "batch"


def test_logs_come_only_from_the_fluent_forward_receiver(collector: dict[str, Any]) -> None:
    # No filelog receiver tailing /var/lib/docker/containers (would collect every container).
    assert "filelog" not in " ".join(collector["receivers"])
    assert collector["service"]["pipelines"]["logs"]["receivers"] == ["fluent_forward"]


def test_span_status_messages_are_cleared_and_events_reduced(collector: dict[str, Any]) -> None:
    groups = collector["processors"]["transform/traces"]["trace_statements"]
    by_context = {g["context"]: g["statements"] for g in groups}
    assert 'set(span.status.message, "")' in by_context["span"]
    assert by_context["spanevent"] == [
        'keep_matching_keys(spanevent.attributes, "^exception\\\\.(?:type|escaped)$")'
    ]


# --- compose overlay -----------------------------------------------------------------------------


def test_only_the_backend_uses_the_fluentd_log_driver(compose: dict[str, Any]) -> None:
    for name, service in compose["services"].items():
        driver = (service.get("logging") or {}).get("driver")
        if name == "backend":
            assert driver == "fluentd"
            assert service["logging"]["options"]["fluentd-async"] == "true"
        else:
            assert driver != "fluentd", f"{name} would ship its logs to Loki"


def test_published_ports_are_loopback_only(compose: dict[str, Any]) -> None:
    for name, service in compose["services"].items():
        for port in service.get("ports", []):
            spec = str(port)
            assert spec.startswith(("127.0.0.1:", "${GRAFANA_BIND:-127.0.0.1}:")), (
                f"{name} publishes {port}"
            )


def test_grafana_credentials_from_env_and_anonymous_off(compose: dict[str, Any]) -> None:
    env: dict[str, str] = compose["services"]["grafana"]["environment"]
    password = env["GF_SECURITY_ADMIN_PASSWORD"]
    assert re.fullmatch(r"\$\{GRAFANA_ADMIN_PASSWORD:\?[^}]*\}", password), (
        "admin password must be required from the environment, with no default"
    )
    assert env["GF_AUTH_ANONYMOUS_ENABLED"] == "false"
    assert env["GF_USERS_ALLOW_SIGN_UP"] == "false"


def test_env_example_documents_the_grafana_credentials() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^GRAFANA_ADMIN_USER=", text, re.M)
    assert re.search(r"^GRAFANA_ADMIN_PASSWORD=", text, re.M)


def test_every_observability_service_is_pinned(compose: dict[str, Any]) -> None:
    for name in (*OBS_SERVICES, "obs-probe"):
        image: str = compose["services"][name]["image"]
        tag = image.rsplit(":", 1)[-1] if ":" in image else ""
        assert tag and tag != "latest", f"{name} image {image!r} is not pinned"


def test_up_wait_covers_every_observability_service(compose: dict[str, Any]) -> None:
    services = compose["services"]
    probe = services["obs-probe"]["healthcheck"]["test"][-1]
    for name in OBS_SERVICES:
        if "healthcheck" not in services[name]:
            # Distroless images: readiness is checked by the probe instead.
            assert f"http://{name}:" in probe, f"{name} has neither a healthcheck nor a probe"
    grafana_deps = services["grafana"]["depends_on"]
    assert grafana_deps["obs-probe"]["condition"] == "service_healthy"


# --- retention -----------------------------------------------------------------------------------


def test_retention_is_set_for_prometheus_loki_and_tempo(compose: dict[str, Any]) -> None:
    prom_cmd = " ".join(compose["services"]["prometheus"]["command"])
    assert "--storage.tsdb.retention.time=" in prom_cmd
    assert "--storage.tsdb.retention.size=" in prom_cmd

    loki = _yaml(OBS / "loki" / "loki.yaml")
    assert loki["compactor"]["retention_enabled"] is True
    assert loki["limits_config"]["retention_period"]

    tempo = _yaml(OBS / "tempo" / "tempo.yaml")
    assert tempo["backend_worker"]["compaction"]["block_retention"]
    assert tempo["backend_scheduler"]["provider"]["compaction"]["compaction"]["block_retention"]


def test_user_hash_is_never_a_loki_index_label() -> None:
    loki = _yaml(OBS / "loki" / "loki.yaml")
    configs = loki["limits_config"]["otlp_config"]["resource_attributes"]["attributes_config"]
    labels = {a for c in configs if c["action"] == "index_label" for a in c["attributes"]}
    assert labels == {"service.name", "env"}


# --- Grafana provisioning and correlation ---------------------------------------------------------


def test_datasources_are_provisioned_read_only_with_trace_links() -> None:
    ds = _yaml(OBS / "grafana" / "provisioning" / "datasources" / "datasources.yaml")
    by_uid = {d["uid"]: d for d in ds["datasources"]}
    assert set(by_uid) == {"prometheus", "loki", "tempo"}
    assert all(d["editable"] is False for d in by_uid.values())

    exemplar = by_uid["prometheus"]["jsonData"]["exemplarTraceIdDestinations"]
    assert exemplar == [
        {"name": "trace_id", "datasourceUid": "tempo", "urlDisplayLabel": "View trace"}
    ]
    to_logs = by_uid["tempo"]["jsonData"]["tracesToLogsV2"]
    assert to_logs["datasourceUid"] == "loki"
    assert 'trace_id="$${__trace.traceId}"' in to_logs["query"]
    derived = by_uid["loki"]["jsonData"]["derivedFields"]
    assert any(f["matcherRegex"] == "trace_id" and f["datasourceUid"] == "tempo" for f in derived)


def test_dashboards_are_provisioned_from_files_without_ui_updates() -> None:
    prov = _yaml(OBS / "grafana" / "provisioning" / "dashboards" / "dashboards.yaml")
    (provider,) = prov["providers"]
    assert provider["type"] == "file"
    assert provider["allowUiUpdates"] is False
    titles = {json.loads(p.read_text(encoding="utf-8"))["title"] for p in DASHBOARDS.glob("*.json")}
    assert titles >= {"Key journey", "Engines", "Service health"}


# Stack self-monitoring series (no `env` label): the only queries allowed without the env filter.
SELF_MONITORING = re.compile(
    r"^(sum\(up\)|.*(prometheus_tsdb_|loki_distributor_|tempo_distributor_))"
)


@pytest.mark.parametrize("path", sorted(DASHBOARDS.glob("*.json")), ids=lambda p: p.name)
def test_every_application_query_filters_by_env(path: Path) -> None:
    dashboard = json.loads(path.read_text(encoding="utf-8"))
    assert any(v["name"] == "env" for v in dashboard["templating"]["list"])
    exprs = re.findall(r'"expr":\s*"((?:[^"\\]|\\.)*)"', path.read_text(encoding="utf-8"))
    assert exprs
    for expr in exprs:
        if SELF_MONITORING.match(expr):
            continue
        assert 'env=~\\"$env\\"' in expr, f"{path.name}: query without env filter: {expr}"


def test_key_journey_has_rate_errors_and_p95_for_the_logging_endpoints() -> None:
    text = (DASHBOARDS / "key-journey.json").read_text(encoding="utf-8")
    for route in (
        "/api/v1/sessions/{session_id}/sets",
        "/api/v1/sessions/{session_id}/finish",
        "/api/v1/athletes/{athlete_id}/meal-logs",
    ):
        assert route in text
    assert "rate(http_server_duration_seconds_count" in text
    assert 'status=~\\"5..\\"' in text
    assert "histogram_quantile(0.95" in text
