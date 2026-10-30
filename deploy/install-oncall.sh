#!/usr/bin/env bash
# Install the on-call responder as a systemd service on the PROD host (issue #69). Idempotent.
# Run as root on fitwise-prod (SSM session), after bootstrap.sh and the first deploy:
#
#   DEPLOY_REF=<branch|sha> deploy/install-oncall.sh        # default main
#
# Creates the unprivileged user fitwise-oncall (NOT in the docker group), a root-owned checkout of
# the repo (the service cannot edit its own code or allow-list), a Python venv from oncall/uv.lock,
# a separate clone the agent pushes branches from, the docker shim, the sudoers rule (rollback.sh
# and oncall-compose.sh only), the systemd unit and /etc/fitwise-oncall.env (0600 root:root).
#
# Prerequisites it checks but does not install: python3.12, git, gh and the claude CLI (Claude
# Code) on PATH. SECRETS ARE NEVER PASSED TO THIS SCRIPT: the owner puts CLAUDE_CODE_OAUTH_TOKEN (or ANTHROPIC_API_KEY) and
# GH_TOKEN into /etc/fitwise-oncall.env by hand and sets ONCALL_AGENT_ENABLED=1; until then the
# service only receives, deduplicates and captures alerts (agent disabled).
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
REPO="${GITHUB_REPOSITORY:-DanielB280320/AiDevToolsZoomcamp_FinalProject}"
DEPLOY_REF="${DEPLOY_REF:-main}"
APP=/opt/fitwise-oncall
STATE=/var/lib/fitwise-oncall
ENV_FILE=/etc/fitwise-oncall.env
HOST_ENV=/opt/fitwise/.env
USER_NAME=fitwise-oncall

missing=()
for c in python3.12 git gh claude sudo; do command -v "$c" >/dev/null || missing+=("$c"); done
[ "${#missing[@]}" -eq 0 ] || { echo "missing on PATH: ${missing[*]} (install them first, see oncall/README.md)" >&2; exit 1; }
[ -x /opt/fitwise/bin/oncall-compose.sh ] && [ -x /opt/fitwise/bin/rollback.sh ] ||
  { echo "run deploy/bootstrap.sh (prod) with the current scripts first" >&2; exit 1; }

id "$USER_NAME" >/dev/null 2>&1 || useradd --system --create-home --home-dir "$STATE/home" --shell /sbin/nologin "$USER_NAME"
if id -nG "$USER_NAME" | grep -qw docker; then gpasswd -d "$USER_NAME" docker; fi
mkdir -p "$APP" "$STATE/incidents" "$STATE/home"
chown -R "$USER_NAME:$USER_NAME" "$STATE"; chmod 700 "$STATE" "$STATE/home"

# Root-owned checkout: runbooks, ops scripts, responder code.
if [ -d "$APP/app/.git" ]; then git -C "$APP/app" fetch --quiet origin
else git clone --quiet "https://github.com/$REPO.git" "$APP/app"; fi
git -C "$APP/app" checkout --quiet --detach "$(git -C "$APP/app" rev-parse "origin/$DEPLOY_REF" 2>/dev/null || echo "$DEPLOY_REF")"
chown -R root:root "$APP/app"

# Venv from the lock file (hash-checked by uv).
[ -x "$APP/venv/bin/python" ] || python3.12 -m venv "$APP/venv"
[ -x "$APP/venv/bin/uv" ] || "$APP/venv/bin/pip" install --quiet uv
(cd "$APP/app/oncall" && UV_PROJECT_ENVIRONMENT="$APP/venv" "$APP/venv/bin/uv" sync --quiet --locked --no-dev)

# Docker shim and sudoers (visudo-checked): rollback.sh without arguments, the compose helper.
install -d -m 755 "$APP/shim"
install -m 755 "$APP/app/oncall/host/docker" "$APP/shim/docker"
tmp="$(mktemp)"
printf '%s ALL=(root) NOPASSWD: /opt/fitwise/bin/rollback.sh "", /opt/fitwise/bin/oncall-compose.sh\n' "$USER_NAME" > "$tmp"
visudo -cf "$tmp" >/dev/null && install -m 440 -o root -g root "$tmp" /etc/sudoers.d/fitwise-oncall
rm -f "$tmp"

# Separate clone for fix branches (never the deployed checkout). Credentials come from GH_TOKEN.
if [ ! -d "$STATE/clone/.git" ]; then
  sudo -u "$USER_NAME" git clone --quiet "https://github.com/$REPO.git" "$STATE/clone"
fi
sudo -u "$USER_NAME" git -C "$STATE/clone" config user.name "FitWise on-call agent"
sudo -u "$USER_NAME" git -C "$STATE/clone" config user.email "fitwise-oncall@users.noreply.github.com"
sudo -u "$USER_NAME" git -C "$STATE/clone" config credential.helper '!gh auth git-credential'

# Webhook password shared with Grafana (it reads it from /opt/fitwise/.env). Generated once, never printed.
if ! grep -q '^ONCALL_WEBHOOK_PASSWORD=.' "$HOST_ENV"; then
  printf 'ONCALL_WEBHOOK_PASSWORD=%s\n' "$(openssl rand -hex 24)" >> "$HOST_ENV"
fi
if ! grep -q '^ONCALL_WEBHOOK_URL=' "$HOST_ENV"; then
  printf 'ONCALL_WEBHOOK_URL=http://host.docker.internal:8099/alerts\n' >> "$HOST_ENV"
fi
chmod 600 "$HOST_ENV"

if [ ! -e "$ENV_FILE" ]; then
  umask 077
  {
    echo "# FitWise on-call responder (root-only). Own secrets only; see oncall/README.md."
    echo "$(grep '^ONCALL_WEBHOOK_PASSWORD=' "$HOST_ENV" | tail -n1)"
    echo "# Docker bridge gateway: where Grafana's host.docker.internal resolves. Never 0.0.0.0 unfirewalled."
    echo "ONCALL_HOST=$(docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || echo 172.17.0.1)"
    echo "ONCALL_AGENT_ENABLED=0"
    echo "ONCALL_AGENT_MAX_BUDGET_USD=5"
    echo "COMPOSE=sudo -n /opt/fitwise/bin/oncall-compose.sh"
    echo "# Claude auth: subscription token from 'claude setup-token' run locally by the owner (D72)."
    echo "CLAUDE_CODE_OAUTH_TOKEN="
    echo "# Alternative (pay-per-token API key); set only one of the two:"
    echo "# ANTHROPIC_API_KEY="
    echo "GH_TOKEN="
  } > "$ENV_FILE"
fi
chown root:root "$ENV_FILE"; chmod 600 "$ENV_FILE"

install -m 644 "$APP/app/oncall/host/fitwise-oncall.service" /etc/systemd/system/fitwise-oncall.service
systemctl daemon-reload
systemctl enable --now fitwise-oncall.service >/dev/null
systemctl restart fitwise-oncall.service
echo "fitwise-oncall installed; edit $ENV_FILE (CLAUDE_CODE_OAUTH_TOKEN, GH_TOKEN, ONCALL_AGENT_ENABLED=1) then: systemctl restart fitwise-oncall"
