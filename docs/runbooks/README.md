# Runbooks

Incident runbooks for the on-call agent ([spec §15.2](../spec.md#152-on-call-responder), [ADR 0007](../adr/0007-on-call-agent-with-allow-listed-mitigations.md)) and for the owner. Process: [docs/process.md §10](../process.md#10-incidents). Each alert in `observability/grafana/provisioning/alerting/rules.yaml` links its runbook in `runbook_url` and the "Key journey" dashboard in `dashboard_url`.

| Alert | Runbook | Condition (prod) |
|---|---|---|
| KeyJourneyErrors | [key-journey-errors.md](key-journey-errors.md) | 5xx ratio > 5 % on the logging endpoints over 5 min, at least 20 requests |
| KeyJourneyLatency | [key-journey-latency.md](key-journey-latency.md) | p95 latency > 1 s on the same endpoints over 10 min |

## Rules every runbook follows

- One investigation, **one mitigation**, then verify recovery (condition under threshold for 5 minutes), then an incident issue (template inside each runbook).
- Only allow-listed commands (spec §15.2): read-only queries to Prometheus, Loki and Tempo, read-only `docker compose ps` and `docker compose logs`, `oncall/ops/flag.sh <key> <value>`, `oncall/ops/rollback.sh`, `oncall/ops/restart.sh <backend|frontend>`, `gh issue create`, and a branch push plus `gh pr create` on a separate clone. There are no direct database writes and no secret reads; the only state change besides rollback and restart is `oncall/ops/flag.sh` (flag state via the app CLI).
- `rollback.sh` runs locally on the host and redeploys `PREVIOUS_TAG` without migrations. The pull-based poller does not redeploy the rolled-back tag until the `deploy/prod` ref moves, and the fix goes out through "Promote to production" ([ADR 0010](../adr/0010-pull-based-deploy.md)).
- No health data in issues or logs: identify users only by `user_hash`.
- If the incident reveals a gap, DevOps updates the runbook in the fix PR.

`oncall/ops/restart.sh` is part of the allow-list but is delivered with the launcher (#69); until it exists, the restart rows in the decision tables cannot be executed and the agent should escalate instead.

## Demo scenarios (spec §15.3)

The scenarios show the agent end to end. They run after the logging endpoints exist (#29, D53). The fault-injection flags exist **only for demonstrations**, are **off by default** (`fault_injection_latency_ms` is `0`) and must not be set outside a demo.

| # | Fault | Alert | Expected mitigation | Follow-up PR |
|---|---|---|---|---|
| S1 | **Bad release**: a build where finishing a workout raises an error is promoted to prod through "Promote to production" | KeyJourneyErrors on `/api/v1/sessions/{session_id}/finish` | `oncall/ops/rollback.sh` (previous tag) | Fix plus a regression test, promoted through "Promote to production" |
| S2 | **Faulty engine version**: `progression_engine=v2` is enabled and v2 fails on bodyweight exercises (demo-only fault in `backend/app/engines/progression_v2.py`, off unless the flag is set; default `v1`) | KeyJourneyErrors | `oncall/ops/flag.sh progression_engine v1` | Fix v2 plus a test |
| S3 (optional) | **Latency fault**: the `fault_injection_latency_ms` flag adds a delay to the logging endpoints | KeyJourneyLatency | `oncall/ops/flag.sh fault_injection_latency_ms 0` | Runbook note |

How to trigger the faults (owner or DevOps, never the agent):

- S1: merge a PR that makes `finish` raise, let CI build it, run "Promote to production" and approve. Prod then serves the faulty tag; after the rollback the poller leaves it alone.
- S2: `oncall/ops/flag.sh progression_engine v2` on the prod host, then finish a session with a bodyweight exercise.
- S3: `oncall/ops/flag.sh fault_injection_latency_ms 1500` on the prod host, then log a few sets. Reset with the same command and `0` after the demo.

Evidence to keep for the demo (spec §15.2): the alert, the `incidents/<id>/` folder, the agent's transcript, the incident issue and the fix PR.
