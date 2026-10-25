#!/usr/bin/env bash
# Nightly production database backup (issue #66, spec §12). Runs as root on fitwise-prod from
# fitwise-backup.timer; installed to /opt/fitwise/bin by deploy/bootstrap.sh.
#
#   pg_dump -Fc (custom format, compressed) of the compose `db` container
#   -> validated (pg_restore --list) -> aws s3 cp s3://<bucket>/prod/<UTC timestamp>.dump
#
# Credentials: the EC2 instance role only (no keys on the host). Any failure exits non-zero, so
# the systemd unit fails and the reason is in `journalctl -u fitwise-backup`. Output holds only
# the object key, size and statuses: never dump contents, database credentials or row data.
#
# Settings (optional file /etc/fitwise-backup.env, no secrets): BACKUP_BUCKET (default
# fitwise-prod-backups-<account id>), AWS_REGION (default us-east-2), BACKUP_PREFIX (default prod/).
set -euo pipefail
umask 077

APP_DIR="${APP_DIR:-/opt/fitwise}"
REGION="${AWS_REGION:-us-east-2}"
PREFIX="${BACKUP_PREFIX:-prod/}"
export AWS_DEFAULT_REGION="$REGION" AWS_PAGER=""

log() { printf '%s fitwise-backup: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
die() { log "ERROR: $*"; exit 1; }

bucket="${BACKUP_BUCKET:-}"
if [ -z "$bucket" ]; then
  account="$(aws sts get-caller-identity --query Account --output text)" || die "cannot determine the AWS account (instance role missing?)"
  bucket="fitwise-prod-backups-$account"
fi

db="$(docker ps -q --filter label=com.docker.compose.project=fitwise --filter label=com.docker.compose.service=db | head -n1)"
[ -n "$db" ] || die "database container not running"

work="$(mktemp -d "${TMPDIR:-/var/tmp}/fitwise-backup.XXXXXX")"
trap 'rm -rf "$work"' EXIT
key="${PREFIX}$(date -u +%Y%m%dT%H%M%SZ).dump"
file="$work/db.dump"

log "dumping database to a temporary file"
# The container's own POSTGRES_USER / POSTGRES_DB are used; no password passes through this script.
docker exec "$db" sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$file" || die "pg_dump failed"
[ -s "$file" ] || die "dump is empty"
docker exec -i "$db" pg_restore --list < "$file" > /dev/null || die "dump failed validation (pg_restore --list)"
size="$(wc -c < "$file" | tr -d ' ')"

log "uploading s3://$bucket/$key ($size bytes)"
aws s3 cp "$file" "s3://$bucket/$key" --only-show-errors --sse AES256 || die "upload failed"
aws s3api head-object --bucket "$bucket" --key "$key" > /dev/null || die "uploaded object not found"

if [ -d "$APP_DIR" ]; then
  printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$key" "$size" > "$APP_DIR/LAST_BACKUP.tmp" && mv -f "$APP_DIR/LAST_BACKUP.tmp" "$APP_DIR/LAST_BACKUP"
fi
log "backup ok: $key ($size bytes)"
