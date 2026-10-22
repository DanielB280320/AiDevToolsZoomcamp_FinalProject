# ADR 0005: Make openapi.yaml the API source of truth

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-21 |
| **Deciders** | Owner |
| **Spec** | [spec §7.1 Tech stack](../spec.md#71-tech-stack) (API contract), [§9 API outline](../spec.md#9-api-outline), [§10 Testing](../spec.md#10-testing-strategy) (contract tests), [§13 CI/CD](../spec.md#13-cicd-github-actions) (OpenAPI validation) |

## Context

Backend and frontend are written by different agents, often in parallel worktrees. Without a shared contract they drift: field names, units and error shapes get guessed on each side. Charts need pre-aggregated endpoints (F15.1), and coaches reuse the athlete-scoped endpoints ([§9](../spec.md#9-api-outline)), so the API surface is large and must stay consistent.

## Decision

We will write **`openapi.yaml` (OpenAPI 3.1) first** for every API change, before backend or frontend code:

- All paths live under `/api/v1`.
- The **frontend client is generated** from `openapi.yaml` and regenerated in the same PR as any contract change.
- CI **validates** the spec, and a schemathesis smoke test checks that backend responses match it.
- Two issues that both edit `openapi.yaml` run sequentially, never in parallel ([process.md §4](../process.md#4-branches-worktrees-and-commits)).

## Alternatives considered

| Option | Why not |
|---|---|
| Code-first (export the spec from FastAPI) | Less duplication, but the contract appears only after the backend is written, so the frontend agent waits or guesses. |
| Hand-written frontend types | Drift between client and server is caught only at runtime. |
| GraphQL | Not needed for this app; REST + OpenAPI fits the course tooling and the observability route labels. |

## Consequences

- **Positive:** frontend and backend can be built in parallel against one reviewed contract; type errors surface at compile time; QA can verify responses against the schema.
- **Negative / accepted risks:** the contract and FastAPI's own models can diverge if not tested; mitigated by the contract test in CI.
- **Follow-ups:** CLAUDE.md rule 2; the Engineer workflow orders work as contract → tests → code → regenerate client → docs.
