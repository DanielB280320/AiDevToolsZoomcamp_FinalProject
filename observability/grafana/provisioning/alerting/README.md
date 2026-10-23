# Grafana-managed alerting, provisioned as code

Grafana loads every `*.yaml` file in this directory at start-up
(`/etc/grafana/provisioning/alerting`). The directory is empty on purpose until the alerts land:

| File (planned) | Holds | Issue |
|---|---|---|
| `rules.yaml` | KeyJourneyErrors, KeyJourneyLatency (`env=prod`, spec §15.1) | #18 |
| `contact-points.yaml` | Webhook to the on-call responder (`/alerts`) | #18 / on-call |
| `policies.yaml` | Notification policy routing `severity=page` to the responder | #18 |

Rules query the datasource UIDs `prometheus`, `loki` and `tempo` (see
`../datasources/datasources.yaml`); annotations link the dashboard UIDs `fitwise-key-journey`,
`fitwise-engines`, `fitwise-service-health` and a runbook in `docs/runbooks/`.
