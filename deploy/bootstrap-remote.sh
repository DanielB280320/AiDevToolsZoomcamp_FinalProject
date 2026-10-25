#!/usr/bin/env bash
# Run deploy/bootstrap.sh on a host over SSM (no SSH).
#   [DEPLOY_REF=<branch|sha>] deploy/bootstrap-remote.sh <dev|prod>
# DEPLOY_REF: where bootstrap fetches the deploy scripts from (default main).
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_REGION:-us-east-2}" AWS_PAGER=""
env="${1:?usage: bootstrap-remote.sh dev|prod}"
here="$(cd "$(dirname "$0")" && pwd)"
iid="$(aws ec2 describe-instances --filters Name=tag:Name,Values="fitwise-$env" Name=tag:Project,Values=fitwise Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].InstanceId' --output text)"
for _ in $(seq 40); do
  [ "$(aws ssm describe-instance-information --filters Key=InstanceIds,Values="$iid" --query 'length(InstanceInformationList)' --output text)" = 1 ] && break
  sleep 10
done
# Dev forwards telemetry to the prod collector (#67): its Elastic IP, port 4317 (OTLP gRPC).
upstream="${OTLP_UPSTREAM:-}"
if [ "$env" = dev ] && [ -z "$upstream" ]; then
  pip="$(aws ec2 describe-addresses --filters Name=tag:Name,Values=fitwise-prod Name=tag:Project,Values=fitwise \
    --query 'Addresses[0].PublicIp' --output text | sed 's/^None$//')"
  [ -z "$pip" ] || upstream="$pip:4317"
fi
b64="$(base64 -w0 "$here/bootstrap.sh")"
cid="$(aws ssm send-command --instance-ids "$iid" --document-name AWS-RunShellScript \
  --parameters "commands=[\"echo $b64 | base64 -d > /tmp/bootstrap.sh\",\"ENV_NAME=$env DEPLOY_REF=${DEPLOY_REF:-main} OTLP_UPSTREAM=$upstream bash /tmp/bootstrap.sh\"]" \
  --query Command.CommandId --output text)"
echo "ssm command id: $cid"
aws ssm wait command-executed --command-id "$cid" --instance-id "$iid" || true
aws ssm get-command-invocation --command-id "$cid" --instance-id "$iid" --query '[Status,StandardOutputContent,StandardErrorContent]' --output text
