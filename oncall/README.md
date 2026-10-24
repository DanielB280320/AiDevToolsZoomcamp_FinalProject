# FitWise on-call responder (webhook receiver)

Spec [§15.2](../docs/spec.md#152-on-call-responder), [ADR 0007](../docs/adr/0007-on-call-agent-with-allow-listed-mitigations.md), issue #19.

Receives Grafana unified-alerting webhooks at `POST /alerts`, deduplicates them per alert
fingerprint, saves the telemetry around the alert to `incidents/<id>/` and hands each new incident
to a launcher hook. The headless Claude Code launcher, its tool allow-list, recovery check and the
systemd unit are issue #69; until then the hook is a no-op that logs.

## Run the tests

```bash
make test-oncall     # pytest against stub HTTP servers: no network, no database
make lint-oncall     # ruff check, ruff format --check, mypy (strict)
# or directly:
cd oncall && uv run --locked pytest
```

CI runs both in the `oncall` job, which `ci-passed` requires.

## Run the service

```bash
cd oncall
ONCALL_WEBHOOK_PASSWORD=<secret> uv run --locked python -m responder
```

It listens on `127.0.0.1:8099` (`ONCALL_HOST`, `ONCALL_PORT`).

**Docker wiring (#67/#69):** Grafana runs in a container and calls the responder at
`host.docker.internal:8099` (default `ONCALL_WEBHOOK_URL`), which does not reach a service bound
to the host's `127.0.0.1`. On the prod host set `ONCALL_HOST` to the Docker bridge address (the
`docker0` gateway, usually `172.17.0.1`) or to `0.0.0.0` behind a firewall that only allows the
Docker networks, and keep the basic-auth credential set either way. Never expose the port publicly. Grafana reaches it through the
contact point `oncall-responder` (`observability/grafana/provisioning/alerting/contact-points.yaml`).

## Behaviour

| Notification | Result |
|---|---|
| No or wrong credentials | `401`, nothing stored |
| Malformed body or unsafe fingerprint | `400` |
| Grafana contact-point "Test" (`alertname=TestAlert`) | `202`, logged, no incident, no launcher call |
| `firing`, no open incident for the fingerprint | `202`; incident opened; capture and launcher run in the background |
| `firing`, incident already open | `202`, ignored (no second incident) |
| `resolved` for an open incident | `202`; incident closed (`closed_at` set); a later `firing` opens a new one |

Test notifications are recognised by Grafana's default test labels (`alertname=TestAlert` and the
annotation `summary=Notification test`). A test sent from the UI with custom labels or annotations
would open a real incident.

After a restart the service re-runs the launcher for open incidents that never reached it (no
`launched` file in the folder); incidents already handed over are left alone.

The response never waits for the capture or the launcher, so it is well under Grafana's timeout
even when the hook is slow.

### State on disk

```
incidents/
  open/<fingerprint>          dedupe marker: id of the open incident (removed on resolve)
  <id>/                       <id> = <UTC timestamp>-<fingerprint prefix>
    incident.json             id, fingerprint, opened_at, closed_at
    alert.json                the alert as Grafana sent it
    prometheus.json           range queries: 5xx requests, all requests, p95 latency
    loki.json                 error log lines for the window (filter: detected_level, as the dashboard)
    tempo.json                {"trace_ids": [...]} of failing traces in the window
    capture.json              per backend: "ok" or "failed: <HTTP status | exception type>"
```

The open/closed state is plain files, so a restart does not start a duplicate incident. If one
backend is down, its file is missing, `capture.json` records why, and the other files and the
launcher still run. `incidents/` is git-ignored.

### Privacy (spec §6.5)

The responder stores the alert and the Loki/Tempo/Prometheus results **exactly as returned**. That
is safe because the logs and traces it queries are already allow-listed at the source: the backend
only emits allow-listed fields (`backend/app/telemetry/privacy.py`), so no emails, names, tokens,
body metrics, food names or notes are in Loki in the first place. The responder does not filter
or rewrite them, and a test (`test_loki_results_stored_as_returned`) feeds a log line containing an
email through a Loki stub to show that. Its own logs also go through an allow-list
(`responder/log.py`): event names, incident ids, fingerprints and status codes only.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `ONCALL_WEBHOOK_PASSWORD` | required | Basic-auth password; the service refuses to start without it |
| `ONCALL_WEBHOOK_USER` | `grafana` | Basic-auth user |
| `ONCALL_INCIDENTS_DIR` | `incidents` | Where incident state and folders live |
| `ONCALL_PROMETHEUS_URL` / `ONCALL_LOKI_URL` / `ONCALL_TEMPO_URL` | `127.0.0.1` on 9090 / 3100 / 3200 | Backends to query |
| `ONCALL_CAPTURE_TIMEOUT_S` | `10` | Per backend request timeout |
| `ONCALL_CAPTURE_WINDOW_BEFORE_S` / `_AFTER_S` | `900` / `60` | Query window around `startsAt` / `endsAt` |
| `ONCALL_LAUNCHER_CMD` | empty (no-op that logs) | Command line run for each new incident, no shell |
| `ONCALL_LAUNCHER_TIMEOUT_S` | `1260` | Launcher timeout (spec: 20 min plus margin) |
| `ONCALL_WORKERS` | `4` | Background worker threads |
| `ONCALL_HOST` / `ONCALL_PORT` | `127.0.0.1` / `8099` | Listen address |

The webhook credentials (`ONCALL_WEBHOOK_USER`, `ONCALL_WEBHOOK_PASSWORD`) are shared with Grafana,
which reads the same names (see `.env.example`). Never commit real values.

### Launcher hook contract

`ONCALL_LAUNCHER_CMD` is split like a shell command line and run without a shell, with the
incident folder appended as the last argument and exposed as `ONCALL_INCIDENT_DIR` /
`ONCALL_INCIDENT_ID`. The webhook password is removed from its environment. Its output is
discarded; the exit code is logged.
