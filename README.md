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
| `make up` | `docker compose up --build --wait`; the backend runs `alembic upgrade head` before serving |
| `make test` | Backend unit + integration tests (throwaway Postgres container on `127.0.0.1:${TEST_DB_PORT}`, default 15432) and frontend tests. Uses `TEST_DATABASE_URL` instead if it is already set |
| `make lint` | ruff, ruff format --check, mypy, eslint, tsc |
| `make e2e` | Playwright project in `e2e/` against the running stack (`BASE_URL`, #65) |
| `make check-log-privacy` | Smoke check (stack running) that no query string, user UUID or numeric id in a path, client IP, referrer or token reaches container logs, and that nginx access lines are valid JSON; with the backend up and down |
| `make build TAG=<sha>` | Build `<IMAGE_PREFIX>-backend:<TAG>` and `<IMAGE_PREFIX>-frontend:<TAG>` |

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
```

or, for a single command, in the environment (it takes precedence over `.env`):

```bash
COMPOSE_PROJECT_NAME=fitwise-21 HTTP_PORT=8121 TEST_DB_PORT=15421 make up test
```

On Windows/WSL with Docker Desktop, pick ports below 49152: Windows reserves the dynamic range
above it and Docker Desktop may fail to publish there.
