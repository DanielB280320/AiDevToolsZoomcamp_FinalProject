# Runbook: KeyJourneyErrors

Used by the on-call agent ([ADR 0007](../adr/0007-on-call-agent-with-allow-listed-mitigations.md), spec [§15](../spec.md#15-alerting-and-on-call-agent)) and by the owner. Alert rule: [`observability/grafana/provisioning/alerting/rules.yaml`](../../observability/grafana/provisioning/alerting/rules.yaml). Dashboard: Grafana "Key journey" (`d/fitwise-key-journey`, `env=prod`). Index: [README](README.md).

## What the alert means

More than 5 % of requests to one logging endpoint returned 5xx over the last 5 minutes, with at least 20 requests in that window. Severity `page`, `env=prod`.

The endpoints are the key journey (check off meals, log sets, finish workout):

| Route template (label `route`) | What the user cannot do |
|---|---|
| `/api/v1/sessions/{session_id}/sets` | Log a set |
| `/api/v1/sessions/{session_id}/finish` | Finish a workout (suggestions are generated here) |
| `/api/v1/athletes/{athlete_id}/meal-logs` | Check off a meal |

"No data" counts as OK, so the alert never fires on an idle system. The alert's `route` label names the affected endpoint; run the queries below for that route (or drop the `route` matcher for all three).

## 1. Gather evidence (read-only)

The incident folder `incidents/<id>/` already holds `prometheus.json`, `loki.json`, `tempo.json` and `capture.json` captured by the responder; read those first. Fresh data comes from the host-local backends (defaults: Prometheus `127.0.0.1:9090`, Loki `127.0.0.1:3100`, Tempo `127.0.0.1:3200`). Only read queries; nothing here writes anywhere.

**PromQL** (replace `ROUTE` with the alert's route label, or use the regex of all three):

```bash
# 5xx ratio per route, 5 min (the alert's expression, without the >= 20 request guard)
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=
  sum by (route) (increase(http_server_duration_seconds_count{env="prod", method="POST", route="ROUTE", status=~"5.."}[5m]))
  / sum by (route) (increase(http_server_duration_seconds_count{env="prod", method="POST", route="ROUTE"}[5m]))'

# request volume in the same window (the alert needs >= 20)
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=
  sum by (route) (increase(http_server_duration_seconds_count{env="prod", method="POST", route="ROUTE"}[5m]))'

# 5xx by status code: one status (500 vs 502/503/504) points at a different cause
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=
  sum by (route, status) (increase(http_server_duration_seconds_count{env="prod", method="POST", route="ROUTE", status=~"5.."}[5m]))'

# was it fine before? same ratio 15 minutes ago (a low value then and a high one now dates the start)
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=
  sum by (route) (increase(http_server_duration_seconds_count{env="prod", method="POST", route="ROUTE", status=~"5.."}[5m] offset 15m))
  / sum by (route) (increase(http_server_duration_seconds_count{env="prod", method="POST", route="ROUTE"}[5m] offset 15m))'
```

**LogQL** (Loki; log fields are structured metadata, filter them with `| field=...`, and are allow-listed: `route`, `method`, `status`, `duration_ms`, `error_type`, `engine`, `rule`, `outcome`, `user_hash`, `trace_id`; no messages with user data exist):

```bash
# error logs of the backend, newest first
curl -sG http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode 'query={service_name="fitwise-backend", env="prod"} | detected_level=~"error|critical|fatal"' \
  --data-urlencode since=30m --data-urlencode limit=100 --data-urlencode direction=backward

# 5xx access-log lines for the route; look at error_type / engine and the earliest timestamp
curl -sG http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode 'query={service_name="fitwise-backend", env="prod"} | logger="app.access" | route="ROUTE" | status>=500' \
  --data-urlencode since=30m --data-urlencode limit=100

# error count by error_type over 30 min
curl -sG http://127.0.0.1:3100/loki/api/v1/query \
  --data-urlencode 'query=sum by (error_type) (count_over_time({service_name="fitwise-backend", env="prod"} | detected_level=~"error|critical|fatal" [30m]))'

# recent flag changes (who changed what, when)
curl -sG http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode 'query={service_name="fitwise-backend", env="prod"} |= "feature flag changed"' \
  --data-urlencode since=6h --data-urlencode limit=20
```

**TraceQL** (Tempo; span attributes are allow-listed too, no exception messages):

```bash
# failing traces for the route in the last 30 min; open one in Grafana (Explore > Tempo) or fetch it
curl -sG http://127.0.0.1:3200/api/search \
  --data-urlencode 'q={ status = error && span.http.route = "ROUTE" }' \
  --data-urlencode limit=20
curl -s http://127.0.0.1:3200/api/traces/<trace_id>
```

Spans named `engine.progression`, `engine.meal_plan` and `engine.targets` show whether the failure is inside an engine; SQLAlchemy spans show database failures; an outgoing HTTP span to Open Food Facts shows an upstream failure.

**Which release is live and when it changed** (every log line carries the release as `service_version`, the git SHA):

```bash
# log volume per release over the last 6 h: the minute a new version first appears is the deploy
curl -sG http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode 'query=sum by (service_version) (count_over_time({service_name="fitwise-backend", env="prod"} [5m]))' \
  --data-urlencode since=6h --data-urlencode step=300
docker compose ps                                  # container state, restarts, health
docker compose logs --since 30m backend | tail -200
```

Compare the time the errors started (the 15-minute-ago query above, `incidents/<id>/prometheus.json`) with the first appearance of the current `service_version` and with the last "feature flag changed" line.

## 2. Decide: exactly one mitigation

Apply **one** mitigation, the first row whose evidence matches. If no row matches, apply none: open the incident issue (section 5) and leave the system as it is.

| Evidence | Mitigation | Command |
|---|---|---|
| Errors began within a few minutes after a new `service_version` first appeared in the logs (the 15-minutes-ago ratio is low), the same `error_type` dominates the error logs and no flag changed since | Roll back to the previous release | `oncall/ops/rollback.sh` |
| A "feature flag changed" line shortly before the errors, and the failing traces or logs show `engine.progression` (or `engine=...`) and `progression_engine` is `v2` | Return the engine flag to its safe value | `oncall/ops/flag.sh progression_engine v1` |
| Failing traces show outgoing HTTP errors to Open Food Facts and `off_search_enabled` is `true` | Turn the upstream feature off (the app degrades to `available: false`) | `oncall/ops/flag.sh off_search_enabled false` |
| No deploy or flag change, `docker compose ps` shows the backend unhealthy, restarting or exited, or traces show a stuck connection pool | Restart the backend container | `oncall/ops/restart.sh backend` |
| Frontend/nginx returns 502/504 while backend metrics are clean (5xx come from the proxy, not `error_type` logs) | Restart the frontend container | `oncall/ops/restart.sh frontend` |
| Database errors (`error_type` such as `OperationalError`, readiness `check=database`), disk full, or anything else not above | No mitigation is on the allow-list. Open the incident issue and page the owner | none |
| Low traffic (close to 20 requests) and a handful of errors from one user (`user_hash`), no pattern | No mitigation. Keep watching, open the issue | none |

Notes on the mitigations:

- `rollback.sh` runs **locally on the host**, as root through `sudo -n` (no SSM, no AWS credential). It redeploys `PREVIOUS_TAG` **without running migrations** and without down-migrating; this is safe because migrations are backward compatible (D50). Exit 3 means `PREVIOUS_TAG` is empty and nothing changed: treat it as "no mitigation available" and escalate to the owner.
- The pull-based poller **will not redeploy the rolled-back tag** and will not undo the rollback: it acts again only when the `deploy/prod` ref moves. So prod stays on the rolled-back tag until someone promotes a new one.
- The follow-up fix goes out **only through the "Promote to production" workflow** (manual run, `production` environment approval; [ADR 0010](../adr/0010-pull-based-deploy.md)). Never deploy to prod from the host or a branch.
- Flag changes take effect within 5 seconds without a restart (`FLAG_CACHE_TTL_SECONDS`). Allowed keys are only those in `backend/app/config.py` `FEATURE_FLAGS`; an unknown key or value is rejected and nothing changes.
- Do not apply a second mitigation if the first did not help. Record that in the issue and stop (the agent's limit is one mitigation per incident).

## 3. Verify recovery

Recovered means: the 5xx ratio of the affected route is **under 5 % for 5 consecutive minutes** (or the alert resolves; no data also counts as OK). Check every minute or so:

```bash
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=
  sum by (route) (increase(http_server_duration_seconds_count{env="prod", method="POST", route="ROUTE", status=~"5.."}[5m]))
  / sum by (route) (increase(http_server_duration_seconds_count{env="prod", method="POST", route="ROUTE"}[5m]))'
```

The 5-minute window still contains pre-mitigation requests for a few minutes, so a falling ratio is expected before it is under the threshold. Also confirm with `docker compose ps` (backend healthy) and, after a rollback, that new log lines carry the previous `service_version` (Loki query above). If the condition does not hold within 15 minutes, say so in the issue and hand over to the owner.

## 4. Follow-up (not an on-call action)

The root-cause fix, with a regression test, is a normal PR: branch, CI, human review, merge (deploys to dev), then "Promote to production". After a rollback, prod keeps the old tag until that promotion.

## 5. Incident issue template

Create with `gh issue create --label incident` (title `Incident: KeyJourneyErrors <route> <UTC date>`). Never put emails, names, body metrics, food names or notes in it; `user_hash` and `trace_id` are fine.

```markdown
## Summary
KeyJourneyErrors on `<route>`: <5xx ratio> over 5 min at <UTC time>. User impact: <what could not be done, for how long>.

## Timeline (UTC)
- HH:MM errors begin (PromQL range query)
- HH:MM alert fires
- HH:MM evidence gathered
- HH:MM mitigation applied: `<command>`
- HH:MM recovered (ratio < 5 % for 5 min) / not recovered

## Evidence
- Releases: running `service_version` `<sha>`, first seen HH:MM, previous `<sha>`; flags changed: <none | key old -> new at HH:MM>
- Metrics: <query and result>
- Logs: <error_type counts, earliest line>
- Traces: <trace_ids and the failing span>

## Mitigation
<the one allow-listed command, its output, and why that row of the decision table>

## Recovery check
<query, value, time window; or why not recovered>

## Follow-up
- [ ] Root-cause fix PR with regression test: <link>
- [ ] Promote the fix via "Promote to production" (prod stays on the rolled-back tag until then, ADR 0010)
- [ ] Runbook gap (if any): <what to add to docs/runbooks/key-journey-errors.md>
```
