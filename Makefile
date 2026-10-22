# FitWise single-command entry points (spec §10, §11; CLAUDE.md "Commands").
#
# Prerequisites: Docker with Compose v2 (every target), plus uv and Node.js 24 on the host for
# test/lint/e2e. `make up` needs only Docker. Run `make help` for the list of targets.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

COMPOSE ?= docker compose
# Image tag: `make build TAG=<sha>` or TAG in the environment / .env (compose default: local).
ifdef TAG
export TAG
endif

BACKEND := backend
FRONTEND := frontend
E2E := e2e
NPM_STAMP := $(FRONTEND)/node_modules/.package-lock.json

# --------------------------------------------------------------------------------------------
##@ Stack

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make <target>\n"} \
	  /^##@/ {printf "\n%s\n", substr($$0, 5)} \
	  /^[a-zA-Z0-9_-]+:.*##/ {printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@printf "\nApp URL after 'make up': http://localhost:<HTTP_PORT>  (HTTP_PORT in .env, default 8088)\n"
	@printf "Images: <IMAGE_PREFIX>-backend:<TAG>, <IMAGE_PREFIX>-frontend:<TAG>  (TAG=%s)\n" "$${TAG:-$$(sed -n 's/^TAG=//p' .env 2>/dev/null)}"

.env:
	@cp .env.example .env
	@echo "Created .env from .env.example (local defaults; edit if needed)."

.PHONY: up
up: .env ## Build and start db, backend, frontend; returns when all are healthy
	$(COMPOSE) up --build --wait
	@echo "FitWise is up: http://localhost:$$($(COMPOSE) port frontend 8080 | sed 's/.*://')"

.PHONY: build
build: .env ## Build the backend and frontend images (tag: TAG, default local)
	$(COMPOSE) build

.PHONY: down
down: ## Stop the stack (and the test database); the database volume is kept
	$(COMPOSE) --profile test down --remove-orphans

.PHONY: clean
clean: ## Stop the stack and DELETE its database volume (all local data)
	$(COMPOSE) --profile test down --volumes --remove-orphans

.PHONY: ps
ps: ## Show service status and health
	$(COMPOSE) ps

.PHONY: logs
logs: ## Follow the logs of all services
	$(COMPOSE) logs -f

.PHONY: up-obs
up-obs: ## Start the observability stack (not yet: #17)
	@echo "make up-obs: the observability stack is not implemented yet (#17)." >&2
	@exit 1

.PHONY: check-log-privacy
check-log-privacy: ## Smoke: no query/ids/IP/referrer/token in logs, valid JSON; backend up AND down
	COMPOSE="$(COMPOSE)" scripts/check-log-privacy.sh

.PHONY: seed-demo
seed-demo: ## Load the demo athlete + coach (not yet: #51)
	@echo "make seed-demo: demo data is not implemented yet (#51)." >&2
	@exit 1

# --------------------------------------------------------------------------------------------
##@ Quality

.PHONY: test
test: ## Backend unit + integration (Postgres container) and frontend tests
	@rc=0; \
	$(MAKE) test-backend || rc=1; \
	$(MAKE) test-frontend || rc=1; \
	if [ $$rc -ne 0 ]; then echo "make test: FAILED (see output above)" >&2; fi; \
	exit $$rc

# TEST_DATABASE_URL already set (e.g. a CI service container) -> use it as is.
# Otherwise start the throwaway `db-test` container and point the tests at it.
.PHONY: test-backend
test-backend: check-uv ## Backend pytest (unit + integration)
ifdef TEST_DATABASE_URL
	cd $(BACKEND) && uv run --locked pytest
else
	@$(MAKE) test-db-up
	port=$$($(COMPOSE) --profile test port db-test 5432 | sed 's/.*://'); \
	cd $(BACKEND) && \
	TEST_DATABASE_URL="postgresql+psycopg://fitwise_test:fitwise_test@127.0.0.1:$$port/postgres" \
	uv run --locked pytest
endif

.PHONY: test-db-up
test-db-up: .env ## Start the throwaway test PostgreSQL (tmpfs, 127.0.0.1:TEST_DB_PORT)
	$(COMPOSE) --profile test up --wait db-test

.PHONY: test-db-down
test-db-down: ## Remove the test PostgreSQL
	$(COMPOSE) --profile test rm --stop --force db-test

.PHONY: test-frontend
test-frontend: $(NPM_STAMP) ## Frontend Vitest + RTL
	cd $(FRONTEND) && npm test

.PHONY: lint
lint: ## ruff (lint + format check), mypy, eslint, tsc
	@rc=0; \
	$(MAKE) lint-backend || rc=1; \
	$(MAKE) lint-frontend || rc=1; \
	if [ $$rc -ne 0 ]; then echo "make lint: FAILED (see output above)" >&2; fi; \
	exit $$rc

.PHONY: lint-backend
lint-backend: check-uv ## ruff check, ruff format --check, mypy
	cd $(BACKEND) && uv run --locked ruff check
	cd $(BACKEND) && uv run --locked ruff format --check
	cd $(BACKEND) && uv run --locked mypy

.PHONY: lint-frontend
lint-frontend: $(NPM_STAMP) ## eslint, tsc --noEmit
	cd $(FRONTEND) && npm run lint
	cd $(FRONTEND) && npm run typecheck

# --------------------------------------------------------------------------------------------
##@ End-to-end

# Runs the Playwright project in e2e/ against the running stack (`make up` first).
# The project reads its base URL from BASE_URL (default: the published frontend port).
.PHONY: e2e
e2e: check-node ## Playwright journeys in e2e/ against the running stack
	@if [ ! -f $(E2E)/package.json ]; then \
	  echo "make e2e: no Playwright project in $(E2E)/ yet (it arrives in #65)." >&2; exit 1; fi
	@base_url="$${BASE_URL:-}"; \
	if [ -z "$$base_url" ]; then \
	  hostport=$$($(COMPOSE) port frontend 8080 2>/dev/null || true); \
	  if [ -z "$$hostport" ]; then echo "make e2e: the stack is not running; run 'make up' first." >&2; exit 1; fi; \
	  base_url="http://localhost:$${hostport##*:}"; \
	fi; \
	echo "e2e against $$base_url"; \
	cd $(E2E) && npm ci --no-audit --no-fund && npx playwright install chromium && \
	BASE_URL="$$base_url" npx playwright test

# --------------------------------------------------------------------------------------------
# Toolchain checks and dependency install

.PHONY: check-uv
check-uv:
	@command -v uv >/dev/null || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }

.PHONY: check-node
check-node:
	@command -v node >/dev/null || { echo "Node.js 24 is required (frontend/.nvmrc)." >&2; exit 1; }
	@node -e 'process.exit(Number(process.versions.node.split(".")[0]) >= 24 ? 0 : 1)' || \
	  { echo "Node.js 24 is required (frontend/.nvmrc); found $$(node --version)." >&2; exit 1; }
	@npm --version | awk -F. '{ exit !($$1 > 9 || ($$1 == 9 && $$2 >= 5)) }' || \
	  { echo "npm >= 9.5 is required (Node 24 ships npm 11); found $$(npm --version)." >&2; exit 1; }

# Reinstall frontend dependencies whenever the lockfile changes.
$(NPM_STAMP): $(FRONTEND)/package-lock.json | check-node
	cd $(FRONTEND) && npm ci --no-audit --no-fund
	@touch $@
