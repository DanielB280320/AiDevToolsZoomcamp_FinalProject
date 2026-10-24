# FitWise

Mobile-first web app that is a single source of truth for training and nutrition. See
[CLAUDE.md](CLAUDE.md) and [docs/spec.md](docs/spec.md). The full project README (features,
deploy, demo, limitations) arrives with #53; this page covers running it locally.

## Run locally

Prerequisites: Docker with Compose v2. For `make test`, `make lint` and `make e2e` also
[uv](https://docs.astral.sh/uv/) and Node.js 24 with npm >= 9.5 (`frontend/.nvmrc`).

```bash
cp .env.example .env   # optional: `make up` does it if .env is missing
make up                # db + backend + frontend, returns when all are healthy
open http://localhost:8088
make down              # stop; the database volume is kept
make clean             # stop and DELETE the database volume
```

The app (SPA and `/api`) is published on `127.0.0.1:${HTTP_PORT}`, default **8088**. Every
setting is an environment variable documented in [.env.example](.env.example). `make help` lists
all targets.

| Command | What it does |
|---|---|
| `make up` | `docker compose up --build --wait`: db, the one-shot `migrate` step (migrations + seed), then backend and frontend |
| `make test` | Backend unit + integration tests (throwaway Postgres container on `127.0.0.1:${TEST_DB_PORT}`, default 15432) and frontend tests. Uses `TEST_DATABASE_URL` instead if it is already set |
| `make lint` | ruff, ruff format --check, mypy, eslint, tsc, generated API client up to date (`npm run check:api`), `openapi.yaml` lint (Redocly) |
| `make e2e` | Playwright project in `e2e/` against the running stack (`BASE_URL`, #65) |
| `make check-log-privacy` | Smoke check (stack running) that no query string, user UUID or numeric id in a path, client IP, referrer or token reaches container logs, and that nginx access lines are valid JSON; with the backend up and down |
| `make contract-smoke` | Contract smoke (stack running): schemathesis checks the responses of every operation the backend serves against `openapi.yaml`, with a throwaway signed-in athlete |
| `make scan` | Security scans: `scan-secrets` (gitleaks, full history; run from a regular clone), `scan-deps` (pip-audit, npm audit), `scan-images` (Trivy, HIGH/CRITICAL with a fix) |
| `make up-obs` | The app plus the observability stack (OTel Collector, Prometheus, Loki, Tempo, Grafana at `http://localhost:${GRAFANA_PORT}`, default 3030); the backend exports to it. `make check-obs` verifies metric/exemplar/trace/log correlation and the privacy gate; `make down-obs` / `make clean-obs` stop it. See [observability/README.md](observability/README.md) |
| `make rollback-compat` | Rollback guard: builds the previous release's backend image (`PREV_REF`, default the merge-base with `origin/main`) and this tree's, migrates with the new one, rolls back without the migration step and checks `readyz` (own Compose project, nothing published) |
| `make build TAG=<sha>` | Build `<IMAGE_PREFIX>-backend:<TAG>` and `<IMAGE_PREFIX>-frontend:<TAG>` |

### CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every pull request and every push
to `main`, using the make targets above: backend lint and tests (Postgres 16 service), frontend
lint/type-check/client drift/tests, OpenAPI lint, secret and dependency scans, both image builds
with a Trivy scan (never pushed), then the stack is started for `make contract-smoke` and
`make check-log-privacy`. When a change touches migrations, the backend image or `compose*.yaml`,
the job **Rollback compatibility** runs `make rollback-compat` against the PR's base. `main` requires the aggregate check **CI passed**. Intentional fake
credentials in tests need a trailing `# gitleaks:allow` comment.

### Migrations, deploys and rollbacks

Migrations and the F4.1 seed run only in the one-shot `migrate` service, from the same image as
the backend (`python -m app.migrate`). The backend container only starts the app; it never
migrates or seeds, so a restart never touches the schema and an older image can always start
on a newer schema (spec §11, §13; D50, ADR 0009).

| Situation | Command |
|---|---|
| Local | `make up` (the backend waits for `migrate` to exit 0) |
| Forward deploy | `TAG=<sha> docker compose run --rm migrate && TAG=<sha> docker compose up -d --no-deps --wait backend frontend` |
| Rollback | `TAG=<PREVIOUS_TAG> docker compose up -d --no-deps --wait backend frontend` (no migration step, no down-migration) |
| Restart | `docker compose restart backend` (no migration step) |

The forward deploy runs the step on its own first: if a migration fails, it exits non-zero and
the running backend keeps serving the old tag. A plain `docker compose up` would also run the
step first, but it replaces the old backend container before the step finishes.

### Several stacks side by side

Each checkout uses `COMPOSE_PROJECT_NAME=fitwise`, port 8088 and test port 15432 by default,
so two checkouts (for example parallel agent worktrees under `../fitwise-wt/<issue>`) would share
one Compose project and its database volume, and collide on the ports. Give each one its own
values in its `.env`:

```bash
# ../fitwise-wt/21/.env
COMPOSE_PROJECT_NAME=fitwise-21
HTTP_PORT=8121
TEST_DB_PORT=15421
# only for `make up-obs`:
GRAFANA_PORT=3121
OTLP_HTTP_PORT=14321
FLUENT_FORWARD_PORT=24321
```

or, for a single command, in the environment (it takes precedence over `.env`):

```bash
COMPOSE_PROJECT_NAME=fitwise-21 HTTP_PORT=8121 TEST_DB_PORT=15421 make up test
```

On Windows/WSL with Docker Desktop, pick ports below 49152: Windows reserves the dynamic range
above it and Docker Desktop may fail to publish there.

## Feature flags

Runtime flags live in the `feature_flag` table (allow-list and defaults in
`backend/app/config.py` `FEATURE_FLAGS`: `progression_engine` v1|v2, `off_search_enabled`
true|false, `fault_injection_latency_ms` 0..10000). Change one on the running stack with:

```bash
oncall/ops/flag.sh <key> <value>                 # actor oncall-agent; FLAG_ACTOR=owner to override
docker compose exec -T backend python -m app.cli.flags list
```

Unknown keys or invalid values exit non-zero and change nothing. Running backends pick the change
up within 5 s (`FLAG_CACHE_TTL_SECONDS`), without a restart.
