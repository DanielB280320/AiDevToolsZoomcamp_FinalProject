#!/usr/bin/env bash
# Create the AWS side of the prod database backups (issue #66, spec §12). Idempotent.
#
#   deploy/provision-backups.sh
#
# Creates (all tagged Project=fitwise, Env=prod):
#   S3 bucket   fitwise-prod-backups-<account id>, us-east-2: public access fully blocked,
#               default encryption SSE-S3, TLS-only bucket policy, versioning off, lifecycle rule
#               "expire-prod-dumps" deleting objects under prod/ after 7 days (and aborting
#               incomplete multipart uploads after 1 day).
#   IAM role    fitwise-ec2-prod (+ instance profile of the same name): AmazonSSMManagedInstanceCore
#               plus inline policy fitwise-prod-backup-bucket: s3:PutObject / GetObject on
#               prod/* and s3:ListBucket (prefix prod/) on that bucket only. No delete: the
#               lifecycle rule expires objects. A separate role (not the shared fitwise-ec2-ssm)
#               keeps the dev host away from production dumps.
#   Association the fitwise-prod instance is switched to that profile (SSM keeps working).
# Cost: S3 Standard, a few MB per dump x 7 = well under USD 0.01 per month.
set -euo pipefail
REGION="${AWS_REGION:-us-east-2}"
export AWS_DEFAULT_REGION="$REGION" AWS_PAGER=""
log() { echo "[provision-backups] $*" >&2; }

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="fitwise-prod-backups-$ACCOUNT"
ROLE=fitwise-ec2-prod
TAGS_S3='{"TagSet":[{"Key":"Project","Value":"fitwise"},{"Key":"Env","Value":"prod"}]}'

# --- bucket ---
if ! aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  log "creating bucket $BUCKET"
  aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
    --create-bucket-configuration "LocationConstraint=$REGION" >/dev/null
fi
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
aws s3api put-bucket-tagging --bucket "$BUCKET" --tagging "$TAGS_S3"
aws s3api put-bucket-policy --bucket "$BUCKET" --policy "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Sid\":\"TlsOnly\",\"Effect\":\"Deny\",\"Principal\":\"*\",\"Action\":\"s3:*\",\"Resource\":[\"arn:aws:s3:::$BUCKET\",\"arn:aws:s3:::$BUCKET/*\"],\"Condition\":{\"Bool\":{\"aws:SecureTransport\":\"false\"}}}]}"
aws s3api put-bucket-lifecycle-configuration --bucket "$BUCKET" --lifecycle-configuration \
  '{"Rules":[{"ID":"expire-prod-dumps","Status":"Enabled","Filter":{"Prefix":"prod/"},"Expiration":{"Days":7},"AbortIncompleteMultipartUpload":{"DaysAfterInitiation":1}}]}'

# --- role + instance profile ---
if ! aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  log "creating role $ROLE"
  aws iam create-role --role-name "$ROLE" --tags Key=Project,Value=fitwise Key=Env,Value=prod \
    --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
fi
aws iam attach-role-policy --role-name "$ROLE" --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam put-role-policy --role-name "$ROLE" --policy-name fitwise-prod-backup-bucket --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[{\"Sid\":\"Objects\",\"Effect\":\"Allow\",\"Action\":[\"s3:PutObject\",\"s3:GetObject\"],\"Resource\":\"arn:aws:s3:::$BUCKET/prod/*\"},{\"Sid\":\"List\",\"Effect\":\"Allow\",\"Action\":\"s3:ListBucket\",\"Resource\":\"arn:aws:s3:::$BUCKET\",\"Condition\":{\"StringLike\":{\"s3:prefix\":\"prod/*\"}}}]}"
if ! aws iam get-instance-profile --instance-profile-name "$ROLE" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$ROLE" --tags Key=Project,Value=fitwise Key=Env,Value=prod >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "$ROLE" --role-name "$ROLE"
  sleep 10 # IAM propagation
fi

# --- switch the prod instance to the new profile ---
IID="$(aws ec2 describe-instances --filters Name=tag:Name,Values=fitwise-prod Name=tag:Project,Values=fitwise \
  Name=instance-state-name,Values=running --query 'Reservations[0].Instances[0].InstanceId' --output text)"
[ -n "$IID" ] && [ "$IID" != None ] || { echo "fitwise-prod is not running" >&2; exit 1; }
read -r ASSOC CUR <<<"$(aws ec2 describe-iam-instance-profile-associations --filters Name=instance-id,Values="$IID" \
  --query 'IamInstanceProfileAssociations[?State==`associated`]|[0].[AssociationId,IamInstanceProfile.Arn]' --output text)"
case "${CUR:-}" in
  */"$ROLE") log "prod already uses $ROLE" ;;
  ""|None) aws ec2 associate-iam-instance-profile --instance-id "$IID" --iam-instance-profile Name="$ROLE" >/dev/null ;;
  *) log "replacing $CUR on $IID"
     aws ec2 replace-iam-instance-profile-association --association-id "$ASSOC" --iam-instance-profile Name="$ROLE" >/dev/null ;;
esac
echo "bucket=$BUCKET role=$ROLE instance=$IID"
