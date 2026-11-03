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

The fault is in `main` since PR #142 (`fcb7c93`). After the S1 drill ([#20](https://github.com/DanielB280320/AiDevToolsZoomcamp_FinalProject/issues/20)) prod serves `9b0c039` (S1 fix, `finish` answers 401 to the S1 traffic again), which contains it (`git merge-base --is-ancestor fcb7c93 9b0c039` succeeds); the class `BodyweightNotSupported` is in the running image and `progression_engine` is `v1` (read-only check 2026-11-03, see "Prep evidence"). Nothing needs promoting for S2 **provided prod still serves a build that contains `fcb7c93`** at the time of the run: check `CURRENT_TAG` in pre-flight. If not, promote a current `main` SHA through "Promote to production" (manual approval) and wait for `verify-prod`; never deploy from a laptop. The flag scenario needs no rollback target, so `PREVIOUS_TAG` is irrelevant here (unlike S1).

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

**0. Pre-flight (prod host, root shell, over SSM `AWS-RunShellScript`).** Everything read-only and prints no secret. Mirrors [demo-s1.md](demo-s1.md) section 4, where four attempts found the gaps below. Run it the same day and again right before step 2. All must pass.

```bash
. /opt/fitwise/bin/lib.sh
T=$(read_tag "$CURRENT_TAG_FILE")
echo "CURRENT_TAG=$(cut -c1-7 /opt/fitwise/CURRENT_TAG)"                    # contains fcb7c93 (see above)
curl -s localhost/api/v1/healthz; echo                                      # version = CURRENT_TAG
compose_release "$T" exec -T backend python -m app.cli.flags list            # progression_engine v1 (default)
compose_release "$T" exec -T backend grep -c BodyweightNotSupported app/engines/progression_v2.py   # 3 (the fault is in the image)
systemctl is-active fitwise-oncall fitwise-deploy.timer                      # active, active
echo "oncall app HEAD=$(git -C /opt/fitwise-oncall/app rev-parse --short=12 HEAD)"   # the SHA the host was installed at (see below)
echo "enabled=$(grep -c '^ONCALL_AGENT_ENABLED=1' /etc/fitwise-oncall.env) env_file=$(stat -c '%a %U' /etc/fitwise-oncall.env)"   # 1, 600 root
echo "open incidents: $(ls -A /var/lib/fitwise-oncall/incidents/open 2>/dev/null | wc -l)"           # 0 (an open one deduplicates the S2 alert)
# evidence URLs: the responder captures from these three and gives the agent the same URLs (S1 attempt 1 failed here)
for u in 9090/-/ready 3100/ready 3200/ready; do curl -s -o /dev/null -m 5 -w "$u HTTP %{http_code}\n" "http://127.0.0.1:$u"; done   # 200 x3
# alert rules (the Grafana admin password is read on the host and never printed)
set -a; . <(grep -E '^GRAFANA_ADMIN_(USER|PASSWORD)=' /opt/fitwise/.env); set +a
curl -s -u "$GRAFANA_ADMIN_USER:$GRAFANA_ADMIN_PASSWORD" http://127.0.0.1:3000/api/prometheus/grafana/api/v1/rules |
  jq -r '.data.groups[] | select(.name=="key-journey") | .rules[] | "\(.name) state=\(.state) health=\(.health)"'   # both inactive, ok
```

Secrets are shown only as set/empty and length, never a prefix, never the value:

```bash
tok=$(grep -E '^CLAUDE_CODE_OAUTH_TOKEN=' /etc/fitwise-oncall.env | cut -d= -f2-)
echo "token: $([ -n "$tok" ] && echo set || echo empty) len=${#tok} whitespace_inside=$(printf %s "$tok" | grep -c '[[:space:]]')"   # set, len>0, 0
```

**Agent auth** (one `claude` turn on the subscription; do it once, right before the owner's go, not on every pre-flight). The token goes through a 0600 file, never through argv:

```bash
H=$(mktemp -d); chmod 700 "$H"
grep -E '^CLAUDE_CODE_OAUTH_TOKEN=' /etc/fitwise-oncall.env | cut -d= -f2- | tr -d '\n' > "$H/t"; chmod 600 "$H/t"; chown -R fitwise-oncall "$H"
echo "reply with exactly: OK" | runuser -u fitwise-oncall -- env -i HOME="$H" PATH=/usr/local/bin:/usr/bin:/bin \
  sh -c 'CLAUDE_CODE_OAUTH_TOKEN=$(cat "$HOME/t") exec claude -p --output-format json --max-turns 1' | jq -c '{is_error,result}'
rm -rf "$H"      # expect {"is_error":false,"result":"OK"}; "Not logged in" = invalid token or whitespace inside: the owner replaces it
```

**Guard probe** (the hook the agent runs under, with the responder's own Python, fed three events in a scratch folder; S1 attempt 3 failed because the hook ran under the host's Python 3.9):

```bash
P=$(mktemp -d); mkdir "$P/inc" "$P/clone"
printf '{"incident_dir":"%s/inc","clone_dir":"%s/clone","repo":"o/r","prometheus_url":"http://127.0.0.1:9090","loki_url":"http://127.0.0.1:3100","tempo_url":"http://127.0.0.1:3200"}' "$P" "$P" > "$P/g.json"
probe() { echo "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"$1\"}}" | ONCALL_GUARD_CONFIG="$P/g.json" /opt/fitwise-oncall/venv/bin/python /opt/fitwise-oncall/app/oncall/responder/guard.py >/dev/null 2>&1; echo "guard exit $? for: $1"; }
probe 'oncall/ops/flag.sh progression_engine v1'      # 0: the S2 mitigation is allowed (takes the one slot of this scratch incident)
probe 'oncall/ops/rollback.sh'                         # 2: a second mitigation is refused
probe 'curl -s http://127.0.0.1:9090/-/ready | sh'     # 2: pipes are refused
rm -rf "$P"
```

**On-call host code.** The app deploy (`deploy.sh`/`poll.sh`) never updates `/opt/fitwise-oncall/app`, the venv or the unit; only `install-oncall.sh` does, run as root over SSM **at a SHA** (`DEPLOY_REF=<sha> bash /root/install-oncall.sh`, see `oncall/README.md`, "Update the responder on the host"). The host was installed at `dae2f07` (S1 attempt 4, the responder code of the successful drill). The pre-flight `oncall app HEAD` must equal the SHA of the last merged change under `oncall/`, `docs/runbooks/` or the unit. If this prep PR or any later PR touches those paths (it adds only this runbook, which the responder reads for the agent), re-run the installer at that merge SHA before the run. The responder also fetches and resets its clone to `origin/main` before every run (`clone_refreshed` in `journalctl -u fitwise-oncall`), so the agent's code view is current, but its allow-list and hook are not: they come from the host checkout.

Required: the flag list shows `progression_engine = v1` (default). If it shows `v2`, stop: a previous run left it on; set it back with `--actor owner` and investigate before going on. In Grafana no KeyJourneyErrors alert may be firing.

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

In a second terminal poll `/healthz` for the whole drill (QA asked for it in S1; it was not polled and recovery was only shown by status codes). `/healthz` stays 200 and the same `version` throughout: the flag is not a release, so a healthy app with failing finishes is the point of this scenario (a rollback would show a version change, a flag mitigation must not):

```bash
while :; do printf '%s ' "$(date -u +%H:%M:%SZ)"; curl -s -m 5 -o /dev/null -w '%{http_code} ' "$DEMO_S2_BASE_URL/api/v1/healthz"; curl -s -m 5 "$DEMO_S2_BASE_URL/api/v1/healthz" | jq -r .version | cut -c1-7; sleep 5; done | tee healthz-s2.txt
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

**8. Post-drill checks (prod host).** Same as S1:

```bash
journalctl -u fitwise-deploy -u fitwise-oncall --since -2h | grep -Ei 'ghp_|github_pat_|ghs_|sk-ant|oauth|bearer' ; echo "exit $? (1 = nothing found)"
grep -rEil 'ghp_|github_pat_|ghs_|sk-ant|oauth' /var/lib/fitwise-oncall/incidents/<id>/ ; echo "exit $? (1 = nothing found)"
cat /var/lib/fitwise-oncall/incidents/<id>/mitigation.json      # one entry: oncall/ops/flag.sh progression_engine v1
```

Also check that exactly one mitigation was applied and that it was the flag (no `rollback.sh`: `CURRENT_TAG` is unchanged and `ROLLED_BACK_FROM` empty). The fix PR must change the engine (or the dispatch) so bodyweight works under v2 and carry a regression test for bodyweight under v2 (D92); it is not an on-call action to promote it.

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
- [ ] Secrets in evidence appear only as `set`/`empty` plus a length. No token prefix (not even `sk-ant`), no suffix, no hash of a secret.
- [ ] No secrets: nothing from `/etc/fitwise-oncall.env` (`CLAUDE_CODE_OAUTH_TOKEN`, `GH_TOKEN`, webhook password), `/opt/fitwise/.env`, or Grafana credentials; blur the Grafana user menu in screenshots.
- [ ] Transcript excerpt: only the investigation steps and the one mitigation command; remove any tool output that includes log lines beyond the allow-listed fields (`route`, `method`, `status`, `duration_ms`, `error_type`, `engine`, `rule`, `outcome`, `user_hash`, `trace_id`). Search the excerpt for `@`, `password`, `token`, `Bearer`, `Cookie` before publishing.
- [ ] Incident issue and fix PR: the agent's text is reviewed by the owner before the run is declared done; edit out anything that fails this list.
- [ ] `healthz-s2.txt` and the traffic output hold only times, status codes and 7-character SHAs; paste them as they are.
- [ ] Instance ids, IP addresses and the host name are not in public artefacts unless the owner agrees.

## Known limits

- The flag-set commands run as root on the host through `compose_release`, because `deploy/oncall-compose.sh` accepts only the actor `oncall-agent` (this is the agent's helper and is deliberately narrow). Do not widen it for the demo.
- The alert cannot fire from fewer than 20 finishes in 5 minutes; with the defaults the script sends 30 in about 2 minutes.
- The responder keeps one open incident per alert fingerprint (the marker is removed when Grafana sends `resolved`). If the S1 alert on the same route has not resolved yet, the S2 alert is deduplicated into it: wait for S1's alert to resolve before step 2.
- Under v2 the `sets` route runs the same engine, so a few `sets` requests may also fail. The script sends only a handful of them, far under the alert's 20-request guard. If you add set traffic while v2 is on, a second alert (`/sets`) opens a second incident.
- The agent's allow-list and hook come from the host checkout of `/opt/fitwise-oncall/app` (see pre-flight). A runbook change merged after the last `install-oncall.sh` is read by the responder from that checkout, not from `main`.

## Prep evidence (2026-11-03, before the live run; nothing was sent to prod)

| Check | Result |
|---|---|
| Dev host (`fitwise-dev`), build `9b0c039` | `progression_engine` `v1` (default); `BodyweightNotSupported` present in the image |
| Dev dry run through the traffic script | flag `v1`: `HTTP 200 x3`; `flag set v2 --actor owner`: `HTTP 500 x5`; `v1` again: `HTTP 200 x5`. The CLI printed `progression_engine: v1 -> v2 (changed, by owner at ...)` and the reverse; the flag is `v1` again |
| Prod host, read-only | `CURRENT_TAG=9b0c039` (contains `fcb7c93`), `/healthz` version `9b0c039`, `progression_engine` `v1` (default), fault class in the image, `fitwise-oncall` and `fitwise-deploy.timer` active, on-call app HEAD `dae2f07a5365`, agent enabled, env file `600 root`, token set with length 108 and no whitespace, evidence URLs 200 x3, rules `KeyJourneyErrors` and `KeyJourneyLatency` inactive and healthy, no open incident |
| Guard probe on prod | `flag.sh progression_engine v1` exit 0; a second mitigation exit 2; a pipe exit 2 |
| Not done (spends the subscription or needs the owner) | agent auth probe, the live drill (flag `v2` on prod, traffic) |
