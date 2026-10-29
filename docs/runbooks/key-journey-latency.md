# Runbook: KeyJourneyLatency

Used by the on-call agent ([ADR 0007](../adr/0007-on-call-agent-with-allow-listed-mitigations.md), spec [§15](../spec.md#15-alerting-and-on-call-agent)) and by the owner. Alert rule: [`observability/grafana/provisioning/alerting/rules.yaml`](../../observability/grafana/provisioning/alerting/rules.yaml). Dashboard: Grafana "Key journey" (`d/fitwise-key-journey`, `env=prod`). Index: [README](README.md).

## What the alert means

The p95 latency of one logging endpoint is above **1 second** over the last 10 minutes (severity `page`, `env=prod`). The endpoints are the key journey; the `route` label names the affected one:

| Route template (label `route`) | What the user feels |
|---|---|
| `/api/v1/sessions/{session_id}/sets` | Logging a set hangs |
| `/api/v1/sessions/{session_id}/finish` | Finishing a workout hangs (engines run here) |
| `/api/v1/athletes/{athlete_id}/meal-logs` | Checking off a meal hangs |

"No data" counts as OK. Unlike KeyJourneyErrors there is no minimum request count, so a single slow request on a quiet route can trip it; check the request volume before acting.

## 1. Gather evidence (read-only)

The incident folder `incidents/<id>/` already holds `prometheus.json` (includes `p95_latency_seconds`), `loki.json`, `tempo.json` and `capture.json`; read those first. Fresh data comes from the host-local backends (defaults: Prometheus `127.0.0.1:9090`, Loki `127.0.0.1:3100`, Tempo `127.0.0.1:3200`). Only read queries; nothing here writes anywhere. Replace `ROUTE` with the alert's route label.

**PromQL**

```bash
# p95 latency in seconds per route, 10 min (the alert's expression)
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=
  histogram_quantile(0.95, sum by (route, le) (increase(http_server_duration_seconds_bucket{env="prod", method="POST", route="ROUTE"}[10m])))'

# was it fine before? same quantile 15 minutes ago
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=
  histogram_quantile(0.95, sum by (route, le) (increase(http_server_duration_seconds_bucket{env="prod", method="POST", route="ROUTE"}[10m] offset 15m)))'

# p50 and p99: is everything slow (p50 high) or only the tail?
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=
  histogram_quantile(0.5, sum by (route, le) (increase(http_server_duration_seconds_bucket{env="prod", method="POST", route="ROUTE"}[10m])))'
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=
  histogram_quantile(0.99, sum by (route, le) (increase(http_server_duration_seconds_bucket{env="prod", method="POST", route="ROUTE"}[10m])))'

# request volume (a spike alone is not a regression)
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=
  sum by (route) (increase(http_server_duration_seconds_count{env="prod", method="POST", route="ROUTE"}[10m]))'

# errors at the same time (if the 5xx ratio is also high, follow key-journey-errors.md as well)
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=
  sum by (route) (increase(http_server_duration_seconds_count{env="prod", method="POST", route="ROUTE", status=~"5.."}[10m]))'
```

**LogQL**

```bash
# slowest requests for the route in the last 30 min: duration_ms above 1000, with trace_id
curl -sG http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode 'query={service_name="fitwise-backend", env="prod"} | logger="app.access" | route="ROUTE" | duration_ms > 1000' \
  --data-urlencode since=30m --data-urlencode limit=100

# recent flag changes (who changed what, when): look for fault_injection_latency_ms or progression_engine
curl -sG http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode 'query={service_name="fitwise-backend", env="prod"} |= "feature flag changed"' \
  --data-urlencode since=6h --data-urlencode limit=20

# error logs, in case slowness comes with failures
curl -sG http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode 'query={service_name="fitwise-backend", env="prod"} | detected_level=~"error|critical|fatal"' \
  --data-urlencode since=30m --data-urlencode limit=100 --data-urlencode direction=backward
```

**TraceQL**

```bash
# slow traces for the route (> 1 s); then open one and find the longest span
curl -sG http://127.0.0.1:3200/api/search \
  --data-urlencode 'q={ span.http.route = "ROUTE" && duration > 1s }' --data-urlencode limit=20
curl -s http://127.0.0.1:3200/api/traces/<trace_id>

# which span is slow: engines, database or an outgoing call
curl -sG http://127.0.0.1:3200/api/search --data-urlencode 'q={ name =~ "engine.*" && duration > 500ms }' --data-urlencode limit=20
curl -sG http://127.0.0.1:3200/api/search --data-urlencode 'q={ span.db.system != "" && duration > 500ms }' --data-urlencode limit=20
curl -sG http://127.0.0.1:3200/api/search --data-urlencode 'q={ kind = client && span.http.url != "" && duration > 500ms }' --data-urlencode limit=20
```

A request span that is long while its children are short means the time is spent in the app itself before or between spans (for example an injected delay or a blocked event loop).

**Which release is live and when it changed** (every log line carries the release as `service_version`, the git SHA):

```bash
# log volume per release over the last 6 h: the minute a new version first appears is the deploy
curl -sG http://127.0.0.1:3100/loki/api/v1/query_range \
  --data-urlencode 'query=sum by (service_version) (count_over_time({service_name="fitwise-backend", env="prod"} [5m]))' \
  --data-urlencode since=6h --data-urlencode step=300
docker compose ps                                  # container state, restarts, health
docker compose logs --since 30m --tail 200 backend
```

Compare the time the slowdown started (the 15-minutes-ago query above, `incidents/<id>/prometheus.json`) with the first appearance of the current `service_version` and with the last "feature flag changed" line.

## 2. Decide: exactly one mitigation

Apply **one** mitigation, the first row whose evidence matches. If no row matches, apply none: open the incident issue (section 5) and leave the system as it is.

| Evidence | Mitigation | Command |
|---|---|---|
| A "feature flag changed" line for `fault_injection_latency_ms` (value above 0) shortly before the slowdown; slow traces show a long request span with short children | Turn the demo fault off (S3) | `oncall/ops/flag.sh fault_injection_latency_ms 0` |
| A "feature flag changed" line for `progression_engine` to `v2` shortly before the slowdown, and slow spans are `engine.progression` | Return the engine flag to its safe value | `oncall/ops/flag.sh progression_engine v1` |
| Slow spans are outgoing HTTP calls to Open Food Facts and `off_search_enabled` is `true` | Turn the upstream feature off (the app degrades to `available: false`) | `oncall/ops/flag.sh off_search_enabled false` |
| Slowdown began within a few minutes after a new `service_version` first appeared in the logs, no flag changed, the 15-minutes-ago p95 was under 1 s | Roll back to the previous release | `oncall/ops/rollback.sh` |
| No deploy or flag change, `docker compose ps` shows the backend restarting or unhealthy, or latency grows steadily with no matching slow span | Restart the backend container | `oncall/ops/restart.sh backend` |
| Slow spans are database spans, the host is saturated, or traffic volume is far above normal with healthy spans | No mitigation is on the allow-list. Open the incident issue and page the owner | none |
| Few requests (a handful in 10 min), one slow outlier, p50 normal | No mitigation. Keep watching, open the issue | none |

Notes on the mitigations:

- `rollback.sh` runs **locally on the host**, as root through `sudo -n` (no SSM, no AWS credential). It redeploys `PREVIOUS_TAG` **without running migrations** and without down-migrating; this is safe because migrations are backward compatible (D50). It leaves `PREVIOUS_TAG` unchanged and records the release it rolled back from in `ROLLED_BACK_FROM`. Exit 3 means `PREVIOUS_TAG` is empty or already equals the current tag (for example a second rollback right after a first one), and exit 4 means the target is the release that was just rolled back from; nothing changed in either case. Treat both as "no mitigation available", do not retry and do not pass a SHA, and escalate to the owner (the release is rolled forward only through "Promote to production").
- The pull-based poller **will not redeploy the rolled-back tag** and will not undo the rollback: it acts again only when the `deploy/prod` ref moves. So prod stays on the rolled-back tag until someone promotes a new one.
- The follow-up fix goes out **only through the "Promote to production" workflow** (manual run, `production` environment approval; [ADR 0010](../adr/0010-pull-based-deploy.md)). Never deploy to prod from the host or a branch.
- Flag changes take effect within 5 seconds without a restart (`FLAG_CACHE_TTL_SECONDS`). Allowed keys are only those in `backend/app/config.py` `FEATURE_FLAGS`; an unknown key or value is rejected and nothing changes.
- Do not apply a second mitigation if the first did not help. Record that in the issue and stop (the agent's limit is one mitigation per incident).
- `fault_injection_latency_ms` is a **demo-only** fault-injection flag (scenario S3): it adds a delay to the logging endpoints, is `0` (off) by default and must never be set outside a demonstration. Seeing it above 0 in production outside a demo is itself the finding.

## 3. Verify recovery

Recovered means: the p95 of the affected route is **under 1 s for 5 consecutive minutes** (or the alert resolves; no data also counts as OK). Because the alert looks at 10 minutes, the slow requests need time to leave the window; for a faster check, use a 5-minute window and confirm it drops under 1 s:

```bash
curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=
  histogram_quantile(0.95, sum by (route, le) (increase(http_server_duration_seconds_bucket{env="prod", method="POST", route="ROUTE"}[5m])))'
```

Also confirm with `docker compose ps` (backend healthy) and, after a rollback, that new log lines carry the previous `service_version`. If the condition does not hold within 20 minutes, say so in the issue and hand over to the owner.

## 4. Follow-up (not an on-call action)

The root-cause fix, with a regression test (for the S3 demo: a runbook note), is a normal PR: branch, CI, human review, merge (deploys to dev), then "Promote to production". After a rollback, prod keeps the old tag until that promotion.

## 5. Incident issue template

Create with `gh issue create --label incident` (title `Incident: KeyJourneyLatency <route> <UTC date>`). Never put emails, names, body metrics, food names or notes in it; `user_hash` and `trace_id` are fine.

```markdown
## Summary
KeyJourneyLatency on `<route>`: p95 <seconds> s over 10 min at <UTC time>. User impact: <what could not be done, for how long>.

## Timeline (UTC)
- HH:MM latency rises (PromQL, 15-minutes-ago comparison)
- HH:MM alert fires
- HH:MM evidence gathered
- HH:MM mitigation applied: `<command>`
- HH:MM recovered (p95 < 1 s for 5 min) / not recovered

## Evidence
- Releases: running `service_version` `<sha>`, first seen HH:MM, previous `<sha>`; flags changed: <none | key old -> new at HH:MM>
- Metrics: <p50/p95/p99 and request volume>
- Logs: <slowest requests, flag changes>
- Traces: <trace_ids and the slow span>

## Mitigation
<the one allow-listed command, its output, and why that row of the decision table>

## Recovery check
<query, value, time window; or why not recovered>

## Follow-up
- [ ] Root-cause fix PR with regression test: <link>
- [ ] Promote the fix via "Promote to production" (prod stays on the rolled-back tag until then, ADR 0010)
- [ ] Runbook gap (if any): <what to add to docs/runbooks/key-journey-latency.md>
```
