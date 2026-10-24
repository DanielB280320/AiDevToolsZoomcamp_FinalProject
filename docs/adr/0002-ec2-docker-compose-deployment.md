# ADR 0002: Deploy with Docker Compose on two EC2 instances

| | |
|---|---|
| **Status** | Accepted (deploy mechanism amended by [ADR 0010](0010-pull-based-deploy.md)) |
| **Date** | 2026-10-21 |
| **Deciders** | Owner |
| **Spec** | [spec §11](../spec.md#11-containerization-and-local-run), [§12 Deployment](../spec.md#12-deployment-aws), [§13 CI/CD](../spec.md#13-cicd-github-actions), [§19](../spec.md#19-decisions-log) D2, D3 |

## Context

The course requires a cloud deployment with separate dev and prod environments, CI/CD with manual promotion and rollback. FitWise is a small app (one backend, one SPA, one database) run by one owner on a tight budget. The same containers must run locally (`make up`), in CI and in the cloud so "works on my machine" problems do not reach prod.

## Decision

We will:

- Run each environment on its **own EC2 instance** (`fitwise-dev`, `fitwise-prod`) with Docker and **Docker Compose**; Postgres 16 runs as a **container** with a volume on the instance.
- Build images **once per commit** in GitHub Actions and push them to **GHCR** tagged with the git SHA. Dev auto-deploys every merge to `main`; prod gets a SHA already running on dev through the "Promote to production" workflow, which requires approval in the `production` GitHub Environment.
- Keep `CURRENT_TAG` and `PREVIOUS_TAG` on each host. A failed health check after a deploy redeploys `PREVIOUS_TAG` automatically on the host; "Rollback production" (moves the `deploy/prod` ref back) and the on-call `rollback.sh` do the same (as amended by ADR 0010).
- **Amended by [ADR 0010](0010-pull-based-deploy.md):** CI does not push deploys to the hosts. It records the approved tag and a systemd timer on each host pulls and deploys it, and rolls back by itself.
- Back up prod with a nightly `pg_dump` to S3 (7-day retention). Bootstrap is scripted and documented in `deploy/README.md`.

## Alternatives considered

| Option | Why not |
|---|---|
| ECS/Fargate + RDS | Managed and more robust, but more AWS surface, more cost and more setup than the MVP needs. |
| Kubernetes (EKS or k3s) | Far more operational complexity for three containers. |
| PaaS (Render, Fly.io, Railway) | Easy, but the course asks for a cloud deployment we control, and the on-call agent needs host access for allow-listed scripts. |
| One instance with both environments | Cheaper, but a dev incident could take prod down and the separation of environments would be weak. |

## Consequences

- **Positive:** identical Compose setup everywhere; deploy is `docker compose pull && up` with a tag; rollback is a tag swap with no rebuild; low, predictable cost.
- **Negative / accepted risks:** each environment is a single host (no high availability); Postgres in a container means we own backups and upgrades; infrastructure is scripted, not declarative (IaC is roadmap item 7, [§17](../spec.md#17-roadmap-post-mvp)).
- **Follow-ups:** migrations must be backward compatible (expand → migrate → contract) so a rollback never needs a down-migration ([§13](../spec.md#13-cicd-github-actions), CLAUDE.md rule 8). Security groups as in [§12](../spec.md#12-deployment-aws). Access is over plain HTTP, see [ADR 0003](0003-plain-http-known-limitation.md).
