#!/usr/bin/env bash
# Tests deploy/backup.sh (#66) with fake docker and aws: no network, no root, no database.
#   - success: dump validated, uploaded with SSE under <prefix><UTC>.dump, LAST_BACKUP written, exit 0
#   - bucket defaults to fitwise-prod-backups-<account id>
#   - each failure (db container down, pg_dump fails, empty dump, invalid dump, upload fails)
#     exits non-zero, uploads nothing on pre-upload failures, and leaves no temp files
#   - output never contains dump contents
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"; script="$here/../deploy/backup.sh"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
fails=0
ck() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (want '$3', got '$2')"; fails=$((fails+1)); fi; }
mkdir -p "$tmp/bin" "$tmp/app" "$tmp/tmp"
cat > "$tmp/bin/docker" <<'F'
#!/usr/bin/env bash
case "$1" in
  ps) [ "${FAKE_NO_DB:-0}" = 1 ] || echo abc123 ;;
  exec)
    if [[ "$*" == *pg_dump* ]]; then
      [ "${FAKE_DUMP_FAIL:-0}" = 1 ] && exit 1
      [ "${FAKE_DUMP_EMPTY:-0}" = 1 ] || printf 'SECRET-ROW-CONTENT'
    else
      cat > /dev/null; [ "${FAKE_LIST_FAIL:-0}" = 1 ] && exit 1; exit 0
    fi ;;
esac
F
cat > "$tmp/bin/aws" <<'F'
#!/usr/bin/env bash
echo "aws $*" >> "$FAKE_LOG"
case "$1 $2" in
  "sts get-caller-identity") echo 123456789012 ;;
  "s3 cp") [ "${FAKE_UPLOAD_FAIL:-0}" = 1 ] && exit 1; exit 0 ;;
  *) exit 0 ;;
esac
F
chmod +x "$tmp/bin/docker" "$tmp/bin/aws"
export PATH="$tmp/bin:$PATH" APP_DIR="$tmp/app" TMPDIR="$tmp/tmp" FAKE_LOG="$tmp/log"
run() { : > "$FAKE_LOG"; rm -f "$tmp/app/LAST_BACKUP"; env "$@" bash "$script" > "$tmp/out" 2>&1; echo $?; }

ck "success exits 0" "$(run X=1)" 0
ck "uploads to the default bucket with SSE" "$(grep -c 's3 cp .* s3://fitwise-prod-backups-123456789012/prod/[0-9]\{8\}T[0-9]\{6\}Z.dump .*--sse AES256' "$FAKE_LOG")" 1
ck "LAST_BACKUP written" "$([ -s "$tmp/app/LAST_BACKUP" ] && echo yes)" yes
ck "output has no dump contents" "$(grep -c SECRET-ROW "$tmp/out")" 0
ck "temp dir cleaned" "$(ls "$tmp/tmp" | wc -l | tr -d ' ')" 0
ck "bucket override" "$(run BACKUP_BUCKET=custom >/dev/null; grep -c 's3://custom/prod/' "$FAKE_LOG")" 1
for f in FAKE_NO_DB FAKE_DUMP_FAIL FAKE_DUMP_EMPTY FAKE_LIST_FAIL; do
  got="$(run "$f=1")"; [ "$got" != 0 ] && got=nonzero
  ck "$f fails" "$got" nonzero
  ck "$f uploads nothing" "$(grep -c 's3 cp' "$FAKE_LOG")" 0
  ck "$f leaves no temp files" "$(ls "$tmp/tmp" | wc -l | tr -d ' ')" 0
  ck "$f writes no LAST_BACKUP" "$([ -e "$tmp/app/LAST_BACKUP" ] && echo yes || echo no)" no
done
got="$(run FAKE_UPLOAD_FAIL=1)"; [ "$got" != 0 ] && got=nonzero
ck "upload failure fails" "$got" nonzero
ck "upload failure writes no LAST_BACKUP" "$([ -e "$tmp/app/LAST_BACKUP" ] && echo yes || echo no)" no
ck "failure is logged as ERROR" "$(grep -c 'ERROR: upload failed' "$tmp/out")" 1
[ "$fails" = 0 ] && echo "all backup tests passed" || { echo "$fails failure(s)"; exit 1; }
