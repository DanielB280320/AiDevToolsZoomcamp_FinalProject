# Demo S1: bad release, alert, rollback by the on-call agent

Issue [#20](https://github.com/DanielB280320/AiDevToolsZoomcamp_FinalProject/issues/20). Spec [§15.3](../spec.md#153-demo-scenarios-documented-in-docsrunbooks), D53, D91. Alert runbook the agent follows: [key-journey-errors.md](key-journey-errors.md). Index: [README](README.md).

**Story.** A release in which finishing a workout raises an error is promoted to prod through the normal "Promote to production" workflow. `KeyJourneyErrors` fires for `/api/v1/sessions/{session_id}/finish`, the responder starts the on-call agent, the agent sees that the errors began with the new `service_version`, runs `oncall/ops/rollback.sh` (one mitigation), verifies recovery, opens an incident issue and a fix PR. The fix goes out through "Promote to production" again.

This is a **live prod drill**. The orchestrator runs it after the owner confirms. Nobody deploys to prod from a laptop or a branch, and nothing here widens the on-call allow-list.

## 1. What the broken build is

`backend/app/demo_faults.py` holds `S1_FINISH_RAISES: bool = False`. `POST /api/v1/sessions/{id}/finish` has a route dependency (`finish_session_fault`) that raises `DemoFaultError` when the constant is `True`. In the drill build it is `True`; the result is an unhandled exception, so HTTP 500 `internal_error`, with only `error_type=DemoFaultError` in the logs and the failing span in the trace (no message, no request data; rule 6).

- The fault runs before authentication, so the drill's traffic needs no account and no health data (`scripts/demo-s1-traffic.sh`). Real users finishing a workout fail the same way.
- Only `finish` is affected. Sets and meal logs keep working; the alert fires per route.
- The code is compiled into the image: **rolling back to `PREVIOUS_TAG` removes the fault**, which is what makes this a bad-release scenario (S2 and S3 are flag scenarios).
- `scripts/demo-s1-enable.sh` produces the drill commit: it flips the constant and the guard test `test_shipped_build_has_no_demo_fault`, so CI stays green. Tests: `backend/tests/unit/test_demo_faults.py` (fault off does nothing, fault on gives 500 with `DemoFaultError`, only `finish` carries the dependency, the shipped build is off).

### Why this mechanism (trade-offs)

"Promote to production" only accepts a SHA whose `ci.yml` run **on `main`** passed `deploy-dev` and `smoke-dev` (`scripts/promote-verify.sh`, D58). So a throwaway demo branch cannot be promoted: the broken build has to be a commit on `main`. Options considered:

| Option | Verdict |
|---|---|
| Demo branch, image built by CI, promote it | Not possible: `promote-verify.sh` requires a `main` push run; weakening that gate for a demo is worse than the problem. |
| Runtime flag or env var gating the fault | The same image would be "good" and "bad", so the mitigation would be the flag, not a rollback. Not a bad release. |
| **Constant flipped by a small, reviewed PR on `main`, reverted afterwards (chosen)** | Uses the unchanged pipeline end to end (PR, CI, dev, dev smoke, promote, approval). Costs: for the time between the drill merge and the revert, `main` and **dev** serve the broken build, and the drill commit sits in history. Mitigation: the drill PR is one line plus the guard test, labelled `DEMO S1`, merged only on the owner's go and reverted right after the drill. |
| Permanent fault code gated by a build arg | Needs CI changes (build args per commit) and keeps unreleasable test code in production images. Rejected. |

The production code added is 25 lines, off by default, covered by tests, and recorded in D91.

## 2. Reproduce locally (no prod, own compose project)

```bash
git worktree add ../fitwise-s1 -b scratch/demo-s1 main   # scratch copy; never push it
cd ../fitwise-s1 && scripts/demo-s1-enable.sh
COMPOSE_PROJECT_NAME=fitwise-s1 HTTP_PORT=18090 make up
BASE_URL=http://127.0.0.1:18090 scripts/demo-s1-traffic.sh 5 1     # expect HTTP 500 five times
COMPOSE_PROJECT_NAME=fitwise-s1 docker compose down -v
```

Without the fault the same command prints `HTTP 401`. Unit level: `cd backend && uv run pytest tests/unit/test_demo_faults.py`.

## 3. Roles

| Who | Does |
|---|---|
| Owner | Confirms the live run, approves the `production` environment job, reviews the incident issue and the fix PR |
| Orchestrator | Runs the commands below (pre-flight, PRs, promotion, traffic, evidence) |
| DevOps | Prepared this runbook and the scripts; updates the runbook if the drill shows a gap |
| On-call agent | Everything from "alert fired" to the incident issue and the fix PR, inside its allow-list. **Nobody types the mitigation.** |

## 4. Pre-flight (read-only; orchestrator, before asking the owner for the go)

All of it must pass. Nothing here changes state.

**A. Public part** (laptop or CI; `BASE_URL` is the `PROD_BASE_URL` variable of the `production` environment):

```bash
BASE_URL=http://<prod elastic ip> scripts/demo-s1-preflight.sh            # before the drill PR exists
BASE_URL=http://<prod elastic ip> scripts/demo-s1-preflight.sh <drill-sha> # after the drill PR is on main and dev is green
```

It prints the SHA prod serves now (this is release **A**, the rollback target), checks `readyz`, that A is in the history of `deploy/prod`, the last three promote runs and, with the drill SHA, that dev proved it and that it is not A.

**B. Host part** (as root on `fitwise-prod`, over SSM `AWS-RunShellScript`; prints no secret):

```bash
echo "CURRENT_TAG=$(cat /opt/fitwise/CURRENT_TAG) PREVIOUS_TAG=$(cat /opt/fitwise/PREVIOUS_TAG) ROLLED_BACK_FROM=$(cat /opt/fitwise/ROLLED_BACK_FROM 2>/dev/null)"
curl -s localhost/api/v1/healthz; echo
systemctl is-active fitwise-oncall fitwise-deploy.timer
grep -c '^ONCALL_AGENT_ENABLED=1' /etc/fitwise-oncall.env                      # 1
stat -c '%a %U' /etc/fitwise-oncall.env                                        # 600 root
# the responder answers and enforces basic auth: 401 without credentials (this changes nothing)
curl -s -o /dev/null -w 'responder HTTP %{http_code}\n' -X POST "http://$(grep '^ONCALL_HOST=' /etc/fitwise-oncall.env | cut -d= -f2):8099/alerts"
# no open incident: an open one deduplicates (ignores) the next firing of the same fingerprint
ls -A /var/lib/fitwise-oncall/incidents/open 2>/dev/null | wc -l               # 0
# alert rule state from Grafana (admin password read on the host, not printed)
set -a; . <(grep -E '^GRAFANA_ADMIN_(USER|PASSWORD)=' /opt/fitwise/.env); set +a
curl -s -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" http://127.0.0.1:3000/api/prometheus/grafana/api/v1/rules |
  jq -r '.data.groups[] | select(.name=="key-journey") | .rules[] | "\(.name) state=\(.state) health=\(.health)"'
```

Expected:

| Check | Pass |
|---|---|
| `CURRENT_TAG` equals the SHA from part A (and `/healthz`) | yes |
| `PREVIOUS_TAG` | A SHA different from `CURRENT_TAG` is fine now; **after promoting the drill build it must be A**. If `PREVIOUS_TAG` is empty or equals `CURRENT_TAG` the agent's rollback exits 3 and nothing rolls back: stop and fix first (promote one more good release) |
| `ROLLED_BACK_FROM` | Does not equal the drill SHA (it would refuse with exit 4) |
| `fitwise-oncall` and `fitwise-deploy.timer` | `active` |
| `ONCALL_AGENT_ENABLED=1`, env file `600 root` | `1`, `600 root` |
| Responder | HTTP 401 |
| Open incidents | `0` |
| Rules | `KeyJourneyErrors state=inactive health=ok` (Normal) and `KeyJourneyLatency state=inactive health=ok`. `pending`/`firing` means something else is wrong: do not start. `nodata` is not expected: `noDataState` is OK |

**C. Judgement** (orchestrator): the owner has given the go for the live run in a message of their own; no other incident is open; the day's `claude` usage on the subscription leaves room for one run (also check that `--max-budget-usd` does not reject the run under subscription auth, the open question carried over from #166: look at `agent.json` and the transcript of the first minute).

## 5. Live procedure

Release A is what prod serves now. B is the drill build. `T0` is the minute errors start.

| # | Step | Who / command | Expect |
|---|---|---|---|
| 1 | Pre-flight A, B, C above | Orchestrator | All pass; note `CURRENT_TAG` (A) in the table below |
| 2 | Prepare the drill PR: `git switch -c ops/20-s1-drill main && scripts/demo-s1-enable.sh && git commit -am "DEMO S1: finish raises (drill build, revert after the drill) (#20)"`, push, `gh pr create --draft` titled `DEMO S1: ...` with a body saying "do not release to anyone; revert after the drill" | Orchestrator | CI green (guard test expects the fault) |
| 3 | Owner reviews and the orchestrator squash-merges the drill PR. Dev now serves B, dev smoke passes (the smoke does not finish a workout) | Orchestrator | `ci.yml` run on `main` for the merge SHA B: `deploy-dev` and `smoke-dev` green |
| 4 | Pre-flight A with B: `scripts/demo-s1-preflight.sh <B>` | Orchestrator | all `ok` |
| 5 | Start the stopwatch notes. Run "Promote to production": `gh workflow run promote-prod.yml --ref main -f sha=<B>`. Record the run URL | Orchestrator | `verify` green, `promote` waits for approval |
| 6 | Approve the `production` environment job | **Owner** | `deploy/prod` moves (job summary shows the time) |
| 7 | Watch the host: `journalctl -u fitwise-deploy -f -o cat` (SSM). Within about 3 to 6 minutes (poll every 150 s, deploy about 40 s) prod serves B; `curl -s <PROD>/api/v1/healthz` returns B. The health check passes, so the host does **not** roll back by itself | Orchestrator | `smoke-prod` goes green too (the e2e smoke does not finish a workout). That is expected: the release is bad only for `finish` |
| 8 | Send traffic at once: `BASE_URL=<PROD> scripts/demo-s1-traffic.sh 150 6` in a terminal that stays open for the whole drill (about 15 minutes, 10 requests per minute, only status codes are printed). Record `T0` = time of the first `HTTP 500` | Orchestrator | `HTTP 500` lines |
| 9 | Optional, owner: finish a workout in the prod UI to show the user-facing error. Do not screenshot Today or session screens (see the checklist) | Owner | Error toast |
| 10 | Wait for the alert. Rule evaluates every 1 min, `for: 0s`, the 5 min window needs at least 20 requests, so expect **KeyJourneyErrors firing about 2 to 4 minutes after T0** (20 requests take 2 minutes at this rate, then up to one evaluation and `group_wait` 10 s). Record the time of the webhook in the responder log: `journalctl -u fitwise-oncall -o cat --since -15min`, and `incidents/<id>/incident.json` (`opened_at`) | Orchestrator watches | One incident folder in `/var/lib/fitwise-oncall/incidents/`. If nothing fires 8 minutes after T0, see "If it does not go as planned" |
| 11 | The agent runs (about 3 to 10 minutes; hard timeout 20). Do not interfere. Watch only: `journalctl -u fitwise-oncall -f -o cat`; `ls /var/lib/fitwise-oncall/incidents/<id>/` | Orchestrator watches | `mitigation.json` appears: the command `oncall/ops/rollback.sh`; `journalctl -u fitwise-deploy` shows `rollback: B -> A`; `/healthz` returns A. Record the mitigation time |
| 12 | Recovery: with the traffic script still running, the 5xx ratio of `finish` falls under 5 % once the failing requests leave the 5 min window, so the alert resolves about **5 to 7 minutes after the rollback**. Record the `resolved` time | Orchestrator | Rule back to Normal; the agent reports recovery (it checks for 5 minutes) |
| 13 | The agent opens the incident issue (label `incident`) and a fix PR on branch `oncall/<id>`. Record both links | On-call agent | Issue has timeline, evidence, mitigation, recovery. PR is a revert of the drill or an equivalent fix |
| 14 | No retry: wait 5 minutes (two polls) and check `journalctl -u fitwise-deploy --since -8min -o cat`: B is not redeployed. `cat /opt/fitwise/CURRENT_TAG` is A, `ROLLED_BACK_FROM` is B | Orchestrator | Prod stays on A |
| 15 | Revert the drill on `main` so dev leaves the broken build and the fix is real: owner reviews and merges the agent's fix PR if it removes the fault and keeps `test_shipped_build_has_no_demo_fault` green; otherwise `git revert <drill merge>` as a normal PR. After merge, dev is healthy again (smoke-dev) | Owner merges, orchestrator | `main` has `S1_FINISH_RAISES = False` |
| 16 | Promote the fix through the same workflow (steps 5 and 6 with the fix SHA C); verify `/healthz` is C and `finish` answers 401 (not 500) to `scripts/demo-s1-traffic.sh 3 1` | Orchestrator, owner approves | Prod on C. Record the run link |
| 17 | Fill in the evidence table, redact (section 7), attach to #20, run the post-drill checks below | Orchestrator | |

### Post-drill checks

```bash
# no secret reached the journals or the incident folder
journalctl -u fitwise-deploy -u fitwise-oncall --since -2h | grep -Ei 'ghp_|github_pat_|ghs_|sk-ant|oauth|bearer' ; echo "exit $? (1 = nothing found)"
grep -rEil 'ghp_|github_pat_|ghs_|sk-ant|oauth' /var/lib/fitwise-oncall/incidents/<id>/ ; echo "exit $? (1 = nothing found)"
# the allow-list held: the guard log lists only allowed calls, one mitigation
cat /var/lib/fitwise-oncall/incidents/<id>/mitigation.json
```

The transcript is mode 0600 and stays on the host; only an excerpt checked against section 7 goes into the issue.

### If it does not go as planned

| Symptom | Do |
|---|---|
| Prod never serves B, `smoke-prod` fails with "host may have rolled back" | Host rolled back by itself (health check). Read `journalctl -u fitwise-deploy`; B is not retried. Fix the cause (not a drill failure) and start again from step 5 only after `PREVIOUS_TAG` is sane |
| No alert 8 minutes after T0 | Check that traffic reaches the route: Grafana Key journey dashboard, `env=prod`; count of requests in the 5 min window is at least 20 (increase the pace: `scripts/demo-s1-traffic.sh 150 3`); check rule health in Grafana. If metrics show 500s but the rule stays Normal, it is a bug in the rule: stop, and record it on #18/#97 |
| Alert fires, no agent run | `systemctl status fitwise-oncall`, `journalctl -u fitwise-oncall`; `launched` file missing in the incident folder. The owner can restart the service (it re-runs the launcher for open incidents that never reached it) |
| Agent hits the budget, the timeout, or does nothing | Do **not** run `rollback.sh` for it unless the owner decides to end the drill: then use the "Rollback production" workflow or `sudo /opt/fitwise/bin/rollback.sh` and record that the agent did not mitigate |
| Rollback exit 3 or 4 | `PREVIOUS_TAG` empty or equal to current (3), or target is the release that was rolled back from (4). Nothing changed. The release stays; stop the traffic, run "Rollback production" (it reads the history), and fix `PREVIOUS_TAG` handling in the runbook |
| Users are really affected | This is prod. If the drill must end immediately, stop the traffic and run "Rollback production" |

## 6. Rollback caveats (read before step 5)

- **Migrations.** `rollback.sh` never runs migrations or down-migrations (D50). Before the drill, check whether the drill build B or release A sit on both sides of a migration: `alembic current` on the host before and after (`docker exec $(docker ps -qf name=backend) alembic current`). The drill commit adds none.
- **After rolling back past migration `a9c3e7f1b402` (CSV import, #57, D90)**, the previous release returns 500 when opening an imported (plan-less) session by id. This applies if prod ever holds imported sessions and a rollback goes to a release older than that migration. The manual step is `DELETE FROM session WHERE imported;` on the production database (the sets cascade; athletes can upload the CSV again). It deletes user data, so it is **never automated**, not on the on-call allow-list, and needs the owner's explicit confirmation each time. Check first: `SELECT count(*) FROM session WHERE imported;`. For S1 it applies only if A is older than that migration (compare `alembic current` before the drill with the revision above) and prod holds imported sessions; the drill rolls back from B to A, and both are normally newer.
- The poller does not redeploy the rolled-back tag; only a `deploy/prod` move does. The fix is promoted through the workflow.

## 7. Evidence

Keep these (spec §15.2): the alert, `incidents/<id>/` (redacted excerpts), the agent's transcript (excerpt), the incident issue and the fix PR. Copy this table into #20 and the PR as the drill is done.

| Item | Value |
|---|---|
| Release A (prod before, rollback target) | `<sha>` |
| Drill build B (merge SHA of the drill PR) | `<sha>`, PR #`<n>` |
| Promote run (B) and approval time | `<run link>`, `<UTC>` |
| Prod serves B (first `/healthz`) | `<UTC>` |
| First 500 from `finish` (T0) | `<UTC>` |
| **Alert fired** (`KeyJourneyErrors`, route `/api/v1/sessions/{session_id}/finish`) | `<UTC>` |
| Agent started / first query | `<UTC>` |
| **Mitigation** (`oncall/ops/rollback.sh`, exit code) | `<UTC>`, `<exit>` |
| Prod serves A again (first `/healthz`) | `<UTC>` |
| **Recovered** (alert resolved / ratio under 5 % for 5 min) | `<UTC>` |
| **Alert to recovery** | `<minutes>` |
| Alert to mitigation | `<minutes>` |
| Incident issue | `#<n>` |
| Fix PR (agent's) | `#<n>` |
| Fix promoted (C) and run | `<sha>`, `<run link>` |
| `--max-budget-usd` enforced under subscription auth (from #166) | `<yes/no, evidence>` |
| Guard log: allow-list respected, one mitigation | `<yes/no>` |
| Secret grep results (post-drill checks) | `<clean/not clean>` |

### Redaction checklist (health data and secrets; rule 6)

Tick every item before any screenshot, log excerpt or transcript leaves the host or goes into an issue or PR.

- [ ] Only `user_hash` and `trace_id` identify anyone. No email, name, password, token, session cookie.
- [ ] No body metrics (weight, height, body fat), targets, calories, set weights/reps, food names, meal contents or notes. **No screenshot of Today, Calendar, Charts, Plan, Meals, Settings or any athlete page.** Use only the Grafana Key journey dashboard, GitHub pages and terminals.
- [ ] Dashboards: the `env=prod` filter is visible; no panel with user-level data is open.
- [ ] Terminal excerpts: no `.env` content, no `GH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `ONCALL_WEBHOOK_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`; the Grafana admin password block of the pre-flight prints nothing, keep it that way. Prompts and shell history are cropped.
- [ ] Hostnames are fine, but the prod Elastic IP and instance ids are cropped when the repo is public (owner's preference; default: crop).
- [ ] Agent transcript: read it end to end for pasted log lines or API responses before quoting any of it. Quote the commands and the reasoning, not payloads.
- [ ] Incident issue and PR text: timeline, route, ratios, SHAs, `service_version`, `trace_id`s only. A request body, a response body or a `Problem` detail from a real user is never pasted.
- [ ] The traffic script output holds only times and status codes (it sends no body or cookie), so it can be pasted as is.
- [ ] `grep -Ei 'ghp_|github_pat_|ghs_|sk-ant|bearer'` over everything attached prints nothing.
- [ ] Workflow run logs linked from the issue are public: check the promote and smoke logs for the same items once.
