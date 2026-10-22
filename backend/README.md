# FitWise backend

FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic on Python 3.12, managed with [uv](https://docs.astral.sh/uv/).
The API contract is [`../openapi.yaml`](../openapi.yaml); every path is served under `/api/v1`.

## Layout

```
app/
  main.py          create_app() factory, mounts routers under /api/v1
  config.py        Settings from environment variables (documented in .env.example)
  errors.py        shared RFC 9457 problem+json handling (ProblemError, 400/422 mapping, 500)
  telemetry/       OpenTelemetry traces + metrics, allow-listed JSON logs, user_hash (spec §14)
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

Run from `backend/` (the Makefile wraps these once it exists):

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

## Telemetry (spec §14, §6.5)

* **Logs** are JSON lines on stdout. Use `app.telemetry.get_logger(__name__)` with a constant
  message and keyword fields: `log.info("set logged", outcome="created")`. Only the fields in
  `app/telemetry/privacy.py` (`LOG_EVENT_FIELDS`) are kept; `%s` arguments are never interpolated
  and tracebacks are never written (`error_type` only). Every line has `timestamp`, `level`,
  `message`, `trace_id`, `span_id`, `env`, `service`, `version` and, inside a request, `route`
  (template) and `user_hash`. Adding a field to the allow-list is a privacy review.
* **Users** appear only as `user_hash` (HMAC-SHA256 of the id keyed by `USER_HASH_SALT`). The auth
  dependency calls `app.telemetry.bind_user(user.id)`; never log or tag the raw id.
* **Access log**: `RequestTelemetryMiddleware` logs `route`, `method`, `status`, `duration_ms` per
  request (no path, no query string). Run uvicorn with `--no-access-log`; the app also disables
  the `uvicorn.access` logger.
* **Metrics**: `request.app.state.telemetry.metrics` has typed methods for the §14 counters
  (`set_logged()`, `suggestion_generated(kind, rule)`, ...). `http_server_duration` (seconds;
  labels `route`, `method`, `status`) is recorded for every request.
* **Traces**: FastAPI and SQLAlchemy are instrumented automatically; wrap outgoing httpx clients
  with `instrument_http_client(client, telemetry)` and engine calls with
  `telemetry.engine_span("progression")`. Exported spans pass `SanitizingSpanExporter`:
  allow-listed attributes only (custom ones under `fitwise.*`), no query strings, headers,
  bodies, exception messages or status descriptions. Health probes are not traced.
* **Export**: OTLP/HTTP to `OTEL_EXPORTER_OTLP_ENDPOINT`; unset means no export and no network.
  Tests build the app with in-memory exporters (`captured` fixture in `tests/conftest.py`).
