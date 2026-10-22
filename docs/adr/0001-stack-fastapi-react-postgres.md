# ADR 0001: Use FastAPI, React and PostgreSQL as the stack

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-21 |
| **Deciders** | Owner |
| **Spec** | [spec §7.1 Tech stack](../spec.md#71-tech-stack), [§19 Decisions log](../spec.md#19-decisions-log) D1, D5, D7, D35 |

## Context

FitWise is a mobile-first web app ([D7](../spec.md#19-decisions-log)) with a lot of deterministic calculation (targets, plan generation, progression, energy balance), relational data with strict ownership rules (athletes, coaches, plans, logs), and charts. It must be production-ready for the course: tests, containers, CI/CD and observability. It is built entirely by Claude Code agents ([D35](../spec.md#19-decisions-log)), so the stack must be mainstream, well documented, strongly typed and quick to test.

## Decision

We will build FitWise with:

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, managed with `uv`.
- **Frontend:** React + TypeScript + Vite, React Router, TanStack Query, Recharts, react-i18next, Tailwind CSS. A responsive SPA, no native apps.
- **Database:** PostgreSQL 16.
- **Tests:** pytest + Hypothesis, Vitest + React Testing Library, Playwright.
- **Contract:** OpenAPI 3.1, see [ADR 0005](0005-contract-first-openapi.md).

## Alternatives considered

| Option | Why not |
|---|---|
| Node/TypeScript backend (Express, NestJS) | One language end to end, but Python has the better fit for formula-heavy engines and Hypothesis property tests; FastAPI generates OpenAPI from Pydantic models. |
| Django + server-rendered templates | Heavier ORM/admin than needed; a SPA with TanStack Query gives the 2-tap logging UX ([§6.1](../spec.md#61-usability)) more easily. |
| SQLite | Simpler locally, but concurrent writes, JSON columns and parity with production favour Postgres. |
| Native mobile app | Out of scope ([§2.2](../spec.md#22-non-goals-mvp)); responsive web reaches phones and desktop (coach dashboard) with one codebase. |

## Consequences

- **Positive:** typed models on both sides (Pydantic, TypeScript) and a generated client; engines are plain Python and easy to unit- and property-test; Postgres is the same in tests, CI and prod (integration tests run against real Postgres, [§10](../spec.md#10-testing-strategy)).
- **Negative / accepted risks:** two languages and two toolchains (uv and npm) in CI; Python request throughput is lower than some alternatives, which is acceptable for the SLOs in [§6.6](../spec.md#66-performance-and-reliability-targets-slos).
- **Follow-ups:** `make lint` runs ruff, mypy, eslint and tsc; `make test` runs both test suites ([CLAUDE.md](../../CLAUDE.md#commands)). UI strings go through react-i18next from day one so Spanish can be added later ([D5](../spec.md#19-decisions-log)).
