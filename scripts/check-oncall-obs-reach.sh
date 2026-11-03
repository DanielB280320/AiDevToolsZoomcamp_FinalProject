#!/usr/bin/env bash
# Guards that the on-call responder can reach Prometheus, Loki and Tempo on the prod host (issue #20,
# drill S1 attempt 1: the responder defaults to 127.0.0.1:9090/3100/3200 but nothing published them,
# so evidence capture failed with URLError and the agent had no metrics, logs or traces).
#   scripts/check-oncall-obs-reach.sh
# Renders the prod layering (compose.yaml + deploy/compose.deploy.yaml + compose.observability.yaml +
# compose.obs-full.yaml, as deploy/lib.sh compose_release does) with `docker compose config` and
# asserts, for each default URL in oncall/responder/config.py, that the port is published on
# 127.0.0.1 and nowhere else. Also: the dev (forward) layering publishes none of the three.
# Needs docker compose and jq; starts nothing.
set -euo pipefail
cd "$(dirname "$0")/.."
fails=0
ck() { if [ "$2" = "$3" ]; then echo "ok   $1"; else echo "FAIL $1 (want '$3', got '$2')"; fails=$((fails+1)); fi; }

# Defaults the responder uses, read from the code so that changing them there breaks this check.
declare -A svc=([ONCALL_PROMETHEUS_URL]=prometheus [ONCALL_LOKI_URL]=loki [ONCALL_TEMPO_URL]=tempo)
export OBS_CONFIG_DIR=/nonexistent GRAFANA_ADMIN_PASSWORD=x OTLP_UPSTREAM_ENDPOINT=prod:4317
export BACKEND_IMAGE=b@sha256:0 FRONTEND_IMAGE=f@sha256:0
export POSTGRES_PASSWORD=x JWT_SECRET=x USER_HASH_SALT=x   # placeholders: only rendered, never run

full="$(docker compose -f compose.yaml -f deploy/compose.deploy.yaml -f compose.observability.yaml \
  -f deploy/compose.obs-full.yaml config --format json)"
fwd="$(docker compose -f compose.yaml -f deploy/compose.deploy.yaml \
  -f compose.observability.yaml -f deploy/compose.obs-forward.yaml config --format json)"

for var in "${!svc[@]}"; do
  s="${svc[$var]}"
  url="$(sed -n "s|.*\"$var\", \"\(http://[^\"]*\)\".*|\1|p" oncall/responder/config.py)"
  case "$url" in http://127.0.0.1:[0-9]*) ;; *) echo "FAIL cannot read the $var default from config.py ('$url')"; fails=$((fails+1)); continue;; esac
  port="${url##*:}"
  pub="$(jq -r --arg s "$s" '.services[$s].ports // [] | map("\(.host_ip // "ANY"):\(.published)->\(.target)") | join(" ")' <<<"$full")"
  ck "prod: $s published only as 127.0.0.1:$port->$port" "$pub" "127.0.0.1:$port->$port"
  devpub="$(jq -r --arg s "$s" '.services[$s].ports // [] | length' <<<"$fwd")"
  ck "dev (forward): $s publishes nothing" "$devpub" "0"
done
[ "$fails" -eq 0 ] || { echo "$fails check(s) failed"; exit 1; }
echo "check-oncall-obs-reach: OK"
