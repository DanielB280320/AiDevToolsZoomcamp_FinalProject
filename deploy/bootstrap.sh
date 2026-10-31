#!/usr/bin/env bash
# Host bootstrap (Amazon Linux 2023). Idempotent: running it twice changes nothing.
# Run as root on the instance, normally via deploy/bootstrap-remote.sh (SSM).
#
#   ENV_NAME=dev|prod deploy/bootstrap.sh
#
# Installs Docker + Compose plugin + jq, creates the `deploy` user, /opt/fitwise with CURRENT_TAG /
# PREVIOUS_TAG and a root-only env file (secrets generated on the host), runs a placeholder
# container on port 80 until the first real deploy, and installs the pull-based deploy poller
# (systemd timer + scripts, #13, ADR 0010); the weekly adaptive-calorie timer (#42); on prod also the nightly backup timer (#66).
#
#   DEPLOY_REF=<branch|sha>   where to fetch the deploy scripts from (default main; public repo).
#                             Scripts next to this file are used instead when present.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
ENV_NAME="${ENV_NAME:?set ENV_NAME=dev|prod}"
APP_DIR=/opt/fitwise
REPO="${GITHUB_REPOSITORY:-DanielB280320/AiDevToolsZoomcamp_FinalProject}"
DEPLOY_REF="${DEPLOY_REF:-main}"
IMAGE_NAMESPACE="${IMAGE_NAMESPACE:-ghcr.io/$(printf '%s' "${REPO%%/*}" | tr '[:upper:]' '[:lower:]')/}"
COMPOSE_VERSION=v2.29.7
# sha256 of docker-compose-linux-x86_64 for that version (from the release's .sha256 asset)
COMPOSE_SHA256=383ce6698cd5d5bbf958d2c8489ed75094e34a77d340404d9f32c4ae9e12baf0

command -v docker >/dev/null || dnf install -y docker
command -v jq >/dev/null || dnf install -y jq
systemctl enable --now docker

if [ ! -x /usr/local/lib/docker/cli-plugins/docker-compose ]; then
  mkdir -p /usr/local/lib/docker/cli-plugins
  tmp="$(mktemp)"
  curl -fsSL "https://github.com/docker/compose/releases/download/$COMPOSE_VERSION/docker-compose-linux-x86_64" -o "$tmp"
  echo "$COMPOSE_SHA256  $tmp" | sha256sum -c - || { rm -f "$tmp"; echo "compose checksum mismatch" >&2; exit 1; }
  install -m 755 "$tmp" /usr/local/lib/docker/cli-plugins/docker-compose
  rm -f "$tmp"
fi

id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
id -nG deploy | grep -qw docker || usermod -aG docker deploy

mkdir -p "$APP_DIR"
chown deploy:deploy "$APP_DIR"; chmod 755 "$APP_DIR"
for f in CURRENT_TAG PREVIOUS_TAG; do
  [ -e "$APP_DIR/$f" ] || { : > "$APP_DIR/$f"; chown deploy:deploy "$APP_DIR/$f"; }
done
if [ ! -e "$APP_DIR/.env" ]; then
  printf '# FitWise %s runtime configuration (root-only, generated on this host). See .env.example.\nFITWISE_ENV=%s\n' "$ENV_NAME" "$ENV_NAME" > "$APP_DIR/.env"
fi
# Runtime secrets are generated here once and never leave the host (root-only file, not in the repo).
ensure_env() { grep -q "^$1=" "$APP_DIR/.env" || printf '%s=%s\n' "$1" "$2" >> "$APP_DIR/.env"; }
ensure_env APP_ENV "$ENV_NAME"
ensure_env SESSION_COOKIE_SECURE false
ensure_env POSTGRES_PASSWORD "$(openssl rand -hex 24)"
ensure_env JWT_SECRET "$(openssl rand -hex 32)"
ensure_env USER_HASH_SALT "$(openssl rand -hex 24)"

# --- Observability settings (#67): prod runs the stack, dev forwards to prod --------------------
# set_env replaces a line (used for the upstream address, which changes when prod's IP does).
set_env() {
  if grep -q "^$1=" "$APP_DIR/.env"; then
    local tmp; tmp="$(mktemp)"; grep -v "^$1=" "$APP_DIR/.env" > "$tmp"; cat "$tmp" > "$APP_DIR/.env"; rm -f "$tmp"
  fi
  printf '%s=%s\n' "$1" "$2" >> "$APP_DIR/.env"
}
ensure_env GRAFANA_ADMIN_USER admin
ensure_env GRAFANA_ADMIN_PASSWORD "$(openssl rand -hex 16)"   # prod: the Grafana login (never printed)
if [ "$ENV_NAME" = prod ]; then
  ensure_env OBS_MODE full
  ensure_env GRAFANA_BIND 0.0.0.0          # reachable only from the owner IP (security group, provision.sh)
  ensure_env GRAFANA_PORT 3000
  ensure_env OTLP_GRPC_BIND 0.0.0.0        # reachable only from the dev instance (security group)
  token="$(curl -fsS --max-time 3 -X PUT -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' http://169.254.169.254/latest/api/token 2>/dev/null || true)"
  pub="$(curl -fsS --max-time 3 -H "X-aws-ec2-metadata-token: $token" http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || true)"
  if [[ "$pub" =~ ^[0-9.]+$ ]]; then set_env GRAFANA_ROOT_URL "http://$pub:3000"; fi
else
  ensure_env OBS_MODE forward
  # host:4317 of the prod collector; passed by bootstrap-remote.sh (looked up from AWS) or by hand.
  if [[ "${OTLP_UPSTREAM:-}" =~ ^[A-Za-z0-9.-]+:[0-9]+$ ]]; then set_env OTLP_UPSTREAM_ENDPOINT "$OTLP_UPSTREAM"; fi
fi
chown root:root "$APP_DIR/.env"; chmod 600 "$APP_DIR/.env"

# --- Pull-based deploy poller (#13, ADR 0010) -------------------------------------------------
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$APP_DIR/bin" "$APP_DIR/releases"
changed=0
install_file() {  # install_file <name> <destination> <mode>: copies only when the content differs
  local src="$here/$1" tmp
  tmp="$(mktemp)"
  if [ ! -f "$src" ]; then
    curl -fsSL --retry 3 "https://raw.githubusercontent.com/$REPO/$DEPLOY_REF/deploy/$1" -o "$tmp" ||
      { rm -f "$tmp"; echo "cannot fetch deploy/$1 at $DEPLOY_REF" >&2; exit 1; }
    src="$tmp"
  fi
  if ! cmp -s "$src" "$2"; then install -m "$3" -o root -g root "$src" "$2"; changed=1; fi
  rm -f "$tmp"
}
for f in lib.sh poll.sh deploy.sh rollback.sh obs.sh; do install_file "$f" "$APP_DIR/bin/$f" 755; done
install_file fitwise-deploy.service /etc/systemd/system/fitwise-deploy.service 644
install_file fitwise-deploy.timer /etc/systemd/system/fitwise-deploy.timer 644
# Nightly database backup to S3 (#66): prod only. Needs the fitwise-ec2-prod instance role
# (deploy/provision-backups.sh); no AWS keys on the host.
if [ "$ENV_NAME" = prod ]; then
  install_file backup.sh "$APP_DIR/bin/backup.sh" 755
  install_file oncall-compose.sh "$APP_DIR/bin/oncall-compose.sh" 755   # root helper of the on-call agent (#69)
  install_file fitwise-backup.service /etc/systemd/system/fitwise-backup.service 644
  install_file fitwise-backup.timer /etc/systemd/system/fitwise-backup.timer 644
fi
# Weekly adaptive calorie check (#42): dev and prod; runs the CLI inside the backend container.
install_file adaptive-calories.sh "$APP_DIR/bin/adaptive-calories.sh" 755
install_file fitwise-adaptive-calories.service /etc/systemd/system/fitwise-adaptive-calories.service 644
install_file fitwise-adaptive-calories.timer /etc/systemd/system/fitwise-adaptive-calories.timer 644
conf="$(printf 'GITHUB_REPOSITORY=%s\nDEPLOY_ENV=%s\nIMAGE_NAMESPACE=%s' "$REPO" "$ENV_NAME" "$IMAGE_NAMESPACE")"
if [ "$(cat /etc/fitwise-deploy.env 2>/dev/null)" != "$conf" ]; then
  printf '%s\n' "$conf" > /etc/fitwise-deploy.env
  chmod 644 /etc/fitwise-deploy.env   # no secrets in this file
  changed=1
fi
[ "$changed" = 0 ] || systemctl daemon-reload
systemctl enable --now fitwise-deploy.timer >/dev/null
systemctl enable --now fitwise-adaptive-calories.timer >/dev/null
[ "$ENV_NAME" != prod ] || systemctl enable --now fitwise-backup.timer >/dev/null

# Placeholder on port 80 (removed by the first real deploy).
if [ ! -s "$APP_DIR/CURRENT_TAG" ]; then
  docker ps -a --format '{{.Names}}' | grep -qx fitwise-placeholder ||
    docker run -d --name fitwise-placeholder --restart unless-stopped -p 80:80 nginx:alpine >/dev/null
  docker start fitwise-placeholder >/dev/null 2>&1 || true
fi
echo "bootstrap ok ($ENV_NAME)"
