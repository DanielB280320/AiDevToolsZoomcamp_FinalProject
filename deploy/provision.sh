#!/usr/bin/env bash
# Provision the FitWise AWS hosts (spec §12). Idempotent: every resource is
# looked up by name/tag first and only created when missing.
#
#   deploy/provision.sh                          # default AWS CLI profile
#   OWNER_CIDR=1.2.3.4/32 deploy/provision.sh    # override auto-detected owner IP
#
# Creates: 2 security groups, 1 IAM role + instance profile (SSM only),
# 2 EC2 instances (+ encrypted gp3 root volumes), 2 Elastic IPs, and one
# least-privilege IAM deploy user per GitHub environment.
# No key pair, port 22 stays closed: access is via SSM Session/Run Command.
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
export AWS_DEFAULT_REGION="$REGION" AWS_PAGER=""
GH_REPO="${GH_REPO:-DanielB280320/AiDevToolsZoomcamp_FinalProject}"
OWNER_CIDR="${OWNER_CIDR:-$(curl -fsS https://checkip.amazonaws.com | tr -d '\n')/32}"
OTLP_PORT=4317
GRAFANA_PORT=3000
declare -A TYPE=([dev]="${DEV_TYPE:-t3.small}" [prod]="${PROD_TYPE:-c7i-flex.large}")
declare -A GH_ENV=([dev]=dev [prod]=production)
VOLUME_GB=30
AMI_PARAM=/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
VPC="$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)"

tags() { # <env> <resource-type> <name>
  echo "ResourceType=$2,Tags=[{Key=Project,Value=fitwise},{Key=Env,Value=$1},{Key=Name,Value=$3}]"
}
log() { echo "[provision] $*" >&2; }
# Create an access key and pipe both halves into GitHub environment secrets.
# Nothing is echoed or written to disk; use also for rotation (README).
create_and_store_key() { # <iam-user> <github-env>
  local key
  key="$(aws iam create-access-key --user-name "$1" --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)"
  printf '%s' "$key" | awk '{printf "%s", $1}' | gh secret set AWS_ACCESS_KEY_ID --env "$2" --repo "$GH_REPO"
  printf '%s' "$key" | awk '{printf "%s", $2}' | gh secret set AWS_SECRET_ACCESS_KEY --env "$2" --repo "$GH_REPO"
}

# --- IAM: instance profile (SSM agent only) ---------------------------------
ROLE=fitwise-ec2-ssm
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  log "creating role $ROLE"
  aws iam create-role --role-name "$ROLE" --tags Key=Project,Value=fitwise \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
fi
aws iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
if ! aws iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$ROLE" --tags Key=Project,Value=fitwise >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
  sleep 10 # IAM propagation
fi

# --- Security groups --------------------------------------------------------
sg_id() { aws ec2 describe-security-groups --filters Name=group-name,Values="$1" Name=vpc-id,Values="$VPC" --query 'SecurityGroups[0].GroupId' --output text | sed 's/^None$//'; }
ensure_sg() { # <env>
  local env=$1 name=fitwise-$1 id
  id="$(sg_id "$name")"
  if [ -z "$id" ]; then
    log "creating security group $name"
    id="$(aws ec2 create-security-group --group-name "$name" --description "FitWise $env (no SSH, SSM access)" --vpc-id "$VPC" \
      --tag-specifications "$(tags "$env" security-group "$name")" --query GroupId --output text)"
  fi
  echo "$id"
}
allow() { # <sg> <port> <cidr> <desc>  (duplicate rule errors are ignored)
  aws ec2 authorize-security-group-ingress --group-id "$1" --ip-permissions \
    "IpProtocol=tcp,FromPort=$2,ToPort=$2,IpRanges=[{CidrIp=$3,Description=$4}]" >/dev/null 2>&1 || true
}
declare -A SG
for env in dev prod; do SG[$env]="$(ensure_sg "$env")"; allow "${SG[$env]}" 80 0.0.0.0/0 "HTTP public"; done

# --- Instances + Elastic IPs ------------------------------------------------
AMI="$(aws ssm get-parameter --name "$AMI_PARAM" --query Parameter.Value --output text)"
declare -A IID EIP
for env in dev prod; do
  name=fitwise-$env
  IID[$env]="$(aws ec2 describe-instances --filters Name=tag:Name,Values="$name" Name=tag:Project,Values=fitwise \
    Name=instance-state-name,Values=pending,running,stopped,stopping --query 'Reservations[0].Instances[0].InstanceId' --output text | sed 's/^None$//')"
  if [ -z "${IID[$env]}" ]; then
    log "launching $name (${TYPE[$env]})"
    IID[$env]="$(aws ec2 run-instances --image-id "$AMI" --instance-type "${TYPE[$env]}" --count 1 \
      --security-group-ids "${SG[$env]}" --iam-instance-profile Name="$ROLE" \
      --metadata-options HttpTokens=required,HttpPutResponseHopLimit=2 \
      --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=$VOLUME_GB,VolumeType=gp3,DeleteOnTermination=true,Encrypted=true}" \
      --tag-specifications "$(tags "$env" instance "$name")" "$(tags "$env" volume "$name")" \
      --query 'Instances[0].InstanceId' --output text)"
  fi
  aws ec2 wait instance-running --instance-ids "${IID[$env]}"
  alloc="$(aws ec2 describe-addresses --filters Name=tag:Name,Values="$name" Name=tag:Project,Values=fitwise --query 'Addresses[0].AllocationId' --output text | sed 's/^None$//')"
  if [ -z "$alloc" ]; then
    log "allocating Elastic IP for $name"
    alloc="$(aws ec2 allocate-address --domain vpc --tag-specifications "$(tags "$env" elastic-ip "$name")" --query AllocationId --output text)"
  fi
  aws ec2 associate-address --instance-id "${IID[$env]}" --allocation-id "$alloc" --allow-reassociation >/dev/null
  EIP[$env]="$(aws ec2 describe-addresses --allocation-ids "$alloc" --query 'Addresses[0].PublicIp' --output text)"
done

# --- Security group rules that need the addresses above ---------------------
allow "${SG[prod]}" "$GRAFANA_PORT" "$OWNER_CIDR" "Grafana owner IP"
allow "${SG[prod]}" "$OTLP_PORT" "${EIP[dev]}/32" "OTLP from dev instance"
# Port 22 is intentionally never opened: access is via SSM (see README).

# --- GitHub Actions deploy credentials (least-privilege IAM user per env) ---
# The org SCP denies GitHub OIDC, so each GitHub Environment gets its own IAM
# user that may only run AWS-RunShellScript on that environment's instance and
# read command results. The access key is created once (only if the user has
# none) and piped straight into GitHub environment secrets: never printed and
# never written to disk. Rotation: see deploy/README.md. GITHUB_AUTH=none skips.
if [ "${GITHUB_AUTH:-iam-user}" = iam-user ]; then
  for env in dev prod; do
    user=fitwise-deploy-$env
    ghenv=${GH_ENV[$env]}
    aws iam get-user --user-name "$user" >/dev/null 2>&1 ||
      { log "creating IAM user $user"; aws iam create-user --user-name "$user" --tags Key=Project,Value=fitwise Key=Env,Value="$env" >/dev/null; }
    policy="{\"Version\":\"2012-10-17\",\"Statement\":[
     {\"Effect\":\"Allow\",\"Action\":\"ssm:SendCommand\",\"Resource\":\"arn:aws:ssm:$REGION::document/AWS-RunShellScript\"},
     {\"Effect\":\"Allow\",\"Action\":\"ssm:SendCommand\",\"Resource\":\"arn:aws:ec2:$REGION:$ACCOUNT:instance/${IID[$env]}\",\"Condition\":{\"StringEquals\":{\"ssm:resourceTag/Project\":\"fitwise\",\"ssm:resourceTag/Env\":\"$env\"}}},
     {\"Effect\":\"Allow\",\"Action\":\"ssm:GetCommandInvocation\",\"Resource\":\"*\"}]}"
    aws iam put-user-policy --user-name "$user" --policy-name ssm-run-command --policy-document "$policy"
    gh api -X PUT "repos/$GH_REPO/environments/$ghenv" >/dev/null
    if [ "$(aws iam list-access-keys --user-name "$user" --query 'length(AccessKeyMetadata)' --output text)" = 0 ]; then
      log "creating access key for $user and storing it in GitHub environment $ghenv"
      create_and_store_key "$user" "$ghenv"
    fi
    printf '%s' "$REGION" | gh secret set AWS_REGION --env "$ghenv" --repo "$GH_REPO"
    printf '%s' "${IID[$env]}" | gh secret set DEPLOY_INSTANCE_ID --env "$ghenv" --repo "$GH_REPO"
  done
fi

cat <<OUT
dev_instance_id=${IID[dev]}
dev_elastic_ip=${EIP[dev]}
prod_instance_id=${IID[prod]}
prod_elastic_ip=${EIP[prod]}
dev_sg=${SG[dev]}
prod_sg=${SG[prod]}
OUT
