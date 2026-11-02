# Demo S2: faulty progression engine v2, flag rollback

Scenario S2 of [spec §15.3](../spec.md#153-demo-scenarios-documented-in-docsrunbooks) (issue #33): the flag `progression_engine` is set to `v2`, whose demo-only fault ([#86](https://github.com/DanielB280320/AiDevToolsZoomcamp_FinalProject/issues/86)) raises on bodyweight exercises, so `POST /api/v1/sessions/{session_id}/finish` returns 500. KeyJourneyErrors fires on prod, the on-call agent applies **one** mitigation, `oncall/ops/flag.sh progression_engine v1`, verifies recovery, opens an incident issue and a fix PR. Index: [README](README.md). Alert runbook the agent follows: [key-journey-errors.md](key-journey-errors.md).

**Who runs it:** the owner or the orchestrator, never the agent. **When:** after the S1 drill ([#20](https://github.com/DanielB280320/AiDevToolsZoomcamp_FinalProject/issues/20), D53 ordering) has finished and its incident is closed. **Where:** prod (`fitwise-prod`), only with the owner's explicit go-ahead for the run. Try the traffic script on dev or a local stack first (section "Dry run").

## What happens

| Step | Who | Expected |
|---|---|---|
| Pre-flight | operator | S1 is over, prod serves a build that contains #86, `progression_engine` is `v1`, no open incident, responder active |
| Fault on | operator | `flag.sh progression_engine v2` (actor `owner`); effective within 5 s |
| Traffic | operator | 30+ finishes of a bodyweight session in about 2 minutes: all answer 500 |
| Alert | Grafana | KeyJourneyErrors on route `/api/v1/sessions/{session_id}/finish`; evaluation every 1 min, `for: 0s`, group wait 10 s: expect it **2 to 3 minutes after the first failing request** (needs at least 20 requests in the 5-minute window and a ratio above 5 %) |
| Agent | responder | webhook, `incidents/<id>/`, headless Claude Code; investigates (it sees 500s with `error_type`, `engine=v2`); runs `flag.sh progression_engine v1` |
| Recovery | operator + agent | finishes answer 200 again; the 5xx ratio is under 5 % and **stays under for 5 minutes** |
| Follow-up | agent | incident issue (label `incident`) and a fix PR on a branch (fix v2 for bodyweight plus a test) |

## Which build prod runs

The fault is in `main` since PR #142 (`fcb7c93`), and `deploy/prod` points at `79f16a8`, which contains it; any later `main` commit contains it too. Nothing needs promoting for S2 **provided prod still serves a build from `79f16a8` or later after S1**. S1 promotes a faulty build and rolls back to `PREVIOUS_TAG`; check in pre-flight that the tag prod ends up on (`CURRENT_TAG`) is an ancestor-or-equal of a commit that contains `fcb7c93`, i.e. `git merge-base --is-ancestor fcb7c93 <CURRENT_TAG>` succeeds. If S1 left prod on an older tag, promote a current `main` SHA through "Promote to production" first (manual approval) and wait for `verify-prod`; do not deploy from a laptop.

## Prerequisites

- The dedicated test account (fake data, never a real user). Pick an address on the reserved `.test` domain and a random password; keep both in your shell only, not in git, issues or chat:

  ```bash
  export DEMO_S2_EMAIL=demo-s2@example.test
  export DEMO_S2_PASSWORD="$(openssl rand -hex 16)"
  export DEMO_S2_BASE_URL=https://<prod-host>      # frontend/nginx base URL, no /api suffix
  export DEMO_S2_ALLOW_REMOTE=1                      # required for any host that is not localhost
  ```

- Grafana open on the "Key journey" dashboard (`d/fitwise-key-journey`, `env=prod`) for the screenshot.
- A root shell on `fitwise-prod` (owner: `aws ssm start-session --target <instance-id> --region us-east-2`, see [deploy/README.md](../../deploy/README.md)).

## Live commands, in order

Times are UTC. Note each in the evidence table below as you go.

**0. Pre-flight (prod host, root shell).** Everything read-only.

```bash
cat /opt/fitwise/CURRENT_TAG /opt/fitwise/PREVIOUS_TAG       # the build prod serves; contains fcb7c93 (see above)
systemctl is-active fitwise-oncall                            # active
ls /var/lib/fitwise-oncall/incidents                          # note existing incidents (a new one will appear)
. /opt/fitwise/bin/lib.sh
compose_release "$(read_tag "$CURRENT_TAG_FILE")" exec -T backend python -m app.cli.flags list
```

Required: the `list` output shows `progression_engine = v1` (default). If it shows `v2`, stop: a previous run left it on; set it back with `flag.sh ... v1` and investigate before going on. Also check in Grafana that no KeyJourneyErrors alert is firing.

**1. Create the test account and check the traffic script on prod with the flag still `v1`** (from your machine):

```bash
scripts/demo-s2-traffic.py --signup --requests 3 --interval 1 --expect ok
```

Expected: `HTTP 200 x3`. This creates the account (fake data) and a plan with bodyweight exercises; three 200s stay far below the 20-request threshold.

**2. Fault on (prod host, root shell).** The `owner` actor keeps the injected fault distinguishable from the agent's mitigation in the audit trail:

```bash
. /opt/fitwise/bin/lib.sh
compose_release "$(read_tag "$CURRENT_TAG_FILE")" exec -T backend \
  python -m app.cli.flags set progression_engine v2 --actor owner --log-stream /proc/1/fd/1
```

Note the time `T0`. Wait 6 s (flag cache is 5 s).

**3. Traffic (your machine).** 30 finishes, one every 4 s (about 2 minutes), all expected to fail:

```bash
scripts/demo-s2-traffic.py --requests 30 --interval 4 --expect errors
```

Expected: `HTTP 500 x30 (30 errors)`. The script logs the planned sets only while the session is not done (editing sets of a finished session also runs the engine and would 500 on the `sets` route under v2, which would raise a second alert), so after the first run it only sends finishes. Add `--requests 45` if Grafana still shows fewer than 20 requests in the window.

**4. Alert (Grafana).** KeyJourneyErrors should fire about 2 to 3 minutes after the first 500 and the responder should create `incidents/<id>/`. Screenshot the firing alert and the dashboard (placeholders below). Do not touch anything while the agent works; it has a 20-minute timeout.

**5. Keep light traffic going so recovery is observable.** Right after the agent applies the flag (look for `mitigation.json` in the incident folder), run successful finishes; they also prove the user-visible fix:

```bash
scripts/demo-s2-traffic.py --requests 90 --interval 5 --expect ok
```

Expected: `HTTP 200 x90` (about 7.5 minutes). The ratio drops under 5 % once the 500s leave the 5-minute window; recovery is "under 5 % for 5 minutes". Failing requests of step 3 count against the window until they age out, so allow about 10 minutes after the mitigation. If the agent has not mitigated, the first finishes of this run return 500 and `--expect ok` exits 1: that is the evidence the incident is still open.

**6. Verify (prod host, read-only).**

```bash
. /opt/fitwise/bin/lib.sh
compose_release "$(read_tag "$CURRENT_TAG_FILE")" exec -T backend python -m app.cli.flags list    # progression_engine = v1
ls -l /var/lib/fitwise-oncall/incidents/<id>/                                                    # mitigation.json, transcript, issue.md, pr.md
```

**7. Clean up.** Flag must be `v1` (the agent's mitigation does that; if not, run the `set ... v1` command of step 2 with `--actor owner`). The test account can stay for a repeat run; account deletion is a destructive action that needs the owner's confirmation each time (`POST /me/delete`).

## Dry run (no prod)

Same script, same expectations, any other stack. Local (own compose project and port):

```bash
cp -n .env.example .env
COMPOSE_PROJECT_NAME=fitwise-s2 HTTP_PORT=18433 COMPOSE_FILE=compose.yaml:compose.ci.yaml docker compose up --build --wait
export DEMO_S2_BASE_URL=http://localhost:18433 DEMO_S2_EMAIL=demo-s2@example.test DEMO_S2_PASSWORD="$(openssl rand -hex 16)"
scripts/demo-s2-traffic.py --signup --requests 5 --interval 0 --expect ok
FLAG_ACTOR=owner COMPOSE="docker compose" oncall/ops/flag.sh progression_engine v2     # same COMPOSE_* variables as above
scripts/demo-s2-traffic.py --requests 5 --interval 0 --expect errors
oncall/ops/flag.sh progression_engine v1
scripts/demo-s2-traffic.py --requests 5 --interval 0 --expect ok
```

On dev, set `DEMO_S2_ALLOW_REMOTE=1` and run the flag commands on the dev host as in step 2. Dev is not in the alert's scope (`env=prod`), so no page is raised there.

## Evidence to keep (spec §15.2)

Fill in after the run and link from [#33](https://github.com/DanielB280320/AiDevToolsZoomcamp_FinalProject/issues/33).

| Item | Value |
|---|---|
| Prod build during the run (`CURRENT_TAG`) | `<sha>` |
| Flag set to v2 (`T0`, UTC) | `<time>` |
| First failing request | `<time>` |
| Alert fired | `<time>` (delay from first failure: `<mm:ss>`) |
| Agent started / mitigation (`flag.sh progression_engine v1`) applied | `<time>` / `<time>` |
| Error ratio back under 5 % for 5 min | `<time range>` |
| Alert and dashboard screenshot | `<link or path; screenshot only after the redaction check below>` |
| Incident folder | `incidents/<id>/` on `fitwise-prod` (`/var/lib/fitwise-oncall/incidents/<id>/`) |
| Transcript excerpt | `incidents/<id>/transcript` (stream-json, mode 0600); excerpt of the investigation and the `flag.sh` call: `<link to the excerpt>` |
| Incident issue | `<#N>` |
| Fix PR | `<#N>` (fix v2 for bodyweight plus a regression test; goes through CI, QA and "Promote to production") |

## Health-data redaction checklist

Before anything from this run leaves the host (screenshots, transcript excerpts, issue text, PR text):

- [ ] The test account's email and password appear nowhere: not in the shell history you paste, the transcript, the issue or the PR. (The script prints neither; the backend logs neither.)
- [ ] Users appear only as `user_hash`. No names, emails, tokens, cookies, `Authorization` headers.
- [ ] No body metrics, weights, reps, food names, exercise names tied to a person, or notes. The account is fake, but treat the output as if it were real.
- [ ] No secrets: nothing from `/etc/fitwise-oncall.env` (`CLAUDE_CODE_OAUTH_TOKEN`, `GH_TOKEN`, webhook password), `/opt/fitwise/.env`, or Grafana credentials; blur the Grafana user menu in screenshots.
- [ ] Transcript excerpt: only the investigation steps and the one mitigation command; remove any tool output that includes log lines beyond the allow-listed fields (`route`, `method`, `status`, `duration_ms`, `error_type`, `engine`, `rule`, `outcome`, `user_hash`, `trace_id`). Search the excerpt for `@`, `password`, `token`, `Bearer`, `Cookie` before publishing.
- [ ] Incident issue and fix PR: the agent's text is reviewed by the owner before the run is declared done; edit out anything that fails this list.
- [ ] Instance ids, IP addresses and the host name are not in public artefacts unless the owner agrees.

## Known limits

- The flag-set commands run as root on the host through `compose_release`, because `deploy/oncall-compose.sh` accepts only the actor `oncall-agent` (this is the agent's helper and is deliberately narrow). Do not widen it for the demo.
- The alert cannot fire from fewer than 20 finishes in 5 minutes; with the defaults the script sends 30 in about 2 minutes.
- The responder keeps one open incident per alert fingerprint (the marker is removed when Grafana sends `resolved`). If the S1 alert on the same route has not resolved yet, the S2 alert is deduplicated into it: wait for S1's alert to resolve before step 2.
