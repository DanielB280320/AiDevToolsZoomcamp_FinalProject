# syntax=docker/dockerfile:1
# FitWise backend image (spec §11). Built once per commit and tagged with TAG (CD, #13).
# Configuration comes only from environment variables (see the root .env.example).

ARG PYTHON_VERSION=3.12
ARG UV_VERSION=0.12.9

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---- build: resolve the locked runtime dependencies into /app/.venv ----
FROM python:${PYTHON_VERSION}-slim AS build
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

# ---- runtime: no uv, no build tools, non-root ----
FROM python:${PYTHON_VERSION}-slim AS runtime
RUN groupadd --system --gid 10001 fitwise \
 && useradd --system --uid 10001 --gid fitwise --no-create-home --shell /usr/sbin/nologin fitwise
WORKDIR /app
COPY --from=build --chown=root:root /app /app
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER 10001:10001
EXPOSE 8000

# Migrate first (backward-compatible migrations only, spec §13), then serve.
# --no-access-log: uvicorn's access log records full query strings (e.g. food search `q`),
# which must never reach logs (CLAUDE.md rule 6). The allow-listed access logger comes in #16.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --no-access-log --proxy-headers --forwarded-allow-ips='*'"]
