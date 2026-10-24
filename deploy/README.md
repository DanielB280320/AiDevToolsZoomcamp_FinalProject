# Deploy: AWS hosts (issue #12)

Scripted provisioning for the two FitWise hosts (spec section 12). IaC is a roadmap item, so these are idempotent AWS CLI scripts.

| | dev | prod |
|---|---|---|
| Name | `fitwise-dev` | `fitwise-prod` |
| Region | us-east-2 | us-east-2 |
| Instance type | t3.small (2 vCPU, 2 GiB) | t3.medium (2 vCPU, 4 GiB), runs Prometheus/Loki/Tempo/Grafana + responder (ADR 0006) |
| OS | Amazon Linux 2023 (x86_64) | same |
| Disk | 30 GiB encrypted gp3 | 30 GiB encrypted gp3 |
| Public address | Elastic IP | Elastic IP |

All resources are tagged `Project=fitwise`, `Env=dev|prod`.

## Expected monthly cost (us-east-2, on-demand, approximate)

| Item | dev | prod |
|---|---|---|
| EC2 | ~$15 (t3.small) | ~$30 (t3.medium) |
| EBS 30 GiB gp3 | ~$2.4 | ~$2.4 |
| Elastic IP (public IPv4, $0.005/h) | ~$3.6 | ~$3.6 |
| Total | ~$21 | ~$36 |

About $57/month for the two hosts at on-demand list prices. The owner approved roughly $45/month; the Elastic IP/public IPv4 charges and EBS account for the difference, so check this against the budget. IAM, security groups and SSM are free. Data transfer and the S3 backup bucket (#66) are extra.

## Access method: SSM, not SSH

Port 22 is closed on both hosts and there is no key pair. Reasons: no long-lived SSH keys to store in GitHub or lose, no need to open 22 to GitHub's very large and changing IP ranges, and SSM gives audited sessions. Instances carry the `fitwise-ec2-ssm` instance profile (managed policy `AmazonSSMManagedInstanceCore`, nothing else).

- Owner shell: `aws ssm start-session --target <instance-id> --region us-east-2` (needs the Session Manager plugin), or run commands with `aws ssm send-command`.
- GitHub Actions deploys: workflow assumes `fitwise-deploy-dev` / `fitwise-deploy-prod` and calls `ssm send-command` (AWS-RunShellScript) on instances tagged with its own `Env`. See "GitHub Environments" below.

## Security groups (`fitwise-dev`, `fitwise-prod`)

| Port | Source | Applies to |
|---|---|---|
| 80 | 0.0.0.0/0 | both |
| 22 | closed (SSM) | both |
| 3000 (Grafana) | owner IP /32 (auto-detected, override with `OWNER_CIDR`) | prod |
| 4317 (OTLP gRPC) | dev Elastic IP /32 | prod |

Rules are added only when missing; if the owner IP changes, update the rule by hand (`aws ec2 revoke/authorize-security-group-ingress`) or re-run with the new `OWNER_CIDR` after revoking the old rule.

## Steps

1. Credentials for the AWS CLI with permission to manage EC2/IAM/SSM (the owner or an approved agent).
2. `deploy/provision.sh` creates (or finds) the IAM instance profile, security groups, instances, Elastic IPs and deploy roles, and prints IDs and addresses. Overrides: `AWS_REGION`, `OWNER_CIDR`, `DEV_TYPE`, `PROD_TYPE`, `GH_REPO`, `GITHUB_AUTH=none` to skip the GitHub roles.
3. `deploy/bootstrap-remote.sh dev|prod` ships `deploy/bootstrap.sh` to the host over SSM and runs it. It installs Docker and the Compose plugin, creates the `deploy` user (in the `docker` group), creates `/opt/fitwise` with empty `CURRENT_TAG` and `PREVIOUS_TAG`, a root-only (`0600`) `.env`, and runs an `nginx:alpine` placeholder named `fitwise-placeholder` on port 80 until the first real deploy (#13) replaces it. Running it again changes nothing.
4. Check: `curl -i http://<elastic-ip>/` returns 200.

### GitHub Environments (manual step)

Create environments `dev` and `production` (production with required reviewers) and store, as environment secrets, the deploy credentials; nothing secret goes in git. The intended design is OIDC role assumption (`fitwise-deploy-<env>`, trust limited to this repo and that environment, permission limited to `ssm:SendCommand` on same-`Env` instances), which needs no stored AWS keys; only the role ARN is stored.

Known blocker: the AWS Organization's service control policy denies `iam:CreateOpenIDConnectProvider` in this account, so the OIDC provider and roles could not be created. Options for the owner are listed in the PR.

## Teardown (destructive, owner only)

Terminate instances, release Elastic IPs, delete security groups and the IAM role/profile by the `Project=fitwise` tag. Never done by agents without explicit owner confirmation.
