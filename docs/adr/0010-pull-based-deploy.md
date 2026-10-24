# ADR 0010: Deploy by pull: hosts poll the approved tag, CI holds no AWS credentials

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-24 |
| **Deciders** | Owner, DevOps |
| **Spec** | [spec §12 Deployment](../spec.md#12-deployment-aws), [§13 CI/CD](../spec.md#13-cicd-github-actions), [§19](../spec.md#19-decisions-log) D52, D57; issues #12, #13, #14 |

(The coordinator referred to this as "ADR 0009"; that number is already taken by [ADR 0009](0009-separate-migration-step.md), so this is the next free number.)

## Context

[ADR 0002](0002-ec2-docker-compose-deployment.md) and spec §13 assumed GitHub Actions would reach the hosts to deploy. With port 22 closed, that left SSM `SendCommand`, which needs AWS credentials in GitHub. Both ways of getting them failed in this account (issue #12):

- GitHub OIDC: the AWS Organization service control policy (SCP) explicitly denies `iam:CreateOpenIDConnectProvider`.
- A least-privilege IAM user per environment was created, but the same SCP denies every action for those users (`AllowedByOrganizations=false` in QA's policy simulation), so their keys could not deploy. They were deleted.

Opening port 22 to GitHub's address ranges would be worse than either: very large, changing ranges and a long-lived SSH key.

## Decision

Deployment is **pull-based**:

1. CI builds images once per commit and pushes them to GHCR tagged with the git SHA.
2. CI **records the approved tag** for an environment by moving a git ref in this repository (`deploy/dev`, `deploy/prod`) to the approved commit. For dev this happens after a green merge to `main`. For prod it happens only in the "Promote to production" workflow job that runs in the `production` GitHub environment, so the manual approval gate still applies.
3. A **systemd timer on each host** polls its ref through the public GitHub API (conditional requests with `ETag`, every minute or two, well inside the unauthenticated rate limit). When the SHA changes it pulls the images, runs the migration step, starts the new tag, health-checks `/readyz`, writes `CURRENT_TAG`/`PREVIOUS_TAG`, and **rolls back to `PREVIOUS_TAG` by itself** if the health check fails ([D50](../spec.md#19-decisions-log): rollback skips migrations).
4. The poller remembers the last tag it attempted or that was rolled back, so it does not redeploy a failed tag in a loop and does not undo an on-call `rollback.sh`; it acts again only when the approved ref moves.
5. Hosts open **no inbound ports** for deployment and GitHub holds **no AWS keys**. The only credential on the host is none at all, provided the repository and GHCR packages are public (see below).

The poller (`deploy/deploy.sh`, systemd unit and timer) is built in #13 and #14. This ADR only fixes the design.

## Alternatives considered

| Option | Why not |
|---|---|
| GitHub OIDC to AWS, then SSM | Denied by the organization SCP. |
| IAM user keys in GitHub environment secrets | Created and tested in #12; the SCP denies all their actions, so they cannot deploy. |
| SSH from GitHub Actions | Needs port 22 open to GitHub's ranges and a long-lived key in secrets. |
| Self-hosted GitHub runner on each host | A permanent runner holding repository access on the production host, with its own patching and takeover risk. |
| Manual deploy by the owner | Fails the "merge deploys to dev automatically" requirement. |

## Consequences

- **Positive:** no AWS credentials in GitHub, nothing to rotate, no inbound deploy path, works under the SCP; rollback also works with no CI available.
- **Negative / accepted risks:**
  - Deploys lag the approval by up to one polling interval.
  - Whoever can move the `deploy/*` refs controls what runs, so ref creation and updates must be restricted to the workflow (repository ruleset / protected tags), and `deploy/prod` only from the `production` environment job.
  - The workflow cannot see the host's result directly; it smoke-tests the public URL after the poll interval instead (spec §13).
  - The poller has no private token, so the repository and the GHCR packages must be public. If either becomes private, hosts need a read-only token in a root-only file (a new decision).
  - If GitHub is unreachable, hosts keep running the current tag.
- **Follow-ups:** #13 (compose deploy, `deploy.sh`) and #14 (CD workflow, poller timer) implement this; the workflows' deploy steps no longer use AWS.
