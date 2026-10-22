# FitWise backend

FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic on Python 3.12, managed with [uv](https://docs.astral.sh/uv/).
The API contract is [`../openapi.yaml`](../openapi.yaml); every path is served under `/api/v1`.

## Layout

```
app/
  main.py          create_app() factory, mounts routers under /api/v1
  config.py        Settings from environment variables (documented in .env.example)
  errors.py        shared RFC 9457 problem+json handling (ProblemError, 400/422 mapping, 500)
  db.py            engine, session factory, get_session dependency
  migrations.py    Alembic script location and known revisions
  routers/         HTTP layer (Pydantic schemas in, service calls out)
  services/        auth, authorization, transactions, clock, time zone, flags
  engines/         pure calculation engines; constants.py holds every tunable number
  models/          SQLAlchemy models (Base with naming convention)
  schemas/         Pydantic schemas mirroring openapi.yaml (RequestModel forbids unknown fields)
alembic/           migrations (expand -> migrate -> contract, never break the previous release)
tests/unit/        no database needed
tests/integration/ real PostgreSQL via TEST_DATABASE_URL (one fresh database per test)
```

## Commands

From the repository root, `make up` runs the whole stack in Docker (migrations run on container
start), `make lint` and `make test` wrap the commands below (`make test` starts a throwaway
Postgres container and sets `TEST_DATABASE_URL`); see `make help`. Run from `backend/`:

```bash
uv sync                                              # install deps into .venv
cp .env.example .env                                 # then edit DATABASE_URL
uv run alembic upgrade head                          # migrate DATABASE_URL to head
uv run uvicorn app.main:create_app --factory --reload
uv run alembic revision --autogenerate -m "add x"    # new migration

uv run ruff check && uv run ruff format --check && uv run mypy
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/postgres uv run pytest
uv run pytest tests/unit                             # without a database
```

`TEST_DATABASE_URL` must point at a throwaway PostgreSQL 16 server whose user may `CREATE DATABASE`;
integration tests fail (they do not skip) when it is missing.

## Conventions for new endpoints

* Request bodies subclass `app.schemas.base.RequestModel` (unknown properties -> 422).
* Expected failures raise `app.errors.ProblemError(status, code, detail)` with a code listed in
  the `Problem` schema; never return ad-hoc error bodies.
* Invalid query/path parameters and unparseable JSON become 400 `bad_request` automatically;
  body validation becomes 422 `validation_error` (spec D40).
* `tests/unit/test_contract.py` fails if the app serves an operation that is not in `openapi.yaml`
  or uses a different `operationId`.
