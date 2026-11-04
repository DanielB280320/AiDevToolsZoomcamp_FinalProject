#!/usr/bin/env bash
# HTTPS for FitWise (#220, ADR 0012): one CloudFront distribution per environment in front of the
# EC2 host, on the default *.cloudfront.net name and AWS-managed certificate. Idempotent: every
# subcommand can be re-run. Runs LOCALLY with the owner's AWS credentials (the instance roles have
# no CloudFront permission and CI holds no AWS credentials, ADR 0010). Needs aws CLI v2 and jq.
#
#   deploy/cloudfront.sh ensure <dev|prod>        create or update the distribution, print id + URL
#   deploy/cloudfront.sh status <dev|prod>        show id, domain, deployment status, SG rules
#   deploy/cloudfront.sh lock-add <dev|prod>      allow port 80 from the CloudFront prefix list
#   deploy/cloudfront.sh lock-revoke <dev|prod>   then remove port 80 from 0.0.0.0/0
#   deploy/cloudfront.sh unlock <dev|prod>        rollback of the lock: re-open 80 to 0.0.0.0/0
#   deploy/cloudfront.sh verify <dev|prod>        curl checks through CloudFront (no -k)
#
# Order for an environment: ensure -> (wait for Deployed) -> lock-add -> verify -> lock-revoke.
# Ports other than 80 (prod Grafana 3000, OTLP 4317) are never touched.
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"        # EC2 and security groups; CloudFront itself is global
export AWS_DEFAULT_REGION="$REGION" AWS_PAGER=""
# AWS-managed origin-facing prefix list (com.amazonaws.global.cloudfront.origin-facing).
PREFIX_LIST="${CLOUDFRONT_PREFIX_LIST:-pl-b6a144df}"
# AWS-managed policies (fixed ids): CachingDisabled, CachingOptimized, AllViewerExceptHostHeader.
CACHING_DISABLED=4135ea2d-6df8-44a3-9df3-4b5a84be39ad
CACHING_OPTIMIZED=658327ea-f89d-4fab-a63d-7e88639e58f6
ALL_VIEWER_EXCEPT_HOST=b689b0a8-53d0-40ab-baf2-68738e2966ac

usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }
[ $# -eq 2 ] || usage
cmd="$1"; env="$2"
case "$env" in dev|prod) ;; *) usage;; esac
name="fitwise-$env"
comment="$name (#220)"
command -v jq >/dev/null || { echo "jq is required" >&2; exit 1; }

instance_field() {  # instance_field <jq-path-in-instance>
  aws ec2 describe-instances --filters "Name=tag:Name,Values=$name" Name=tag:Project,Values=fitwise \
    Name=instance-state-name,Values=pending,running --query 'Reservations[0].Instances[0]' --output json |
    jq -r "$1 // empty"
}
origin_dns="$(instance_field .PublicDnsName)"
sg="$(instance_field '.SecurityGroups[0].GroupId')"
[ -n "$origin_dns" ] && [ -n "$sg" ] || { echo "no running instance named $name (Project=fitwise)" >&2; exit 1; }

dist_id() {
  aws cloudfront list-distributions --output json |
    jq -r --arg c "$comment" '[.DistributionList.Items[]? | select(.Comment == $c)][0].Id // empty'
}

config_json() {  # config_json <caller-reference>
  jq -n --arg ref "$1" --arg comment "$comment" --arg origin "$origin_dns" \
    --arg off "$CACHING_DISABLED" --arg opt "$CACHING_OPTIMIZED" --arg orp "$ALL_VIEWER_EXCEPT_HOST" '
    def methods($m): {Quantity: ($m | length), Items: $m};
    def beh: {
      TargetOriginId: "ec2", ViewerProtocolPolicy: "redirect-to-https", Compress: true,
      SmoothStreaming: false, FieldLevelEncryptionId: "",
      LambdaFunctionAssociations: {Quantity: 0}, FunctionAssociations: {Quantity: 0}
    };
    {
      CallerReference: $ref, Comment: $comment, Enabled: true, PriceClass: "PriceClass_100",
      HttpVersion: "http2", IsIPV6Enabled: true, DefaultRootObject: "",
      Origins: {Quantity: 1, Items: [{
        Id: "ec2", DomainName: $origin, OriginPath: "", CustomHeaders: {Quantity: 0},
        CustomOriginConfig: {HTTPPort: 80, HTTPSPort: 443, OriginProtocolPolicy: "http-only",
          OriginSslProtocols: {Quantity: 1, Items: ["TLSv1.2"]},
          OriginReadTimeout: 60, OriginKeepaliveTimeout: 5}
      }]},
      # Default: the SPA shell and its routes. Never cached, so a release shows up at once.
      DefaultCacheBehavior: (beh + {
        AllowedMethods: (methods(["GET","HEAD"]) + {CachedMethods: methods(["GET","HEAD"])}),
        CachePolicyId: $off, OriginRequestPolicyId: $orp }),
      CacheBehaviors: {Quantity: 2, Items: [
        # API: never cached; all methods; cookies, query string and headers (except Host) forwarded.
        (beh + { PathPattern: "/api/*",
          AllowedMethods: (methods(["GET","HEAD","OPTIONS","PUT","POST","PATCH","DELETE"])
            + {CachedMethods: methods(["GET","HEAD"])}),
          CachePolicyId: $off, OriginRequestPolicyId: $orp }),
        # Hashed Vite build output: immutable, cached.
        (beh + { PathPattern: "/assets/*",
          AllowedMethods: (methods(["GET","HEAD"]) + {CachedMethods: methods(["GET","HEAD"])}),
          CachePolicyId: $opt })
      ]},
      CustomErrorResponses: {Quantity: 0}, Restrictions: {GeoRestriction: {RestrictionType: "none", Quantity: 0}},
      ViewerCertificate: {CloudFrontDefaultCertificate: true, MinimumProtocolVersion: "TLSv1.2_2021"},
      Logging: {Enabled: false, IncludeCookies: false, Bucket: "", Prefix: ""},
      WebACLId: "", Aliases: {Quantity: 0}
    }'
}

# The desired config is hashed (with a fixed caller reference) and the hash is kept in the
# distribution's `ConfigSha` tag, so a re-run with no change makes no UpdateDistribution call.
config_sha() { config_json fixed | jq -S -c . | sha256sum | cut -c1-16; }

ensure() {
  local id sha arn; id="$(dist_id)"; sha="$(config_sha)"
  if [ -z "$id" ]; then
    local ref cfg; ref="$name-$(date -u +%Y%m%dT%H%M%SZ)"; cfg="$(config_json "$ref")"
    echo "creating distribution for $name (origin $origin_dns)"
    id="$(aws cloudfront create-distribution-with-tags --distribution-config-with-tags \
      "$(jq -n --argjson c "$cfg" --arg env "$env" --arg sha "$sha" \
        '{DistributionConfig: $c, Tags: {Items: [{Key:"Project",Value:"fitwise"},{Key:"Env",Value:$env},{Key:"ConfigSha",Value:$sha}]}}')" \
      --query Distribution.Id --output text)"
  else
    arn="$(aws cloudfront get-distribution --id "$id" --query Distribution.ARN --output text)"
    if [ "$(aws cloudfront list-tags-for-resource --resource "$arn" --query "Tags.Items[?Key=='ConfigSha']|[0].Value" --output text)" = "$sha" ]; then
      echo "distribution $id is up to date"
    else
      local cur etag ref; cur="$(aws cloudfront get-distribution-config --id "$id" --output json)"
      etag="$(jq -r .ETag <<<"$cur")"; ref="$(jq -r .DistributionConfig.CallerReference <<<"$cur")"
      echo "updating distribution $id"
      aws cloudfront update-distribution --id "$id" --if-match "$etag" \
        --distribution-config "$(config_json "$ref")" >/dev/null
      aws cloudfront tag-resource --resource "$arn" --tags "Items=[{Key=ConfigSha,Value=$sha}]"
    fi
  fi
  status
}

status() {
  local id; id="$(dist_id)"
  [ -n "$id" ] || { echo "no distribution for $name yet"; return 0; }
  aws cloudfront get-distribution --id "$id" --output json |
    jq -r '"id=\(.Distribution.Id)\nurl=https://\(.Distribution.DomainName)\nstatus=\(.Distribution.Status)"'
  aws ec2 describe-security-groups --group-ids "$sg" --output json |
    jq -r '.SecurityGroups[0].IpPermissions[] | select(.FromPort == 80) |
      "sg port 80: cidrs=\([.IpRanges[].CidrIp] | join(",")) prefix_lists=\([.PrefixListIds[].PrefixListId] | join(","))"'
}

url() {
  local id; id="$(dist_id)"; [ -n "$id" ] || { echo "no distribution yet; run ensure" >&2; exit 1; }
  aws cloudfront get-distribution --id "$id" --query Distribution.DomainName --output text
}

lock_add() {
  local out
  if out="$(aws ec2 authorize-security-group-ingress --group-id "$sg" --ip-permissions \
      "IpProtocol=tcp,FromPort=80,ToPort=80,PrefixListIds=[{PrefixListId=$PREFIX_LIST,Description=CloudFront origin-facing (#220)}]" 2>&1)"; then
    echo "added port 80 from $PREFIX_LIST on $sg"
  elif grep -q InvalidPermission.Duplicate <<<"$out"; then
    echo "port 80 from $PREFIX_LIST already allowed on $sg"
  else
    echo "$out" >&2; exit 1
  fi
}

lock_revoke() {
  # Refuse to close the open rule unless the prefix-list rule is in place.
  aws ec2 describe-security-groups --group-ids "$sg" --output json |
    jq -e --arg pl "$PREFIX_LIST" '.SecurityGroups[0].IpPermissions[] | select(.FromPort == 80) |
      .PrefixListIds[] | select(.PrefixListId == $pl)' >/dev/null ||
    { echo "run lock-add first: no port 80 rule for $PREFIX_LIST on $sg" >&2; exit 1; }
  if aws ec2 revoke-security-group-ingress --group-id "$sg" --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null 2>&1; then
    echo "revoked port 80 from 0.0.0.0/0 on $sg"
  else
    echo "port 80 from 0.0.0.0/0 is already closed on $sg"
  fi
}

unlock() {
  aws ec2 authorize-security-group-ingress --group-id "$sg" --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null 2>&1 &&
    echo "re-opened port 80 to 0.0.0.0/0 on $sg" || echo "port 80 is already open to 0.0.0.0/0 on $sg"
}

verify() {
  local host; host="$(url)"; local base="https://$host" fail=0
  chk() { if "${@:2}"; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
  chk "https/healthz 200 (valid certificate, no -k)" \
    bash -c "[ \"\$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' '$base/api/v1/healthz')\" = 200 ]"
  chk "http redirects to https" \
    bash -c "curl -sS --max-time 15 -o /dev/null -D - 'http://$host/' | tr -d '\r' | grep -iq '^location: https://'"
  chk "readyz 200" \
    bash -c "[ \"\$(curl -sS --max-time 15 -o /dev/null -w '%{http_code}' '$base/api/v1/readyz')\" = 200 ]"
  chk "SPA route serves index.html" \
    bash -c "curl -sS --max-time 15 '$base/today' | grep -qi '<div id=\"root\"'"
  chk "/api is not cached (X-Cache is never a Hit)" \
    bash -c "curl -sS -o /dev/null -D - '$base/api/v1/healthz' >/dev/null; curl -sS -o /dev/null -D - '$base/api/v1/healthz' | tr -d '\r' | grep -i '^x-cache:' | grep -vqi hit"
  return "$fail"
}

case "$cmd" in
  ensure) ensure;; status) status;; lock-add) lock_add;; lock-revoke) lock_revoke;;
  unlock) unlock;; verify) verify;; *) usage;;
esac
