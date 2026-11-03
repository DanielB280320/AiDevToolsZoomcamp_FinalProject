# ADR 0012: Serve dev and prod over HTTPS through one CloudFront distribution per environment

| | |
|---|---|
| **Status** | Accepted (dev live; prod pending owner approval) |
| **Date** | 2026-11-03 |
| **Deciders** | Owner, DevOps/SRE, PM |
| **Spec** | [spec §6.4](../spec.md#64-security), [§12](../spec.md#12-deployment-aws), [§13](../spec.md#13-cicd-github-actions), D94. Supersedes [ADR 0003](0003-plain-http-known-limitation.md) |

## Context

[ADR 0003](0003-plain-http-known-limitation.md) accepted plain HTTP because a trusted certificate needs a hostname we control and a TLS terminator. FitWise holds health data, so passwords and session cookies should not cross the network in clear text. There is still no domain. The plan in the first version of #220 (Caddy with a Let's Encrypt IP certificate, sslip.io as fallback) added a service and certificate renewal to every host. Constraints: AWS Organization policies deny IAM users and GitHub OIDC (ADR 0010), so CI has no AWS credentials; the instance roles have no CloudFront permission; the owner's login role `AccountFullAccessRole` is allowed to create distributions and edit security groups in us-east-2 (feasibility check on #220).

## Decision

We will put **one CloudFront distribution per environment in front of each EC2 host** and use its default `*.cloudfront.net` name and AWS-managed certificate (no domain, no ACM, no Caddy).

- **Origin:** the instance's EC2 public DNS name over HTTP on port 80 (CloudFront requires a DNS name, not an IP). Viewer protocol policy `redirect-to-https`; TLS 1.2 minimum.
- **Cache behaviours:** `/api/*` uses the managed `CachingDisabled` cache policy and `AllViewerExceptHostHeader` origin request policy (cookies, query string and headers reach the backend; all HTTP methods); `/assets/*` (hashed Vite output, `Cache-Control: max-age=31536000`) uses `CachingOptimized`; everything else, including `index.html` and SPA routes, is `CachingDisabled` so a release is visible at once.
- **Cost controls:** `PriceClass_100`, no WAF, no logging bucket, no Lambda@Edge, no other add-ons. Expected cost USD 0 at this traffic (CloudFront's always-free tier is 1 TB out and 10 million requests per month).
- **Origin lock-down:** the security group admits port 80 only from the AWS-managed CloudFront origin-facing prefix list `pl-b6a144df`, not `0.0.0.0/0`, so the host cannot be reached directly. Ports 3000 (Grafana) and 4317 (OTLP) are unchanged; Grafana stays private on HTTP and is out of scope.
- **App changes:** `SESSION_COOKIE_SECURE=true` on the hosts. nginx trusts `X-Forwarded-For` only from `NGINX_TRUSTED_PROXIES` (`0.0.0.0/0` on the hosts, which is safe because of the security group; `127.0.0.1` locally), takes the LAST entry (the viewer address CloudFront appended; earlier entries are client-supplied), and forwards exactly that one address and `X-Forwarded-Proto: https` (`NGINX_FORWARDED_PROTO`) to the backend. The backend has no CORS (the SPA and API share an origin) and its sign-in rate limit is keyed by e-mail hash, not by IP (D49), so nothing else depends on the client address; the handling keeps any future IP-based limit correct. Tested by `scripts/test-nginx-proxy.sh`.
- **Provisioning:** `deploy/cloudfront.sh` (idempotent, runs locally with the owner's credentials; CI never runs it) creates or updates the distribution and moves the security group; `deploy/host-https.sh` switches the host env over SSM; `deploy/bootstrap.sh` applies the same env on a new host with `BEHIND_CLOUDFRONT=1`.
- **Order per environment:** create the distribution, wait for `Deployed`, add the prefix-list rule, verify through CloudFront, revoke `0.0.0.0/0`, switch the host env, then update `DEV_BASE_URL` / `PROD_BASE_URL`.
- **Rollback:** `deploy/cloudfront.sh unlock <env>` re-opens port 80, `deploy/host-https.sh <env> off` restores plain HTTP settings, the base URL variable is set back to the IP address.

## Alternatives considered

| Option | Why not |
|---|---|
| Caddy + Let's Encrypt IP certificate on each host | Extra service, port 443 and renewal on every host; short-lived IP certificates. Replaced by the owner on 2026-11-03. |
| sslip.io + Caddy | Same moving parts plus a third-party DNS dependency. |
| ALB + ACM | Needs a domain for ACM; about USD 16-20 per month per environment. |
| Registered domain + ACM + CloudFront | The cleanest long-term; costs a domain. Can replace the default name later without app changes. |
| Self-signed certificate | Browser warnings. |

## Consequences

- **Positive:** TLS with a trusted certificate and automatic renewal, no new service on the hosts, direct access to the origin is closed, USD 0.
- **Negative / accepted risks:** the viewer-to-CloudFront leg is encrypted but CloudFront-to-origin is plain HTTP inside AWS's network (the origin accepts only CloudFront addresses; any CloudFront customer's distribution can reach it, which the prefix list does not prevent, but the origin serves nothing a stranger lacks the session for). The `*.cloudfront.net` names are not memorable and change if a distribution is recreated, so the variables and README must be updated then. Grafana (3000) and dev-to-prod OTLP (4317) stay unencrypted; they carry no health data. `/api/*` is never cached, so CloudFront adds a hop of latency but no staleness risk. A `lock-add` needs 55 rule slots of the 60-rule security group quota (the prefix list's weight), leaving 5 for other rules.
- **Follow-ups:** prod distribution after owner approval; optional custom domain; a CloudFront alarm is not needed (CloudFront has no host to monitor beyond the existing probes).
