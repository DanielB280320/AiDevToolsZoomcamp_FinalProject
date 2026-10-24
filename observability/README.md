# Observability stack

OpenTelemetry Collector, Prometheus, Loki, Tempo and Grafana for FitWise (spec §14,
[ADR 0006](../docs/adr/0006-self-hosted-observability-on-prod.md),
[architecture §5](../docs/architecture.md#5-observability-and-incident-flow)). Everything here is
provisioned from files; nothing is configured by hand in Grafana. Running it on prod and the
dev → prod forwarding are #67; the alert rules are in `grafana/provisioning/alerting/` (#18).

## Run it locally

```bash
make up-obs      # app + collector, Prometheus, Loki, Tempo, Grafana; returns when all are healthy
make check-obs   # smoke: one request as metric + exemplar + trace + logs; privacy; provisioning
make down-obs    # stop everything (volumes kept)
make clean-obs   # stop the observability services and DELETE their volumes
```

Grafana: `http://localhost:${GRAFANA_PORT}` (default 3030), user `GRAFANA_ADMIN_USER`, password
`GRAFANA_ADMIN_PASSWORD` from `.env` (see `.env.example`; dev-only placeholder there).
Anonymous access and sign-up are off. Dashboards are in the **FitWise** folder.

`make up-obs` runs `compose.yaml` and `compose.observability.yaml` together, so the backend exports to
the collector. A later plain `make up` recreates the backend **without** exporting; use `make up-obs`
again to switch it back. `make down` also stops the observability containers (as orphans).

Several stacks side by side: besides `COMPOSE_PROJECT_NAME`, `HTTP_PORT` and `TEST_DB_PORT`, give each
checkout its own `GRAFANA_PORT`, `OTLP_HTTP_PORT` and `FLUENT_FORWARD_PORT` in its `.env`.

## Layout

| Path | What |
|---|---|
| `../compose.observability.yaml` | Services, pinned images, retention flags, backend overrides |
| `collector/config.yaml` | Receivers, the privacy gate (allow-lists), exporters |
| `prometheus/prometheus.yaml` | OTLP receiver settings (promoted `env`), self-scrape of the stack |
| `loki/loki.yaml` | Single binary, filesystem storage, retention, OTLP label mapping |
| `tempo/tempo.yaml` | Single binary, local storage, retention |
| `grafana/provisioning/datasources/` | Prometheus, Loki, Tempo with fixed UIDs and the trace_id links |
| `grafana/provisioning/dashboards/` | File provider for `grafana/dashboards/*.json` |
| `grafana/provisioning/alerting/` | Alert rules, contact points, policies as code (#18) |
| `grafana/dashboards/` | Key journey, Engines, Service health |

## How telemetry flows

| Signal | Path |
|---|---|
| Traces | backend OTLP/HTTP → collector (span attribute allow-list) → Tempo (OTLP/gRPC) |
| Metrics | backend OTLP/HTTP (every 15 s) → collector (label allow-list) → Prometheus OTLP receiver, with exemplars |
| Logs | backend JSON on stdout → Docker `fluentd` log driver (backend only) → collector `fluent_forward` → parse + field allow-list → Loki OTLP |

Why the `fluentd` driver: only the backend uses it, so the collector never sees another container's
logs (db, frontend, other projects), needs no host mounts and no root, and works the same on Docker
Desktop and on EC2. `docker compose logs backend` keeps working (Docker dual logging). The driver
is asynchronous: the backend starts even while the collector is down.

**Correlation** (Grafana datasources): a metric exemplar opens its trace in Tempo; a span opens
"Logs for this span" in Loki (`| trace_id="…"`); a log line's `trace_id` opens the trace.

**`env`**: the backend sets the resource attribute `env` (= `APP_ENV`); the collector keeps it and
inserts `FITWISE_ENV` only when it is missing. Prometheus promotes it to a label on every series,
Loki indexes it (`{service_name, env}` are the only index labels), Tempo keeps it on the resource.
Every dashboard has an `env` variable.

## Privacy gate (CLAUDE.md rule 6, spec §6.5)

The backend already filters what it emits (`backend/app/telemetry/privacy.py`). The collector is a
second, independent gate with the **same** allow-lists:

- Logs: a line that is not a JSON object is dropped (e.g. a traceback printed before logging is
  configured). From a JSON line only the base fields and `LOG_EVENT_FIELDS` are kept; anything else
  (an email, a weight, a note) is dropped. The Docker fields (container id/name) are dropped too.
  `user_hash`, `route`, `status`, … are Loki structured metadata, never labels.
- Spans: attributes outside `SPAN_ATTRIBUTES` / `fitwise.*` are dropped, `fitwise.*` keys whose last
  segment is a sensitive name are dropped, status messages are cleared, exception events keep the
  class name only.
- Metrics: labels outside `METRIC_ATTRIBUTES` are dropped.

`backend/tests/unit/test_collector_allow_lists.py` fails when the collector and `privacy.py` drift
apart: **adding a field to the app's allow-list means adding it to `collector/config.yaml` too.**
`make check-obs` checks the running stack end to end, including lines written to the backend's
stdout that bypass the app logger.

## Retention and disk use

| Store | Setting (`.env`) | Default | Expected disk |
|---|---|---|---|
| Prometheus | `PROM_RETENTION_TIME`, `PROM_RETENTION_SIZE` | 15 d, capped at 2 GB | ≈ 30–45 MB/day (≈ 4.8 k series, ≈ 240 samples/s, mostly the stack's own metrics; the app adds ≈ 15 series per route/method/status) → **≈ 0.5–0.7 GB** at 15 d; never above 2 GB |
| Loki | `LOKI_RETENTION` | 168 h (7 d) | ≈ 170 B per line before compression; at a sustained 1 req/s ≈ 15 MB/day raw → **< 0.2 GB** at 7 d (≈ 1 GB at 10 req/s) |
| Tempo | `TEMPO_RETENTION` | 72 h | ≈ 540 B per span, ≈ 5 spans per request; at 1 req/s ≈ 0.2 GB/day raw, ≈ 60 MB/day stored → **≈ 0.2 GB** at 72 h (≈ 2 GB at 10 req/s) |
| Grafana | – | – | < 50 MB (SQLite: users, sessions; dashboards come from files) |

Local demo traffic is far below 1 req/s, so a laptop needs well under 1 GB. Measured after a 1 h
local session: Prometheus 5.8 MB, Tempo 12 MB, Loki 0.1 MB, Grafana 1.7 MB. On the prod host (#67)
plan **≈ 3 GB** for the stack at the defaults (Prometheus's 2 GB cap dominates).

Loki deletes expired chunks through its compactor (`retention_delete_delay` 2 h). Tempo 3.x applies
retention in the backend scheduler/worker.

## Images

All pinned in `compose.observability.yaml`: `otel/opentelemetry-collector-contrib:0.161.0`,
`prom/prometheus:v3.15.0`, `grafana/loki:3.7.8`, `grafana/tempo:3.1.0`, `grafana/grafana:13.2.3`,
`busybox:1.37.0` (the readiness probe for the collector and Loki, whose images have no shell).
To upgrade, change a tag and run `make up-obs && make check-obs`.

## Alerts (#18)

`grafana/provisioning/alerting/` holds the KeyJourneyErrors and KeyJourneyLatency rules, the webhook
contact point and the notification policy (see its README). The webhook URL is `ONCALL_WEBHOOK_URL`
(`.env.example`; on prod the host's env file, #67). The logging endpoints exist from M2, so the rules
show no data (OK) until then; the fires-and-resolves test is #97.
