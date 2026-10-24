#!/usr/bin/env bash
# Run deploy/bootstrap.sh on a host over SSM (no SSH).
#   deploy/bootstrap-remote.sh <dev|prod>
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
b64="$(base64 -w0 "$here/bootstrap.sh")"
cid="$(aws ssm send-command --instance-ids "$iid" --document-name AWS-RunShellScript \
  --parameters "commands=[\"echo $b64 | base64 -d > /tmp/bootstrap.sh\",\"ENV_NAME=$env bash /tmp/bootstrap.sh\"]" \
  --query Command.CommandId --output text)"
aws ssm wait command-executed --command-id "$cid" --instance-id "$iid" || true
aws ssm get-command-invocation --command-id "$cid" --instance-id "$iid" --query '[Status,StandardOutputContent,StandardErrorContent]' --output text
