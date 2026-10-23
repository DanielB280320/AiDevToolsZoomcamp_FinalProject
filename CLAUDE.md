# FitWise

FitWise is a mobile-first web app that is a single source of truth for training and nutrition. From a user's body metrics and goal it calculates calorie/macro targets and generates a weekly training plan and meal plan; every day the user logs sets and meals, sees planned vs. actual performance and estimated calories eaten vs. burned, and accepts or rejects rule-based suggestions for what to do next. Users can edit everything in custom mode, and a linked human coach can review the same data, edit the plan and leave notes.

It is the final project of the AI Dev Tools Zoomcamp 2026 and is built by a team of Claude Code agents.

## Read first

| Doc | What it holds | Status |
|---|---|---|
| [docs/spec.md](docs/spec.md) | **Source of truth.** Requirements F1–F18 with acceptance criteria, formulas, data model, API outline, testing, deployment, CI/CD, observability, on-call, delivery order, decisions log | ✅ |
| [docs/process.md](docs/process.md) | Workflow: issue lifecycle, status labels ↔ board, branches/worktrees, PRs, QA, releases, incidents | ✅ |
| [docs/team.md](docs/team.md) | Agent team: orchestrator, PM, Engineer, QA, DevOps/SRE — responsibilities and hand-offs. Definitions in `.claude/agents/` | ✅ |
| [docs/architecture.md](docs/architecture.md) | Components, request flow for the key journey, environments, key design decisions | ✅ |
| [docs/adr/](docs/adr/README.md) | Architecture decision records (template `0000-template.md` + ADRs 0001–0007) | ✅ |
| `docs/runbooks/` | Incident runbooks used by the on-call agent | planned (M1) |
| [openapi.yaml](openapi.yaml) | API contract (written before implementation) | ✅ |

When a requirement is unclear, check `docs/spec.md` first; if it doesn't answer the question, ask instead of guessing, and record the outcome in the spec (decisions log §19 or an ADR).

## Task tracker

All work is tracked in **GitHub Issues** on this repo and on the public [FitWise Backlog board](https://github.com/users/DanielB280320/projects/1) (columns Backlog → Ready → In progress → In QA → Done mirror the `status:*` labels), grouped by milestone (`M0`…`M6`, see spec §16.2) and labelled by area, role and priority. Every issue has acceptance criteria; an issue is done only when all of them are verified.

- Pick work with `gh issue list --milestone "<milestone>" --label "status:ready"`.
- Change status only with `scripts/issue-status.sh <issue> <status>` (updates label and board together).
- Comment on the issue when you start, when you hand off, and with QA results.
- Every PR references its issue with `Closes #N`.

## Stack

| Layer | Tech |
|---|---|
| Frontend | React + TypeScript + Vite, TanStack Query, Recharts, react-i18next, Tailwind |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, `uv` |
| Database | PostgreSQL 16 |
| Tests | pytest, Hypothesis, Vitest + RTL, Playwright |
| Infra | Docker Compose, AWS EC2 (dev + prod), GHCR, GitHub Actions |
| Observability | OpenTelemetry → Prometheus, Loki, Tempo, Grafana |

## Commands

These are the target commands; they become valid as the M1 issues land.

```bash
make up          # full stack locally (docker compose up --build --wait)
make test        # backend unit + integration, frontend tests
make e2e         # Playwright journeys against the running stack
make lint        # ruff, mypy, eslint, tsc
make seed-demo   # demo athlete with 8 weeks of history + a coach
make up-obs      # observability stack
```

## Repository layout

```
backend/         FastAPI app; backend/app/engines/ holds the pure calculation engines
frontend/        React SPA
e2e/             Playwright tests
observability/   collector, prometheus, loki, tempo, grafana provisioning, alert rules
oncall/          alert responder, prompts, allow-listed ops scripts
deploy/          EC2 bootstrap, compose overrides, deploy/rollback scripts
.claude/         agent definitions and project skills
docs/            spec, process, team, architecture, adr/, runbooks/
```

## Agent models

Engineer and DevOps agents implement already-groomed issues on **Sonnet with medium effort**, set in their `.claude/agents/*.md` frontmatter; don't override it when starting them. See [docs/team.md](docs/team.md#models-and-effort).

## Rules for every agent

1. **Spec first.** Implement what the issue and `docs/spec.md` say. Behaviour changes need a spec update in the same PR.
2. **Contract first.** API changes start in `openapi.yaml`; the frontend client is generated from it.
3. **Engines are pure.** Code in `backend/app/engines/` takes plain inputs and returns results plus an `explanation`/`reason` string. No database, HTTP or clock access inside engines. Constants live in one config module.
4. **Tests with every change.** Engines: table-driven + property tests. Endpoints: integration tests against real Postgres, including authorization (owner vs. linked coach vs. stranger). No real network calls in tests (use the Open Food Facts fake).
5. **Store metric, display user units.** kg, cm, kcal, grams in the database; convert only at the edges. Dates in UTC; "today" uses the user's time zone.
6. **Health data never reaches telemetry.** No emails, names, passwords, tokens, body metrics, food names or notes in logs, metrics or traces. Identify users only by `user_hash`. Logging goes through the allow-listed structured logger.
7. **Snapshots, not references, for history.** Set logs store the targets they were performed against; plan edits never change the past.
8. **Backward-compatible migrations** (expand → migrate → contract) so a release can always be rolled back.
9. **No secrets in git.** Configuration comes from environment variables; `.env.example` documents them.
10. **Never push to `main` directly.** Work on a branch (one per issue, in its own git worktree when running in parallel) and open a PR.

## Definition of done

- All acceptance criteria in the issue are met and checked off.
- `make lint` and `make test` pass locally and in CI.
- New behaviour is covered by tests; docs/spec updated if behaviour changed.
- QA agent has verified the acceptance criteria independently and commented on the issue.
- PR merged with `Closes #N`.
