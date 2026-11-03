#!/usr/bin/env bash
# Tests the client-IP and scheme handling of the frontend nginx behind CloudFront (#220, ADR 0012).
# Runs the real template in the nginx image against a stub backend that echoes the headers it got.
# Needs docker and the nginx image (pulled if missing); no other network access.
set -uo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
img="${NGINX_IMAGE:-nginxinc/nginx-unprivileged:1.30-alpine}"
net="fw-nginx-test-$$"
fails=0
ok() { echo "ok   $1"; }; bad() { echo "FAIL $1"; fails=$((fails+1)); }
tmp="$(mktemp -d)"; chmod 755 "$tmp"
cleanup() {
  docker rm -f "$net-stub" "$net-fe" "$net-fe2" >/dev/null 2>&1
  docker network rm "$net" >/dev/null 2>&1
  rm -rf "$tmp"
}
trap cleanup EXIT
cat > "$tmp/stub.conf" <<'CONF'
server { listen 8000; location / { default_type text/plain;
  return 200 "xff=$http_x_forwarded_for|proto=$http_x_forwarded_proto|real=$http_x_real_ip"; } }
CONF
chmod 644 "$tmp/stub.conf"
docker network create "$net" >/dev/null || exit 1
docker run -d --name "$net-stub" --network "$net" -v "$tmp/stub.conf:/etc/nginx/conf.d/default.conf:ro" "$img" >/dev/null || exit 1

fe() {  # fe <name> <trusted> <proto>
  docker run -d --name "$1" --network "$net" \
    -e NGINX_ENVSUBST_FILTER='^(BACKEND_|NGINX_)' -e BACKEND_UPSTREAM="$net-stub:8000" \
    -e NGINX_RESOLVER=127.0.0.11 -e NGINX_TRUSTED_PROXIES="$2" -e NGINX_FORWARDED_PROTO="$3" \
    -v "$root/frontend/nginx/default.conf.template:/etc/nginx/templates/default.conf.template:ro" \
    "$img" >/dev/null
}
req() {  # req <container> <X-Forwarded-For value or empty>
  local args=(); [ -n "$2" ] && args=(--header "X-Forwarded-For: $2")
  local out
  for _ in $(seq 1 20); do
    out="$(docker exec "$1" wget -q -O - "${args[@]}" http://127.0.0.1:8080/api/v1/x 2>/dev/null)" && { echo "$out"; return; }
    sleep 0.5
  done
}

# Behind CloudFront: everything is trusted, the last X-Forwarded-For entry (CloudFront's) wins.
# (A request from the container's own loopback is a trusted peer here, like a CloudFront edge.)
fe "$net-fe" 0.0.0.0/0 https || exit 1
got="$(req "$net-fe" '6.6.6.6, 203.0.113.9')"
[ "$got" = "xff=203.0.113.9|proto=https|real=203.0.113.9" ] \
  && ok "trusted proxy: viewer IP is the last entry, spoofed entries dropped, proto https" \
  || bad "trusted: $got"

# Locally: nothing but loopback is trusted. Loopback IS the peer in this test, so use a
# non-loopback trusted list to make the peer untrusted.
fe "$net-fe2" 192.0.2.1 '$scheme' || exit 1
got="$(req "$net-fe2" '6.6.6.6')"
case "$got" in
  "xff=127.0.0.1|proto=http|real=127.0.0.1") ok "untrusted peer: client X-Forwarded-For ignored, proto http";;
  *) bad "untrusted: $got";;
esac
if docker logs "$net-fe" 2>&1 | grep -Eq '203\.0\.113\.9|6\.6\.6\.6'; then bad "client IP in nginx logs"; else ok "no client IP in nginx logs"; fi
if [ "$fails" -eq 0 ]; then echo "all passed"; else echo "$fails failed"; exit 1; fi
