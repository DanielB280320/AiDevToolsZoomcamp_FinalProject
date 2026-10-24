#!/usr/bin/env bash
# Host bootstrap (Amazon Linux 2023). Idempotent: running it twice changes nothing.
# Run as root on the instance, normally via deploy/bootstrap-remote.sh (SSM).
#
#   ENV_NAME=dev|prod deploy/bootstrap.sh
#
# Installs Docker + Compose plugin, creates the `deploy` user, /opt/fitwise
# with CURRENT_TAG / PREVIOUS_TAG and a root-only env file, and runs a
# placeholder container on port 80 until the app is deployed (#13).
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
ENV_NAME="${ENV_NAME:?set ENV_NAME=dev|prod}"
APP_DIR=/opt/fitwise
COMPOSE_VERSION=v2.29.7

command -v docker >/dev/null || dnf install -y docker
systemctl enable --now docker

if [ ! -x /usr/local/lib/docker/cli-plugins/docker-compose ]; then
  mkdir -p /usr/local/lib/docker/cli-plugins
  curl -fsSL "https://github.com/docker/compose/releases/download/$COMPOSE_VERSION/docker-compose-linux-x86_64" \
    -o /usr/local/lib/docker/cli-plugins/docker-compose
  chmod 755 /usr/local/lib/docker/cli-plugins/docker-compose
fi

id deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash deploy
id -nG deploy | grep -qw docker || usermod -aG docker deploy

mkdir -p "$APP_DIR"
chown deploy:deploy "$APP_DIR"; chmod 755 "$APP_DIR"
for f in CURRENT_TAG PREVIOUS_TAG; do
  [ -e "$APP_DIR/$f" ] || { : > "$APP_DIR/$f"; chown deploy:deploy "$APP_DIR/$f"; }
done
if [ ! -e "$APP_DIR/.env" ]; then
  printf '# FitWise %s runtime configuration (root-only). Fill in per .env.example.\nFITWISE_ENV=%s\n' "$ENV_NAME" "$ENV_NAME" > "$APP_DIR/.env"
fi
chown root:root "$APP_DIR/.env"; chmod 600 "$APP_DIR/.env"

# Placeholder on port 80 (removed by the first real deploy, #13).
if [ ! -s "$APP_DIR/CURRENT_TAG" ]; then
  docker ps -a --format '{{.Names}}' | grep -qx fitwise-placeholder ||
    docker run -d --name fitwise-placeholder --restart unless-stopped -p 80:80 nginx:alpine >/dev/null
  docker start fitwise-placeholder >/dev/null 2>&1 || true
fi
echo "bootstrap ok ($ENV_NAME)"
