# FitWise on-call responder (webhook receiver)

Spec [§15.2](../docs/spec.md#152-on-call-responder), [ADR 0007](../docs/adr/0007-on-call-agent-with-allow-listed-mitigations.md), issue #19.

Receives Grafana unified-alerting webhooks at `POST /alerts`, deduplicates them per alert
fingerprint, saves the telemetry around the alert to `incidents/<id>/` and hands each new incident
to a launcher. With `ONCALL_AGENT_ENABLED=1` the launcher starts headless Claude Code
(`claude -p`, issue #69, see "On-call agent" below); otherwise it is a no-op that logs.

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
| `ONCALL_LAUNCHER_CMD` | empty (no-op that logs) | Command line run for each new incident, no shell (test seam; ignored when the agent is enabled) |
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

## On-call agent (issue #69)

Spec [§15.2](../docs/spec.md#152-on-call-responder), [ADR 0007](../docs/adr/0007-on-call-agent-with-allow-listed-mitigations.md).
After the capture, `responder/agent.py` runs, in the repo checkout (`ONCALL_REPO_DIR`, so the runbooks' relative `oncall/ops/...` commands work):

```
claude -p --output-format stream-json --verbose --settings incidents/<id>/agent-settings.json \
  --setting-sources user --tools Bash,Read,Write,Edit --permission-mode dontAsk --strict-mcp-config \
  --disable-slash-commands --no-session-persistence --model sonnet --max-budget-usd 5   < prompt
```

The prompt (on stdin, not in `ps`) holds the alert (labels, annotations), the incident folder, the hard rules and the text of the runbook named by the alert's `runbook_url` (looked up as `docs/runbooks/<file>.md` in the checkout; no runbook means investigate only, no mitigation).

### Tool allow-list

Built per incident by `build_allowlist` (the test `test_allow_list_is_exactly_the_documented_set` pins it). Only:

| Allowed | Notes |
|---|---|
| `curl -sG` to Prometheus `/api/v1/query`, `/query_range`; Loki `/loki/api/v1/query`, `/query_range`; Tempo `/api/search`, `/api/traces/<id>` | read-only, GET, configured backend URLs only |
| `docker compose ps`, `docker compose logs` | no `-f`/`--follow`; on the host through the shim and a root helper |
| `oncall/ops/flag.sh <key> <value>`, `oncall/ops/rollback.sh`, `oncall/ops/restart.sh backend\|frontend` | **one** per incident |
| `sleep <1-120>` | pacing for the 5-minute recovery check |
| `gh issue create --repo <repo> --label incident --title ... --body-file <incident>/issue.md` | fixed option order |
| `git -C <separate clone> ...` (status, diff, log, show, add, commit, checkout, switch, branch, fetch, push) and `gh pr create ... --head oncall/<id> --base main` | push only `origin oncall/<branch>`; never `main`, never force |
| Read in the incident folder and the clone; Write `issue.md`, `pr.md`, `commit-msg.txt` there; Edit/Write in the clone except `.git`, `.github`, `.claude`, `oncall`, `deploy` | |

Everything else is denied: `psql`, `rm`, `sudo`, `docker compose exec/up/down`, `git push origin main`, `gh api`, any pipe, redirect, `;`, `&&`, `$(...)`, WebFetch/WebSearch. Two layers: the settings permission rules (deny wins, `dontAsk` denies the unlisted), and `responder/guard.py`, a `PreToolUse` hook that fails closed and re-checks the exact shape of every call. The guard also enforces the single mitigation: the first of the three scripts writes `incidents/<id>/mitigation.json`, later ones are refused. A mitigation that was refused for bad arguments does not use the slot.

### Run, limits, evidence

- Timeout 20 min (`ONCALL_AGENT_TIMEOUT_S=1200`): the whole process group is killed; `agent.json` has `timed_out: true`.
- Spend: **USD 5 per incident run** (`ONCALL_AGENT_MAX_BUDGET_USD`, enforced by `--max-budget-usd`) and a **monthly limit of USD 20 on the API key** in the Anthropic Console (owner sets it; it cannot be set from this repo). The key is only in `/etc/fitwise-oncall.env`.
- `incidents/<id>/transcript` (full stream-json, mode 0600), `transcript.stderr`, `agent.json` (exit code, duration), `mitigation.json`, `agent-settings.json`, `guard.json`, `issue.md`, `pr.md`. No secret is written to any of them: the agent's environment is `PATH`, `LANG`, `ANTHROPIC_API_KEY`, `GH_TOKEN`, `COMPOSE*`, `DOCKER_HOST`, `FITWISE_BIN_DIR` and `HOME`; the webhook password and cloud credentials are not passed. The telemetry the agent reads is allow-listed at the source (see Privacy above), and the prompt tells it to keep health data out of issues and PRs.
- The agent is enabled only when `ANTHROPIC_API_KEY` and `GH_TOKEN` are set (the service refuses to start otherwise). `GH_TOKEN` should be a fine-grained token for this repository only (contents and pull requests: write, issues: write); `main` is protected (PR, CI, admins enforced), and the guard never allows a push to any branch outside `oncall/`.

### Host (prod): systemd service

`deploy/install-oncall.sh` (root, on `fitwise-prod`, after `bootstrap.sh` has installed the current scripts) sets up:

| Piece | Where |
|---|---|
| Service `fitwise-oncall.service` (`oncall/host/fitwise-oncall.service`), user `fitwise-oncall`, **not in the docker group** | systemd |
| Root-owned checkout (runbooks, ops scripts, code), venv from `oncall/uv.lock` | `/opt/fitwise-oncall/app`, `/opt/fitwise-oncall/venv` |
| Separate clone for fix branches (credentials via `gh auth git-credential` and `GH_TOKEN`) | `/var/lib/fitwise-oncall/clone` |
| Incidents, agent home | `/var/lib/fitwise-oncall/incidents`, `.../home` |
| Env file, `0600 root:root`, own secrets only (`ONCALL_WEBHOOK_PASSWORD`, `ANTHROPIC_API_KEY`, `GH_TOKEN`) plus plain settings | `/etc/fitwise-oncall.env` |
| sudoers: `rollback.sh ""` (no arguments) and `oncall-compose.sh` only | `/etc/sudoers.d/fitwise-oncall` |
| `docker` shim (only `docker compose ...`, forwarded to the root helper) | `/opt/fitwise-oncall/shim/docker` |
| Root helper that runs `docker compose` of the current release and validates its arguments again (ps, logs without follow, restart backend/frontend, the flag CLI) | `/opt/fitwise/bin/oncall-compose.sh` (`deploy/oncall-compose.sh`) |

Owner steps the script cannot do (secrets never travel through SSM command lines): prerequisites `python3.12`, `git`, `gh` and `claude` on the host's PATH; the Console spend limit; then edit `/etc/fitwise-oncall.env`: `ANTHROPIC_API_KEY=`, `GH_TOKEN=`, `ONCALL_AGENT_ENABLED=1`, and `systemctl restart fitwise-oncall`. Grafana reads `ONCALL_WEBHOOK_PASSWORD` from `/opt/fitwise/.env` (the script copies the same value there); re-run `deploy/obs.sh` so Grafana picks it up. Check: `systemctl is-active fitwise-oncall`, `stat -c '%a %U' /etc/fitwise-oncall.env` (`600 root`), `id fitwise-oncall` (no `docker`).

Tests: `make test-oncall` (allow-list, guard, restart.sh, claude invocation with a fake `claude`, timeout, fail-closed config) and `bash scripts/test-oncall-compose.sh` (root helper and shim). A live run with the real `claude` needs the API key and is the demo (S1-S3, `docs/runbooks/`).
