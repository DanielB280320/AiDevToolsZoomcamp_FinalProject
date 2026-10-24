# Deploy: AWS hosts (issue #12)

Scripted provisioning for the two FitWise hosts (spec section 12). IaC is a roadmap item, so these are idempotent AWS CLI scripts.

| | dev | prod |
|---|---|---|
| Name | `fitwise-dev` | `fitwise-prod` |
| Region | us-east-2 | us-east-2 |
| Instance type | t3.small (2 vCPU, 2 GiB) | c7i-flex.large (2 vCPU, 4 GiB), runs Prometheus/Loki/Tempo/Grafana + responder (ADR 0006) |
| OS | Amazon Linux 2023 (x86_64) | same |
| Disk | 30 GiB encrypted gp3 | 30 GiB encrypted gp3 |
| Public address | Elastic IP | Elastic IP |

Prod is a c7i-flex.large rather than the originally planned t3.medium because the AWS account is on the Free plan, which rejects t3.medium (`not eligible for Free Tier`) but allows c7i-flex.large.

All resources are tagged `Project=fitwise`, `Env=dev|prod`.

## Expected monthly cost (us-east-2, on-demand list prices, approximate)

| Item | dev | prod |
|---|---|---|
| EC2 | ~$15 (t3.small, $0.0208/h) | ~$62 (c7i-flex.large, ~$0.085/h) |
| EBS 30 GiB gp3 | ~$2.4 | ~$2.4 |
| Public IPv4 / Elastic IP ($0.005/h) | ~$3.6 | ~$3.6 |
| Total | ~$21 | ~$68 |

About **$89/month** for both hosts (owner approved "$57 or more" on 2026-10-24; this is the real figure, the owner should confirm). Free-plan credits may offset part of it. IAM, security groups and SSM are free. Data transfer and the S3 backup bucket (#66) are extra. Re-check the EC2 prices on the AWS pricing page before relying on them.

## Access method: SSM, not SSH

Port 22 is closed on both hosts and there is no key pair. Reasons: no long-lived SSH keys to store in GitHub or lose, no need to open 22 to GitHub's very large and changing IP ranges, and SSM gives audited sessions. Instances carry the `fitwise-ec2-ssm` instance profile (managed policy `AmazonSSMManagedInstanceCore`, nothing else).

- Owner shell: `aws ssm start-session --target <instance-id> --region us-east-2` (needs the Session Manager plugin), or run commands with `aws ssm send-command`.
- GitHub Actions deploys: the workflow authenticates with the environment's deploy key and calls `ssm send-command` (AWS-RunShellScript) on its own instance. See "GitHub Environments" below.

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
2. `deploy/provision.sh` creates (or finds) the IAM instance profile, security groups, instances, Elastic IPs, deploy IAM users and GitHub environment secrets, and prints IDs and addresses. Overrides: `AWS_REGION`, `OWNER_CIDR`, `DEV_TYPE`, `PROD_TYPE`, `GH_REPO`, `GITHUB_AUTH=none` to skip the deploy users.
3. `deploy/bootstrap-remote.sh dev|prod` ships `deploy/bootstrap.sh` to the host over SSM and runs it. It installs Docker and the Compose plugin, creates the `deploy` user (in the `docker` group), creates `/opt/fitwise` with empty `CURRENT_TAG` and `PREVIOUS_TAG`, a root-only (`0600`) `.env`, and runs an `nginx:alpine` placeholder named `fitwise-placeholder` on port 80 until the first real deploy (#13) replaces it. Running it again changes nothing.
4. Check: `curl -i http://<elastic-ip>/` returns 200.

### GitHub Environments and deploy credentials

`provision.sh` creates the GitHub environments `dev` and `production` and one IAM user per environment (`fitwise-deploy-dev`, `fitwise-deploy-prod`). The org service control policy denies GitHub OIDC (`iam:CreateOpenIDConnectProvider`), so a long-lived access key is used instead, kept as narrowly scoped as possible:

- Each user may only call `ssm:SendCommand` on the document `AWS-RunShellScript` and on its own environment's instance (condition `Project=fitwise`, `Env=<env>`), and `ssm:GetCommandInvocation`. Nothing else; add actions only if a deploy step strictly needs them.
- The key is piped directly into the environment secrets `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`; it is never printed or written to disk. `AWS_REGION` and `DEPLOY_INSTANCE_ID` are stored next to it.
- Manual step for the owner: in GitHub, set required reviewers on the `production` environment (Settings, Environments).

Re-running `provision.sh` never creates a second key for a user that already has one.

#### Rotate the deploy key

For `<env>` in `dev|prod` (GitHub environment `dev` or `production`), with owner confirmation:

1. `aws iam list-access-keys --user-name fitwise-deploy-<env>` and note the old key id.
2. Create the new key and store it without printing it: source the `create_and_store_key` function from `provision.sh` or run its two `gh secret set --env` pipes (the key is piped straight from `aws iam create-access-key --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text`). A user can hold two keys at once, so this does not break deploys.
3. Run a deploy (or the smoke workflow) to confirm the new key works.
4. `aws iam delete-access-key --user-name fitwise-deploy-<env> --access-key-id <old key id>` (destructive, owner confirms).

## Teardown (destructive, owner only)

Terminate instances, release Elastic IPs, delete security groups, the IAM users and the role/profile by the `Project=fitwise` tag. Never done by agents without explicit owner confirmation.
