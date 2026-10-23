# ADR 0009: Run migrations and seed as a separate one-shot step, never on backend start

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-23 |
| **Deciders** | Owner, PM, QA (found the defect) |
| **Spec** | [spec §11](../spec.md#11-containerization-and-local-run), [§13 CI/CD](../spec.md#13-cicd-github-actions), [F4.1](../spec.md#f4-exercise-catalog--must), [§19](../spec.md#19-decisions-log) D50; issue #82 |

## Context

The backend image's command ran `alembic upgrade head` and then uvicorn. A rollback redeploys `PREVIOUS_TAG` ([ADR 0002](0002-ec2-docker-compose-deployment.md)). If the current release shipped a migration, the database is at a revision the previous image doesn't know. `alembic upgrade head` then exits with `Can't locate revision`, and the previous backend never starts. That breaks the automatic rollback after a failed prod smoke test, the "Rollback production" workflow, the on-call `rollback.sh` ([ADR 0007](0007-on-call-agent-with-allow-listed-mitigations.md)) and demo scenario S1. QA found this on #15 / PR #77 and it is tracked in #82.

The schema was never the problem. Migrations are expand → migrate → contract, and `GET /readyz` already accepts a database at or ahead of the release's head (§13). The problem is that starting the app also tried to migrate.

## Decision

We will:

- Run `alembic upgrade head` followed by the idempotent F4.1 seed as a **separate one-shot migration step**, using the image being deployed, **before** the backend starts.
- Make the **backend container only start the app**. It never migrates or seeds on start.
- Run the migration step on **local `make up`** and on **forward deploys** (dev auto-deploy, prod promotion). The backend starts only after the step finishes successfully. If the step fails, the deploy or `make up` fails and the backend never starts.
- **Skip the migration step on rollback.** Redeploying `PREVIOUS_TAG` (automatic rollback, "Rollback production", on-call `rollback.sh`) starts the previous backend against the newer schema as it is, with no down-migration.

How the step is wired (a compose service, a `deploy/deploy.sh` step or both) is an implementation choice for #82. It must keep the behaviour above.

## Alternatives considered

| Option | Why not |
|---|---|
| Keep migrating on start, but skip the upgrade when the database's revision is unknown to the image | Keeps two jobs in the backend's start path. Every replica or restart races to migrate. The "unknown revision means newer" check could also hide a real problem, like a wrong database or a broken history. |
| Seed on every backend start (kept separate from migrations) | The seed writes catalog rows whose shape follows the schema. Running it from an older image on a newer schema is the same class of risk as migrating, and seeding once per deploy is enough because it is idempotent. |
| Down-migrate on rollback | Rejected by §13 and CLAUDE.md rule 8. It can lose data and makes the on-call rollback risky. |

## Consequences

- **Positive:** rollback is a pure image-tag swap that can't fail on schema version. Backend restarts (on-call `restart` mitigation, `restart: unless-stopped`) never touch the schema. A failed migration is reported as a failed step, with its own exit code and logs, not as a backend crash loop.
- **Negative / accepted risks:** a deploy has one more step to orchestrate. Anyone who starts the backend container directly against an empty database gets `migrations: pending` (503) from `/readyz` until the step runs. That is the intended signal.
- **Follow-ups:** #82 implements the step and a CI regression test (previous image on the current schema). #13 (`deploy/deploy.sh`) runs the step before starting the backend on forward deploys. #14 and #69 (rollback paths) don't run it. The rollback runbook for S1 (`docs/runbooks/`) describes the skipped step.
