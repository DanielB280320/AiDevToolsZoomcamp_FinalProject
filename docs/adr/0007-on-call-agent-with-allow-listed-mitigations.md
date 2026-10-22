# ADR 0007: Limit the on-call agent to allow-listed runtime mitigations

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-21 |
| **Deciders** | Owner |
| **Spec** | [spec §15.2 On-call responder](../spec.md#152-on-call-responder), [§15.3 Demo scenarios](../spec.md#153-demo-scenarios-documented-in-docsrunbooks), [§19](../spec.md#19-decisions-log) D33, [process.md §10](../process.md#10-incidents) |

## Context

The course asks for an on-call agent that reacts to user-impact alerts. An autonomous agent with shell access on the prod host could make an incident worse (data loss, leaked secrets, unreviewed code in prod). The response still has to be fast enough to restore the key journey, and every lasting change must go through the normal review process.

## Decision

We will run a small **Python webhook receiver** (systemd on the prod host) that receives Grafana alerts at `/alerts`, deduplicates by fingerprint, saves context to `incidents/<id>/`, and launches **headless Claude Code** (`claude -p`) with a runbook prompt and a **strict tool allow-list**:

- read-only Prometheus/Loki/Tempo queries and `docker compose ps/logs`;
- exactly one runtime mitigation per incident: `oncall/ops/flag.sh <key> <value>` (allow-listed keys), `oncall/ops/rollback.sh` (redeploy `PREVIOUS_TAG`) or `oncall/ops/restart.sh <backend|frontend>`;
- `gh issue create` for the incident report, and `git` + `gh pr create` on a separate clone for the fix (branch push only).

It has no database writes, no secrets beyond its own env file, no arbitrary shell, a 20-minute timeout and an API key with a spend limit.

## Alternatives considered

| Option | Why not |
|---|---|
| Unrestricted agent with shell access | Fast, but one wrong command can cause data loss or a security incident. |
| Agent that only opens an issue | Safe, but does not restore service; users stay impacted until a human acts. |
| Agent that hot-fixes code on the host | Unreviewed changes in prod; breaks the "nothing reaches prod outside the pipeline" rule. |

## Consequences

- **Positive:** mitigations are reversible and already tested by CI/CD (rollback) or designed for it (flags); the audit trail lives in GitHub; root-cause fixes get QA and human review.
- **Negative / accepted risks:** some incidents (for example database problems) cannot be mitigated by the agent and still need a human; the allow-list must be maintained with the runbooks.
- **Follow-ups:** the mitigations depend on the feature-flag table, `PREVIOUS_TAG` on the host and backward-compatible migrations ([ADR 0002](0002-ec2-docker-compose-deployment.md)); engine versions behind flags depend on [ADR 0004](0004-pure-calculation-engines.md). Runbooks for S1–S3 live in `docs/runbooks/`.
