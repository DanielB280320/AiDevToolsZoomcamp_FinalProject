#!/usr/bin/env bash
# Switch a running host between plain HTTP and "behind CloudFront" (#220, ADR 0012) over SSM,
# without a full bootstrap. Runs locally with the owner's AWS credentials.
#
#   deploy/host-https.sh <dev|prod> on     SESSION_COOKIE_SECURE=true, trust the CloudFront edge's
#                                          X-Forwarded-For, X-Forwarded-Proto https
#   deploy/host-https.sh <dev|prod> off    rollback: cookie not Secure, nothing trusted, scheme as seen
#
# It edits the root-only /opt/fitwise/.env (values are never printed) and recreates the backend of
# the CURRENT_TAG release so the cookie setting applies at once; the frontend picks the NGINX_*
# values up at the next deploy (or `compose_release ... up -d frontend`). `on` only after
# deploy/cloudfront.sh verify passes; `off` only together with `cloudfront.sh unlock`.
# The same settings are applied on a new host by deploy/bootstrap.sh with BEHIND_CLOUDFRONT=1.
set -euo pipefail
export AWS_DEFAULT_REGION="${AWS_REGION:-us-east-2}" AWS_PAGER=""
env="${1:-}"; mode="${2:-}"
case "$env:$mode" in dev:on|dev:off|prod:on|prod:off) ;; *) echo "usage: host-https.sh dev|prod on|off" >&2; exit 2;; esac
if [ "$mode" = on ]; then secure=true; trusted=0.0.0.0/0; proto=https; else secure=false; trusted=127.0.0.1; proto='$scheme'; fi

iid="$(aws ec2 describe-instances --filters "Name=tag:Name,Values=fitwise-$env" Name=tag:Project,Values=fitwise \
  Name=instance-state-name,Values=running --query 'Reservations[0].Instances[0].InstanceId' --output text)"
script="$(cat <<EOS
set -eu
cd /opt/fitwise
for kv in 'SESSION_COOKIE_SECURE=$secure' 'NGINX_TRUSTED_PROXIES=$trusted' 'NGINX_FORWARDED_PROTO=$proto'; do
  k=\${kv%%=*}
  grep -v "^\$k=" .env > .env.new || true
  printf '%s\n' "\$kv" >> .env.new
  cat .env.new > .env; rm -f .env.new
done
chown root:root .env; chmod 600 .env
. /opt/fitwise/bin/lib.sh
compose_release "\$(cat CURRENT_TAG)" up -d backend 2>&1 | tail -3
for _ in \$(seq 30); do curl -fsS -m 5 -o /dev/null localhost/api/v1/readyz 2>/dev/null && { echo "readyz ok"; exit 0; }; sleep 2; done
echo "readyz did not recover" >&2; exit 1
EOS
)"
b64="$(printf '%s' "$script" | base64 -w0)"
cid="$(aws ssm send-command --instance-ids "$iid" --document-name AWS-RunShellScript \
  --parameters "commands=[\"echo $b64 | base64 -d | bash\"]" --query Command.CommandId --output text)"
aws ssm wait command-executed --command-id "$cid" --instance-id "$iid" || true
aws ssm get-command-invocation --command-id "$cid" --instance-id "$iid" \
  --query '[Status,StandardOutputContent,StandardErrorContent]' --output text
