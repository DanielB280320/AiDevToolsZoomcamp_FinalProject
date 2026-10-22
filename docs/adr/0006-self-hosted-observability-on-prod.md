# ADR 0006: Self-host the observability stack on the prod EC2 instance

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-21 |
| **Deciders** | Owner |
| **Spec** | [spec §6.5 Privacy](../spec.md#65-privacy-health-data), [§12 Deployment](../spec.md#12-deployment-aws), [§14 Observability](../spec.md#14-observability), [§15.1 Alerts](../spec.md#151-alerts-grafana-managed-provisioned-as-code-envprod), [§19](../spec.md#19-decisions-log) D32, D34 |

## Context

The course requires observability and alerts on user impact. FitWise needs traces, metrics and logs correlated by `trace_id`, dashboards and alert rules provisioned as code, and alerts that can start the on-call agent. Telemetry must never contain health or personal data ([§6.5](../spec.md#65-privacy-health-data)). Budget is small and there are only two hosts ([ADR 0002](0002-ec2-docker-compose-deployment.md)).

## Decision

We will:

- Instrument the backend with the **OpenTelemetry SDK** and send everything to an **OTel Collector** on each host.
- Run **Prometheus, Loki, Tempo and Grafana** in Docker Compose on the **prod** instance only. The dev collector forwards to the prod collector over an OTLP port open only to the dev instance; all data carries `env=dev|prod`.
- Provision dashboards ("Key journey", "Engines", "Service health") and the two alerts (KeyJourneyErrors, KeyJourneyLatency, `env=prod`) **as code** in `observability/`.
- Log structured JSON through an **allow-listed logger**; identify users only by `user_hash`.

## Alternatives considered

| Option | Why not |
|---|---|
| Grafana Cloud / Datadog / New Relic | Less to operate, but sends data to a third party, has free-tier limits, and makes the alert → on-call webhook path harder to demo end to end. |
| AWS CloudWatch | Ties telemetry to AWS and gives weaker trace ↔ log correlation than the Grafana stack. |
| A third "monitoring" instance | Survives prod outages, but adds cost and another host to run for the MVP. |
| Observability stack on each instance | Duplicates the stack; one place for both environments is simpler. |

## Consequences

- **Positive:** full control and zero licence cost; one Grafana for both environments; everything versioned in git; the on-call responder runs next to the data it queries.
- **Negative / accepted risks:** monitoring shares fate with prod, so a host failure takes out the alerts too; the stack uses memory and disk on the prod instance (retention must be bounded). Grafana is reachable only from the owner's IP.
- **Follow-ups:** a unit test asserts sensitive keys are dropped by the logger ([§6.5](../spec.md#65-privacy-health-data)); `make up-obs` runs the same stack locally.
