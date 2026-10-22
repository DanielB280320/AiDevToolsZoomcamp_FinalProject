# ADR 0004: Keep calculation engines pure, deterministic and explainable

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-21 |
| **Deciders** | Owner |
| **Spec** | [spec §1 Problem](../spec.md#1-problem), [§2.1 G3](../spec.md#21-goals-mvp), [F3](../spec.md#f3-calculation-engine-targets--must), [F5](../spec.md#f5-training-plan-generator--must), [F7](../spec.md#f7-meal-plan-generator--must), [F11](../spec.md#f11-progression-engine--must), [F13](../spec.md#f13-daily-energy-balance--must), [F14](../spec.md#f14-body-tracking-and-adaptive-calories--must), [§10 Testing](../spec.md#10-testing-strategy), [§20](../spec.md#20-assumptions-and-open-questions) A2 |

## Context

FitWise acts as a free, rule-based coach: every target, plan and suggestion must show the rule and the numbers that produced it (G3), and there is no AI/LLM in the product ([§1](../spec.md#1-problem), [§2.2](../spec.md#22-non-goals-mvp)). These rules are the core of the product and the riskiest code: a wrong progression or calorie number is a user-facing bug. The spec requires table-driven and property-based tests with ≥ 90 % line coverage for the engines, reproducible generators (F5.5, F7.4), and engine versions switchable by feature flag (F11.5) for the on-call scenario S2.

## Decision

We will put all calculation logic in `backend/app/engines/` as **pure functions**:

- Inputs are plain values (dataclasses / Pydantic models); outputs are results plus an **`explanation` or `reason` string** (and the rule used where relevant).
- Engines have **no database, HTTP, clock, random-without-seed, feature-flag or environment access**. "Today", the user's time zone, the body weight on a date and the seed (`user_id + ISO week` for meal plans) are passed in by the service layer.
- All formula constants (lifestyle factors, goal adjustments, protein per kg, calorie floors, MET values, increments, adaptive thresholds) live in **one config module**.
- Engine versions (for example `progression_engine=v1|v2`) are separate functions; the **service** reads the flag and picks one, falling back to `v1` for unknown values.
- Services store engine outputs together with their inputs and explanation (`Targets.inputs`/`explanation`, `Suggestion.rule`/`reason`/`payload`).

## Alternatives considered

| Option | Why not |
|---|---|
| Logic inside services/endpoints with ORM access | Harder to test (needs a database), easy to leak I/O and non-determinism into the rules. |
| LLM-generated suggestions | Not deterministic, not free to run, hard to test and explain; explicitly a non-goal. |
| Rules engine / DSL | Extra abstraction for a small, stable rule set; plain functions are easier for agents and reviewers. |

## Consequences

- **Positive:** engines are tested with fast table-driven and Hypothesis tests and no fixtures; outputs are reproducible from stored inputs; explanations come for free; a faulty engine version can be switched off at runtime with a flag.
- **Negative / accepted risks:** services must gather every input up front, which can mean more queries per request (watch the 500 ms p95 SLOs, [§6.6](../spec.md#66-performance-and-reliability-targets-slos)); explanation strings must be kept in sync with the formulas.
- **Follow-ups:** CLAUDE.md rule 3 enforces this; QA checks that engine modules import nothing from the database, HTTP or clock layers. Custom spans `engine.targets`, `engine.progression`, `engine.meal_plan` are created by the caller, so engines stay free of telemetry ([§14](../spec.md#14-observability)).
