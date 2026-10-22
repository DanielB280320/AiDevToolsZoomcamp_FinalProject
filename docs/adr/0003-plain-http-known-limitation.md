# ADR 0003: Serve the MVP over plain HTTP as a documented limitation

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-21 |
| **Deciders** | Owner |
| **Spec** | [spec §6.4 Security](../spec.md#64-security), [§12 Deployment](../spec.md#12-deployment-aws), [§17 Roadmap](../spec.md#17-roadmap-post-mvp) item 1, [§19](../spec.md#19-decisions-log) D4 |

## Context

Each environment is reached through its EC2 public DNS name ([ADR 0002](0002-ec2-docker-compose-deployment.md)). There is no registered domain, and a trusted certificate realistically requires a hostname we control, so getting HTTPS needs a domain (or a wildcard DNS service such as sslip.io) plus a TLS terminator, which adds setup and moving parts that do not count towards the MVP criteria. FitWise handles health-related personal data ([§6.5](../spec.md#65-privacy-health-data)), so serving it without TLS is a real risk.

## Decision

We will serve the MVP over **plain HTTP on port 80** on each instance's public DNS name and treat this as a **known, documented limitation**:

- The README warns reviewers to use **test accounts and fake data only**.
- The session cookie stays `HttpOnly` and `SameSite=Lax`; its **`Secure` flag is configurable** (off for HTTP, on once HTTPS exists).
- HTTPS (domain or sslip.io + Caddy/Let's Encrypt, `Secure` cookies) is the **first roadmap item**.

## Alternatives considered

| Option | Why not (for the MVP) |
|---|---|
| Buy a domain + Caddy/Let's Encrypt | Best option and planned next; costs time and money not needed for the MVP criteria. |
| sslip.io + Caddy | No domain purchase, but still adds a TLS proxy and certificate renewal to the walking skeleton. |
| Self-signed certificate | Browser warnings and no real trust; reviewers would have to click through security errors. |
| AWS ALB + ACM | ACM also needs a domain; adds cost and infrastructure. |

## Consequences

- **Positive:** the walking skeleton can be deployed and reviewed without DNS or certificate work.
- **Negative / accepted risks:** passwords, JWT cookies and health data travel unencrypted and can be read or modified by anyone on the network path. Mitigated by test-data-only use, argon2id password hashes at rest, short (24 h) sessions and no real users before HTTPS.
- **Follow-ups:** the cookie `Secure` flag is an environment variable from the first auth issue; the README limitation notice is part of M6; adding HTTPS will supersede this ADR.
