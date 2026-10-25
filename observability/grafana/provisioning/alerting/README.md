# Grafana-managed alerting, provisioned as code

Grafana loads every `*.yaml` file in this directory at start-up
(`/etc/grafana/provisioning/alerting`). Nothing is configured by hand (#18, spec §15.1).

| File | Holds |
|---|---|
| `rules.yaml` | KeyJourneyErrors (5xx > 5 % over 5 min, >= 20 requests) and KeyJourneyLatency (p95 > 1 s over 10 min) on the three logging endpoints, `env="prod"`, severity `page`, no data = OK |
| `contact-points.yaml` | Webhook `oncall-responder` to `$ONCALL_WEBHOOK_URL` (the responder's `/alerts`, `oncall/`, #19) with basic auth `$ONCALL_WEBHOOK_USER` / `$ONCALL_WEBHOOK_PASSWORD`; all from the environment, never from git |
| `policies.yaml` | Default route to `oncall-responder` (the only receiver; all alerts are `page`), grouped by alert and route |

Each alert carries the annotations `route`, `window`, `dashboard_url` (Key journey, `env=prod`) and
`runbook_url` (`docs/runbooks/key-journey-errors.md` / `key-journey-latency.md`, written in #68).
Labels are only `severity`, `env`, `service` plus the query's `route`: never user data.

The logging endpoints arrive in M2/M3 (#29, #37), so until then the rules see no series and stay OK
(D53). The fires-and-resolves test with a stub receiver is `make test-alerts` (#97, see `../../../README.md`).

Checks: `backend/tests/unit/test_alert_rules.py` (static, runs in `make test`) and `make check-obs`
(Grafana loaded the rules, contact point and policy). The datasource UIDs are in
`../datasources/datasources.yaml`.
