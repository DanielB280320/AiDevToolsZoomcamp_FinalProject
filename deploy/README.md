# Deploy: AWS hosts (issue #12)

Scripted provisioning for the two FitWise hosts (spec section 12). IaC is a roadmap item, so these are idempotent AWS CLI scripts.

| | dev | prod |
|---|---|---|
| Name | `fitwise-dev` | `fitwise-prod` |
| Region | us-east-2 | us-east-2 |
| Instance type | t3.small (2 vCPU, 2 GiB) | c7i-flex.large (2 vCPU, 4 GiB), runs Prometheus/Loki/Tempo/Grafana + responder (ADR 0006) |
| OS | Amazon Linux 2023 (x86_64) | same |
| Disk | 30 GiB encrypted gp3 | 30 GiB encrypted gp3 |
| Public address | Elastic IP | Elastic IP |

Prod is a c7i-flex.large rather than the originally planned t3.medium because the AWS account is on the Free plan, which rejects t3.medium (`not eligible for Free Tier`) but allows c7i-flex.large.

All resources are tagged `Project=fitwise`, `Env=dev|prod`.

## Expected monthly cost (us-east-2, on-demand list prices, approximate)

| Item | dev | prod |
|---|---|---|
| EC2 | ~$15 (t3.small, $0.0208/h) | ~$62 (c7i-flex.large, ~$0.085/h) |
| EBS 30 GiB gp3 | ~$2.4 | ~$2.4 |
| Public IPv4 / Elastic IP ($0.005/h) | ~$3.6 | ~$3.6 |
| Total | ~$21 | ~$68 |

About **$89/month** for both hosts (approved by the owner on 2026-10-24). Free-plan credits may offset part of it. IAM, security groups and SSM are free. Data transfer and the S3 backup bucket (#66) are extra. Re-check the EC2 prices on the AWS pricing page before relying on them.

## Access method: SSM, not SSH

Port 22 is closed on both hosts and there is no key pair. Reasons: no long-lived SSH keys to store or lose, no need to open 22 to GitHub's very large and changing IP ranges, and SSM gives audited sessions. Instances carry the `fitwise-ec2-ssm` instance profile (managed policy `AmazonSSMManagedInstanceCore`, nothing else).

- Owner shell: `aws ssm start-session --target <instance-id> --region us-east-2` (needs the Session Manager plugin), or run commands with `aws ssm send-command`.
- Deploys do not use SSM or any AWS credential: see "Deploys are pull-based" below.

## Security groups (`fitwise-dev`, `fitwise-prod`)

| Port | Source | Applies to |
|---|---|---|
| 80 | 0.0.0.0/0 | both |
| 22 | closed (SSM) | both |
| 3000 (Grafana) | owner IP /32 (auto-detected, override with `OWNER_CIDR`) | prod |
| 4317 (OTLP gRPC) | dev Elastic IP /32 | prod |

Re-running `provision.sh` makes ports 3000 and 4317 allow exactly the detected owner IP (or `OWNER_CIDR`) and the dev Elastic IP: a stale CIDR on those ports is revoked and the new one added, so a changed owner IP is fixed by re-running.

## Steps

1. Credentials for the AWS CLI with permission to manage EC2/IAM/SSM (the owner or an approved agent).
2. `deploy/provision.sh` creates (or finds) the IAM instance profile, security groups, instances, Elastic IPs, and prints IDs and addresses. Overrides: `AWS_REGION`, `OWNER_CIDR`, `DEV_TYPE`, `PROD_TYPE`.
3. `deploy/bootstrap-remote.sh dev|prod` ships `deploy/bootstrap.sh` to the host over SSM and runs it. It installs Docker and the Compose plugin, creates the `deploy` user (in the `docker` group), creates `/opt/fitwise` with empty `CURRENT_TAG` and `PREVIOUS_TAG`, a root-only (`0600`) `.env`, and runs an `nginx:alpine` placeholder named `fitwise-placeholder` on port 80 until the first real deploy (#13) replaces it. Running it again changes nothing.
4. Check: `curl -i http://<elastic-ip>/` returns 200.

## Deploys are pull-based (no deploy credentials)

GitHub holds no AWS keys and the hosts open no inbound ports for deployment ([ADR 0010](../docs/adr/0010-pull-based-deploy.md), spec D57). The AWS Organization policy denies GitHub OIDC and every action for IAM users, so a first attempt with per-environment IAM users was removed (issue #12).

Design, built in #13 and #14: CI pushes images to GHCR and records the approved tag by moving the git ref `deploy/dev` (after merge) or `deploy/prod` (only from the job in the `production` GitHub environment, which requires approval). A systemd timer on each host polls that ref through the public GitHub API, pulls, deploys, health-checks and rolls back to `PREVIOUS_TAG` by itself. This requires the repository and GHCR packages to be public.

### How dev is deployed (issue #13)

```
merge to main -> CI (all gates) -> publish: images ghcr.io/<owner>/fitwise-{backend,frontend}:<sha>, digests recorded
              -> deploy-dev (environment `dev`, GITHUB_TOKEN, contents: write): moves branch ref deploy/dev
              -> dev host: fitwise-deploy.timer (every 150 s) -> poll.sh -> deploy.sh
              -> smoke-dev: waits for GET /api/v1/healthz `version` == <sha>, then the e2e smoke test
```

- **The ref.** `deploy/dev` is a branch moved only by the `deploy-dev` job. It points at a *deploy commit*: tree = the tree of the previous deploy commit (so no `.github/workflows` change; see "Deploy commit tree"). The existing `deploy/dev` and `deploy/prod` refs keep the release tree of `5005280` (they predate the fix, #14) and every later deploy commit reuses the previous deploy commit's tree; only a brand-new ref starts from a README-only tree (the first deploy commit has no parent; every later one has the previous deploy commit as parent), message = the release record (`source:` SHA, `backend:` and `frontend:` image references with their `@sha256:` digests, and, when written by a workflow run, `run:` with the Actions run id; the host ignores it). One `GET /repos/<repo>/branches/deploy/dev` returns it, so a poll needs one API request and no credentials.
- **Rate limit.** One conditional request (`If-None-Match`) per 150 s = 24 per hour; the limit is 60 per IP. Compose files come from `raw.githubusercontent.com` and images from GHCR, neither counts against the API limit. A 403/429 is logged and skipped.
- **Deploy (`deploy.sh`).** Fetch that commit's `compose.yaml` and `deploy/compose.deploy.yaml` into `/opt/fitwise/releases/<sha>/`, pull both images by digest, start the database, run the `migrate` one-shot on its own (a failure stops here and the old release keeps serving), `compose up -d --no-deps --wait backend frontend`, then wait up to 120 s for `/readyz` = 200 and `/healthz` `version` = the SHA. On success `PREVIOUS_TAG` = old `CURRENT_TAG` and `CURRENT_TAG` = the new SHA.
- **Automatic rollback.** Unhealthy release: `rollback.sh <old CURRENT_TAG>` starts the old release from its stored digests with **no migration step** (D50). `CURRENT_TAG` never moves to the failed SHA. First deploy with nothing to roll back to: the new containers are stopped and the nginx placeholder is restored.
- **Never retried.** `LAST_REF` holds the ref value last acted on and is written *before* deploying. A failed release stays failed until the ref moves again (a new merge, or re-running the `deploy-dev` job, which creates a new deploy commit). A manual `rollback.sh` is not undone by the poller.
- **Manual rollback** (owner, CI, on-call): `sudo /opt/fitwise/bin/rollback.sh` (target `PREVIOUS_TAG`) or `rollback.sh <sha>` for any stored release. Exit 0 = healthy, 1 = failed, 3 = no previous release (see "State after a rollback"), 4 = refused (target is the release already rolled back from).
- **State after a rollback (#122, D67).** `CURRENT_TAG` = the target. `PREVIOUS_TAG` is **left unchanged**, so after rolling back from B to A it is still A and equals `CURRENT_TAG`; it is deliberately not set to B, because a second no-argument rollback (the on-call agent can run one) would then redeploy the release just found bad. `ROLLED_BACK_FROM` holds B (after an automatic rollback: the failed release) for incident reports. A no-argument `rollback.sh` is refused when `PREVIOUS_TAG == CURRENT_TAG` (exit 3, "nothing earlier to go back to") or when its target equals `ROLLED_BACK_FROM` (exit 4); on-call then escalates to the owner. An explicit `rollback.sh <sha>` (owner, or the poller for "Rollback production") is never refused. Going forward again is "Promote to production"; a successful `deploy.sh` removes `ROLLED_BACK_FROM`. Test: `bash scripts/test-rollback-host.sh`.
- **State on the host** (`/opt/fitwise`): `CURRENT_TAG`, `PREVIOUS_TAG`, `ROLLED_BACK_FROM` (only after a rollback), `LAST_REF`, `POLL_ETAG`, `releases/<sha>/{compose.yaml,compose.deploy.yaml,release.env}` (five newest kept), `bin/` (scripts), `.env` (root-only; `bootstrap.sh` generates the database password, JWT secret and user-hash salt on the host; never printed). `/etc/fitwise-deploy.env` holds the non-secret poller settings.
- **Logs.** `journalctl -u fitwise-deploy -o cat` (UTC timestamps; only tags, digests and statuses). `systemctl list-timers fitwise-deploy.timer` shows the next poll.
- **Updating the scripts.** The poller scripts are installed by `bootstrap.sh`, not by a deploy. After changing anything under `deploy/` other than `compose.deploy.yaml` (which travels with each release), re-run `deploy/bootstrap-remote.sh dev` (idempotent; `DEPLOY_REF=<branch|sha>` installs from a branch).
- **Merge to deployed on dev** targets 10 minutes (owner, 2026-10-24): CI, then at most 150 s until the next poll, then about 40 s to deploy.

### How prod is deployed (issue #14)

```
Actions > "Promote to production" (workflow_dispatch, input: full SHA of a release proven on dev)
  verify      scripts/promote-verify.sh: ci.yml run on main for that SHA has deploy-dev AND smoke-dev = success
              (unknown SHA, failed or skipped smoke: the run fails here, before any approval is requested)
  promote     job in environment `production` (required reviewer, `contents: write`, GITHUB_TOKEN): after approval
              moves deploy/prod to a deploy commit with the SAME release record as dev (source SHA, backend and
              frontend @sha256 digests, taken from the `release-record` artifact of the dev run)
  prod host   same fitwise-deploy.timer / poll.sh / deploy.sh / rollback.sh as dev (DEPLOY_ENV=prod)
  smoke-prod  waits (12 min max) until GET /api/v1/healthz `version` == SHA, then readyz 200 and the e2e smoke
              against the `PROD_BASE_URL` variable of the `production` environment
```

- **Why the SHA check.** Prod only ever runs images that passed CI, were deployed to dev and smoke-tested there. The check reads the Actions API with the run's own `GITHUB_TOKEN` (`actions: read`); tests with a fake `gh`: `bash scripts/test-promote-verify.sh` (CI job `deploy-script-tests`).
- **Deploy commit tree.** `scripts/move-deploy-ref.sh` (used by `deploy-dev` and `promote`) builds the commit on the tree of the *current* `deploy/<env>` commit, so a ref update never changes `.github/workflows/` (GITHUB_TOKEN has no `workflows` permission; changing them is a 403), whatever release is promoted: newer, older (rollback, #113) or one that edits workflows. The host reads only the commit message (source, backend, frontend) and fetches compose files from the source SHA. Test: `bash scripts/test-move-deploy-ref.sh`.
- **Digests.** The `publish` job uploads the `release-record` artifact (90 days). A release that predates it is accepted only while `deploy/dev` still carries it.
- **Poller on prod.** Identical to dev: one conditional (`ETag`) request to `deploy/prod` every 150 s = 24 requests per hour counting 304s (limit 60), no token on the host, images pulled by digest. Install or refresh with `deploy/bootstrap-remote.sh prod` (idempotent; the timer and `/etc/fitwise-deploy.env` are only rewritten when they differ). No inbound deploy port, no credential.
- **Automatic rollback on prod.** Same as dev: if `/readyz` or the `version` check fails within 120 s, `rollback.sh <old CURRENT_TAG>` starts the previous release **without the migration step** and without any down-migration (D50), so `alembic_version` stays where it is. That is the old revision only if the failed release carried no migration; if it carried an expand-only migration the revision has advanced and is not downgraded, and the previous release keeps serving on the expanded schema (backward-compatible migrations, `/readyz` accepts a database ahead of the release). The failed ref is recorded in `LAST_REF` and not retried; the poller acts again only when `deploy/prod` moves. The smoke job then fails with a message saying the host may have rolled back. Inspect: `journalctl -u fitwise-deploy -o cat` on `fitwise-prod`.
- **Rollback demo (temporary host switch, D61).** While the line `FITWISE_DEMO_FAIL_HEALTH=1` exists in `/opt/fitwise/.env`, `deploy.sh` starts the new release and then treats the health check as failed, so the normal path runs: `rollback.sh <CURRENT_TAG>` without migration. Off by default on every host, ignored by `rollback.sh`, not read by the application, never printed. It exists only for the demo; remove it afterwards. Procedure in the PR for #14 (also below).
- **Manual rollback:** the "Rollback production" workflow (below), or `sudo /opt/fitwise/bin/rollback.sh` on the host.
- **Only `main`.** The workflow's first job runs only when dispatched from `main`.

### Rollback production (issue #113)

```
Actions > "Rollback production" (workflow_dispatch, no inputs; only from main)
  plan         scripts/rollback-plan.sh: reads the history of deploy/prod, prints "from -> to"; fails here, before any
               approval, if there is no previous release
  rollback     job in environment `production` (same required reviewer, `contents: write`, GITHUB_TOKEN): after
               approval re-runs the plan with the version prod serves NOW (public /healthz), then moves deploy/prod
               to a deploy commit carrying the target's release record (scripts/move-deploy-ref.sh, as for promotion)
  prod host    poll.sh sees the ref move to its PREVIOUS_TAG (stored on the host) and runs rollback.sh <sha>:
               no migration step (D50), alembic_version untouched
  verify-prod  waits (12 min max) until /healthz `version` == target SHA, then readyz 200 and the e2e smoke
```

- **How it learns the previous SHA.** CI has no access to the host, so the source is the history of the ref `deploy/prod`, which CI can read: every promotion or rollback adds one deploy commit whose message is the release record (`source`, `backend`, `frontend` digests). Newest first, that is the order in which releases were approved for prod, but it is only a candidate list (#122, D67): a record is a valid target only if the run that wrote it (the `run:` line of the record) finished successfully, found through `gh api repos/<repo>/actions/runs/<id>` with `GITHUB_TOKEN` (`actions: read` on the `plan` and `rollback` jobs). Workflow, `main` branch and conclusion `success` are all checked; a run whose last job (prod serves the SHA, readyz, e2e smoke) failed, was cancelled or has not finished is skipped, so a release that failed on the host and was rolled back automatically is never a target. Records without `run:` (written before #122) count only if their source SHA is in `deploy/legacy-good-releases.txt`. If no earlier release qualifies, `plan` fails and names what it skipped. `current` is the `version` on prod's `/healthz` (what is really running; if prod is unreachable, the newest record). `target` is the next older record with a different `source`. Using `/healthz` rather than the ref head matters after a failed promotion: the ref head is then the failed release while the host (having rolled itself back) serves the one before it, and the rollback goes to the release before that. If the served version is not in the history, the plan refuses. The result is cross-checked after the move: `verify-prod` only passes when `/healthz` `version` equals the target SHA.
- **No previous release** (first deploy ever, only one release in the history, or no earlier one verified good): `plan` fails with a clear message before anything is moved. On the host the same situation is `rollback.sh` exit 3 (`PREVIOUS_TAG` empty or equal to `CURRENT_TAG`): it logs and keeps the current tag.
- **No migration.** The host runs `rollback.sh`, which never starts the `migrate` step. `poll.sh` routes a release equal to `PREVIOUS_TAG` (with its files stored under `releases/`) to `rollback.sh`; any other release goes through the normal deploy. If the host's `PREVIOUS_TAG` differs from the history-derived target (for example someone ran `rollback.sh <sha>` by hand), the target is deployed normally, including its (idempotent) migration step, and `verify-prod` still checks the served version. Check `alembic current` before and after for the demo.
- **Rolling back twice** goes forward again: after A to B to rollback-to-A, the history is A, B, A, and the next plan from A picks B (the newest older release that differs). The `plan` summary shows `from -> to` before the approval is requested; reject the `rollback` job if it is not what you want.
- **On-call.** `oncall/ops/rollback.sh` is a thin wrapper over `/opt/fitwise/bin/rollback.sh` on the host (no SSM, no AWS credential, no arguments, `sudo -n` when not root); the exit code passes through (0 healthy, 1 failed, 3 nothing to roll back to). Tests: `bash scripts/test-oncall-rollback.sh`, `bash scripts/test-rollback-plan.sh`, `bash scripts/test-rollback-host.sh` (CI job `deploy-script-tests`).
- **On-call responder service (#69).** `deploy/install-oncall.sh` (root, prod only, after `bootstrap.sh`) installs `fitwise-oncall.service`; `bootstrap.sh` puts the root helper `oncall-compose.sh` in `/opt/fitwise/bin`. Details and the owner's manual steps: `oncall/README.md`. Test: `bash scripts/test-oncall-compose.sh`.
- **Secrets.** Nothing secret is read or printed: the workflow handles SHAs, image references and statuses; the token is the built-in `GITHUB_TOKEN`, masked by Actions. Evidence for the issue: `journalctl -u fitwise-deploy | grep -Ei 'ghp_|github_pat_|ghs_|bearer'` prints nothing, and the same for the downloaded run log.
- **After merging:** re-run `deploy/bootstrap-remote.sh prod` (and dev) so the hosts get the new `poll.sh`.

GitHub settings for prod (owner): environment `production` with required reviewers and deployment branches limited to `main`, and variable `PROD_BASE_URL` (e.g. `http://<prod elastic ip>`).

GitHub settings behind dev: environment `dev` (deploys from `main` only) with variable `DEV_BASE_URL` (the dev address, used by the smoke test). The GHCR packages `fitwise-backend` and `fitwise-frontend` are public: they inherit the public repository because the images carry the `org.opencontainers.image.source` label. A ruleset limiting `deploy/*` to GitHub Actions is **not possible on a personal repository**: the API rejects the GitHub Actions app as a bypass actor ("must be part of the ruleset source or owner organization"). Until the repository moves to an organization, protection rests on the owner being the only writer (D58).

Manual step for the owner: set required reviewers on the `production` GitHub environment (Settings, Environments) and the `PROD_BASE_URL` variable; there is no ruleset for `deploy/*` (see above).

## Observability on the hosts (issue #67)

Prod runs the whole stack of #17 next to the app; dev runs only an OpenTelemetry Collector that forwards to prod (spec §12/§14, [ADR 0006](../docs/adr/0006-self-hosted-observability-on-prod.md)). Same pull-based mechanism as the app, no SSM and no AWS credential involved:

- **Switch.** `OBS_MODE=full` (prod) or `forward` (dev) in the root-only `/opt/fitwise/.env`, written by `bootstrap.sh` together with a random `GRAFANA_ADMIN_PASSWORD` (generated on the host, never in git, never printed), `GRAFANA_BIND=0.0.0.0`, `GRAFANA_PORT=3000`, `OTLP_GRPC_BIND=0.0.0.0` and `GRAFANA_ROOT_URL` on prod, and `OTLP_UPSTREAM_ENDPOINT=<prod elastic ip>:4317` on dev (`bootstrap-remote.sh dev` looks the prod address up; or pass `OTLP_UPSTREAM=host:4317`). A host with an incomplete setting runs without observability and says so in the journal; the app deploy is never affected.
- **Deploy.** `deploy.sh` stores `compose.observability.yaml` and `deploy/compose.obs-{full,forward}.yaml` with the release, so the backend gets the collector endpoint and the fluentd log driver; after the health check it runs `obs.sh`, which downloads `observability/` of the same commit to `/opt/fitwise/observability` and starts the services (`--force-recreate` only when the files changed; hash in `OBS_CONFIG_HASH`). A failure is logged (`obs: WARNING`) and ignored. `sudo /opt/fitwise/bin/obs.sh` applies it without a new release (uses `CURRENT_TAG`).
- **Reboot.** Docker is enabled at boot and every service is `restart: unless-stopped`; nothing needs the poller to come back.
- **Security groups** (created by `provision.sh`, see the table above): Grafana 3000 from the owner IP /32, OTLP gRPC 4317 from the dev Elastic IP /32; nothing else is added. The dev collector reaches prod over the public address, so the traffic is plain gRPC from one allowed IP carrying only allow-listed fields (no health data); TLS for it and for Grafana comes with HTTPS (follow-up).
- **Grafana login.** `admin` and the password in `/opt/fitwise/.env` on `fitwise-prod`. Read it once over SSM (it prints the secret, run it only in your own terminal): `aws ssm start-session --target <prod-instance-id>` then `sudo grep '^GRAFANA_ADMIN_PASSWORD=' /opt/fitwise/.env`. Grafana stores the password on first start; changing the env value later does not change the login (use `docker exec fitwise-grafana-1 grafana cli admin reset-admin-password <new>`).
- **Disk and memory on prod** (30 GB root volume, 4 GiB RAM). Retention comes from `.env` and defaults to `PROM_RETENTION_TIME=15d` with `PROM_RETENTION_SIZE=2GB`, `LOKI_RETENTION=168h`, `TEMPO_RETENTION=72h` ([numbers](../observability/README.md#retention-and-disk-use)). Budget: telemetry data about 3 GB at most (Prometheus is capped at 2 GB; Loki and Tempo about 0.2 GB each at 1 request per second, which demo traffic is far below; dev traffic adds the same order), observability images about 2 GB, application images and database about 3 GB, OS about 5 GB, container logs at most 30 MB per container (`json-file`, 10 MB x 3). Roughly 13 GB of 30 GB. Memory limits add up to 2.3 GiB for the stack (256 + 3 x 512 + 512 MiB, real use is a fraction).

Verification once the hosts are bootstrapped (owner or orchestrator; copy results to #67):

```bash
# prod host
sudo journalctl -u fitwise-deploy -o cat | grep 'obs:'                  # "obs: OK (full)"
sudo docker ps --format '{{.Names}} {{.Status}}' | grep -E 'otel|prometheus|loki|tempo|grafana'
# dev host
sudo docker ps --format '{{.Names}} {{.Status}}' | grep otel            # collector only
# from anywhere: one request on each environment, then in prod Grafana (Explore > Prometheus)
curl -s http://<dev-ip>/api/v1/healthz; curl -s http://<prod-ip>/api/v1/healthz
#   sum by (env) (http_server_duration_seconds_count)   -> series for env="dev" and env="prod"
# security groups (read-only)
aws ec2 describe-security-groups --group-names fitwise-prod --query 'SecurityGroups[0].IpPermissions[].[FromPort,IpRanges[].CidrIp]'
```

## Database backups (issue #66)

```
fitwise-backup.timer (03:00 UTC, +-10 min, Persistent) -> fitwise-backup.service -> /opt/fitwise/bin/backup.sh
  docker exec db pg_dump -Fc  ->  pg_restore --list (validation)  ->  s3://fitwise-prod-backups-<account id>/prod/<UTC timestamp>.dump
```

- **AWS side** (`deploy/provision-backups.sh`, idempotent, run once by the owner or an approved agent with AWS CLI access): bucket `fitwise-prod-backups-<account id>` in us-east-2 with all four public-access blocks on, default SSE-S3 encryption, TLS-only bucket policy and lifecycle rule `expire-prod-dumps` (prefix `prod/`, expire after 7 days). IAM role and instance profile `fitwise-ec2-prod` (SSM managed policy plus inline policy `fitwise-prod-backup-bucket`: `s3:PutObject`/`s3:GetObject` on `prod/*`, `s3:ListBucket` for prefix `prod/`, nothing else) is attached to the prod instance. The dev host keeps `fitwise-ec2-ssm` and cannot read production dumps. Cost: well under USD 0.01 per month.
- **Host side**: `deploy/bootstrap.sh` installs `backup.sh`, the service and the timer on prod only (`deploy/bootstrap-remote.sh prod`, idempotent). Credentials come from the instance role; the bucket name is derived from the account ID (override: `BACKUP_BUCKET=` in `/etc/fitwise-backup.env`).
- **Failure is visible.** Any error (container down, dump or validation failure, upload failure) exits non-zero: the unit is `failed` (`systemctl --failed`, `systemctl status fitwise-backup`) and the reason is in `journalctl -u fitwise-backup -o cat`. Nothing is uploaded on a pre-upload failure. The log holds only the key, size and statuses. `/opt/fitwise/LAST_BACKUP` records the last success (time, key, bytes). Tests: `bash scripts/test-backup.sh` (CI job `deploy-script-tests`).
- **Run one now / list:** `sudo systemctl start fitwise-backup.service; journalctl -u fitwise-backup -o cat -n 5` and `sudo aws s3 ls s3://fitwise-prod-backups-<account id>/prod/` (on the host) or the same `aws s3 ls` with owner credentials.

### Restore procedure

Restoring into a scratch database (this is also the test; do it after the first backup and after any change to the schema tooling). On `fitwise-prod` as root:

```bash
umask 077                                                              # the dump holds all user data: owner-only files
B=fitwise-prod-backups-$(aws sts get-caller-identity --query Account --output text)
KEY=$(aws s3 ls "s3://$B/prod/" | sort | tail -n1 | awk '{print $4}')      # newest dump
aws s3 cp "s3://$B/prod/$KEY" /var/tmp/restore.dump
DB=$(docker ps -qf label=com.docker.compose.service=db -f label=com.docker.compose.project=fitwise)
docker exec "$DB" sh -c 'createdb -U "$POSTGRES_USER" restore_test'
docker exec -i "$DB" sh -c 'pg_restore -U "$POSTGRES_USER" -d restore_test --no-owner --exit-on-error' < /var/tmp/restore.dump
# check: same alembic revision and plausible row counts as the live database
docker exec "$DB" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version"'
docker exec "$DB" sh -c 'psql -U "$POSTGRES_USER" -d restore_test -Atc "select version_num from alembic_version"'
# clean up
docker exec "$DB" sh -c 'dropdb -U "$POSTGRES_USER" restore_test'; shred -u /var/tmp/restore.dump
```

Restoring over production after data loss (owner decision, destructive): start with `umask 077` (the dump is downloaded to `/var/tmp`), stop the app (`docker compose -p fitwise stop backend frontend` from the current release directory under `/opt/fitwise/releases/`), restore into a new database as above, then rename: terminate connections, `ALTER DATABASE fitwise RENAME TO fitwise_old; ALTER DATABASE restore_test RENAME TO fitwise;`, start the app, check `/readyz`, and drop `fitwise_old` only after the owner confirms. The dump is the schema and data as of the backup, including `alembic_version`; the running release must be compatible with that revision (migrations are backward compatible, D50). Data written after the backup is lost: at most one day.

## Teardown (destructive, owner only)

Terminate instances, release Elastic IPs, delete security groups and the role/profile by the `Project=fitwise` tag. Never done by agents without explicit owner confirmation.

## Rollback demo on prod (owner commands, issue #14)

Prerequisite: the scripts on `fitwise-prod` include the switch (re-run `deploy/bootstrap-remote.sh prod` after the PR is merged), and prod already serves one release A (promote any dev-proven SHA first, so there is a `CURRENT_TAG` to roll back to). Pick a second dev-proven SHA B.

```bash
IID=$(aws ec2 describe-instances --region us-east-2 --filters Name=tag:Name,Values=fitwise-prod Name=instance-state-name,Values=running --query 'Reservations[0].Instances[0].InstanceId' --output text)
run() { aws ssm start-session --region us-east-2 --target "$IID" --document-name AWS-StartInteractiveCommand --parameters command="$1"; }   # or open a shell: aws ssm start-session --target "$IID"
```

On the host (as root, `sudo -i`):

1. Record the starting state: `cat /opt/fitwise/CURRENT_TAG /opt/fitwise/PREVIOUS_TAG; docker exec $(docker ps -qf name=backend) alembic current` and `curl -s localhost/api/v1/healthz` (version = A).
2. Switch on: `echo 'FITWISE_DEMO_FAIL_HEALTH=1' >> /opt/fitwise/.env`
3. In GitHub, run "Promote to production" with sha = B and approve it. Link the run in the issue.
4. Watch: `journalctl -u fitwise-deploy -f -o cat`. Expect `deploy/prod moved ... release B`, `FITWISE_DEMO_FAIL_HEALTH is set ... forced to fail`, `rolling back`, `rollback: ... A`, `FAILED B, rolled back to A`. The `smoke-prod` job fails (expected) with the "host may have rolled back" message.
5. Verify: `cat /opt/fitwise/CURRENT_TAG` is A; `curl -s localhost/api/v1/healthz` version = A; `curl -s -o /dev/null -w '%{http_code}' localhost/api/v1/readyz` is 200; `alembic current` is the same revision as in step 1 if B carried no migration, or B's revision if it carried an expand-only one (not downgraded, D50), and `readyz` is 200 either way; `cat /opt/fitwise/LAST_REF` is the deploy/prod commit of B.
6. No retry: wait for two more polls (about 5 minutes) and check `journalctl -u fitwise-deploy --since '-6min' -o cat`: no further deploy of B.
7. **Switch off (required):** `sed -i '/^FITWISE_DEMO_FAIL_HEALTH=1$/d' /opt/fitwise/.env; grep -c FITWISE_DEMO_FAIL_HEALTH /opt/fitwise/.env` must print 0.
8. Evidence for the issue: the journal excerpt (no `.env` contents appear in it), the run link, and `journalctl -u fitwise-deploy | grep -Ei 'ghp_|github_pat_|bearer'` printing nothing. Re-promote B afterwards (switch off) to show it deploys normally.

## Weekly adaptive calorie check (issue #42)

```
fitwise-adaptive-calories.timer (Mon,Tue 01:00 UTC, +-10 min, Persistent) -> fitwise-adaptive-calories.service -> /opt/fitwise/bin/adaptive-calories.sh
  docker exec <backend container> python -m app.cli.adaptive_calories
```

- **Both hosts.** `deploy/bootstrap.sh` installs the script, service and timer on dev and prod and enables the timer (`deploy/bootstrap-remote.sh dev|prod`, idempotent; run it once after this change is on `main`).
- **Why Monday and Tuesday.** The CLI decides "this week" in each athlete's time zone and evaluates an athlete once per Monday (D78), so the Tuesday run only serves zones west of UTC whose Monday had not started at the Monday run.
- **Failure is visible.** A missing backend container or a failing CLI exits non-zero: the unit is `failed` (`systemctl --failed`, `journalctl -u fitwise-adaptive-calories -o cat`). The log holds only statuses and the number of suggestions created, never weights, targets or athlete ids. Run now: `sudo systemctl start fitwise-adaptive-calories.service`. Tests: `bash scripts/test-adaptive-calories.sh` (CI job `deploy-script-tests`).
