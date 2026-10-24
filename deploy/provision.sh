#!/usr/bin/env bash
# Provision the FitWise AWS hosts (spec §12). Idempotent: every resource is
# looked up by name/tag first and only created when missing.
#
#   deploy/provision.sh                          # default AWS CLI profile
#   OWNER_CIDR=1.2.3.4/32 deploy/provision.sh    # override auto-detected owner IP
#
# Creates: 2 security groups, 1 IAM role + instance profile (SSM only),
# 2 EC2 instances (+ encrypted gp3 root volumes) and 2 Elastic IPs.
# No key pair, port 22 stays closed: access is via SSM. Deploys are pull-based
# (ADR 0010), so no deploy credentials are created here.
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
export AWS_DEFAULT_REGION="$REGION" AWS_PAGER=""
OWNER_CIDR="${OWNER_CIDR:-$(curl -fsS https://checkip.amazonaws.com | tr -d '\n')/32}"
OTLP_PORT=4317
GRAFANA_PORT=3000
declare -A TYPE=([dev]="${DEV_TYPE:-t3.small}" [prod]="${PROD_TYPE:-c7i-flex.large}")
VOLUME_GB=30
AMI_PARAM=/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64
VPC="$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)"

tags() { # <env> <resource-type> <name>
  echo "ResourceType=$2,Tags=[{Key=Project,Value=fitwise},{Key=Env,Value=$1},{Key=Name,Value=$3}]"
}
log() { echo "[provision] $*" >&2; }

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
allow() { # <sg> <port> <cidr> <desc>  (only a duplicate-rule error is ignored)
  local out
  if ! out="$(aws ec2 authorize-security-group-ingress --group-id "$1" --ip-permissions \
      "IpProtocol=tcp,FromPort=$2,ToPort=$2,IpRanges=[{CidrIp=$3,Description=$4}]" 2>&1)"; then
    case "$out" in
      *InvalidPermission.Duplicate*) ;;
      *) echo "$out" >&2; return 1 ;;
    esac
  fi
}
only_from() { # <sg> <port> <cidr> <desc>: the port allows exactly this CIDR; stale CIDRs are revoked
  local old c
  old="$(aws ec2 describe-security-groups --group-ids "$1" \
    --query "SecurityGroups[0].IpPermissions[?FromPort==\`$2\`].IpRanges[].CidrIp" --output text)"
  for c in $old; do
    if [ "$c" != "$3" ]; then
      log "port $2 on $1: replacing $c with $3"
      aws ec2 revoke-security-group-ingress --group-id "$1" --protocol tcp --port "$2" --cidr "$c" >/dev/null
    fi
  done
  allow "$1" "$2" "$3" "$4"
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
only_from "${SG[prod]}" "$GRAFANA_PORT" "$OWNER_CIDR" "Grafana owner IP"
only_from "${SG[prod]}" "$OTLP_PORT" "${EIP[dev]}/32" "OTLP from dev instance"
# Port 22 is intentionally never opened: access is via SSM (see README).

cat <<OUT
dev_instance_id=${IID[dev]}
dev_elastic_ip=${EIP[dev]}
prod_instance_id=${IID[prod]}
prod_elastic_ip=${EIP[prod]}
dev_sg=${SG[dev]}
prod_sg=${SG[prod]}
OUT
