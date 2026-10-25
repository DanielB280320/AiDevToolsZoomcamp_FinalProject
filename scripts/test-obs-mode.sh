#!/usr/bin/env bash
# Tests the host-side observability switch (#67): lib.sh obs_mode / compose_release file selection and
# the shape of the dev/prod overlays. No network; docker is a stub that prints its arguments.
set -uo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
root="$here/.."
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
export APP_DIR="$tmp"
mkdir -p "$tmp/stub" "$tmp/releases/$(printf 'a%.0s' {1..40})"
printf '#!/usr/bin/env bash\necho "docker $*"\n' > "$tmp/stub/docker"; chmod +x "$tmp/stub/docker"
export PATH="$tmp/stub:$PATH"
# shellcheck disable=SC1091
. "$root/deploy/lib.sh"
fails=0
ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; fails=$((fails+1)); }
mode_is() { # name, want, env content
  printf '%b' "$3" > "$ENV_FILE"
  got="$(obs_mode 2>/dev/null)"
  if [ "$got" = "$2" ]; then ok "$1"; else bad "$1 (got '$got')"; fi
}
mode_is "prod: full"                       full    "OBS_MODE=full\nGRAFANA_ADMIN_PASSWORD=x\n"
mode_is "dev: forward"                     forward "OBS_MODE=forward\nGRAFANA_ADMIN_PASSWORD=x\nOTLP_UPSTREAM_ENDPOINT=1.2.3.4:4317\n"
mode_is "forward without upstream: off"    ""      "OBS_MODE=forward\nGRAFANA_ADMIN_PASSWORD=x\n"
mode_is "full without password: off"       ""      "OBS_MODE=full\n"
mode_is "empty password: off"              ""      "OBS_MODE=full\nGRAFANA_ADMIN_PASSWORD=\n"
mode_is "unknown mode: off"                ""      "OBS_MODE=both\nGRAFANA_ADMIN_PASSWORD=x\n"
mode_is "unset: off"                       ""      "APP_ENV=prod\n"
out="$(obs_mode 2>&1)"; case "$out" in *x*) bad "obs_mode printed a secret";; *) ok "obs_mode prints no env values";; esac

sha="$(printf 'a%.0s' {1..40})"; rel="$tmp/releases/$sha"
touch "$rel/release.env" "$rel/compose.yaml" "$rel/compose.deploy.yaml"
printf 'OBS_MODE=full\nGRAFANA_ADMIN_PASSWORD=x\n' > "$ENV_FILE"
out="$(compose_release "$sha" ps)"
case "$out" in *compose.observability*) bad "obs files used although the release has none";; *) ok "release without obs files runs without them";; esac
touch "$rel/compose.observability.yaml" "$rel/compose.obs-full.yaml"
out="$(compose_release "$sha" ps)"
case "$out" in *"-f compose.observability.yaml -f compose.obs-full.yaml"*) ok "full overlay layered";; *) bad "full overlay missing: $out";; esac
printf 'APP_ENV=prod\n' > "$ENV_FILE"
out="$(compose_release "$sha" ps)"
case "$out" in *compose.observability*) bad "obs files used while off";; *) ok "off: app files only";; esac

# Overlay shape: prod publishes OTLP gRPC + reads config from OBS_CONFIG_DIR; dev only the collector.
grep -q 'OTLP_GRPC_PORT:-4317}:4317' "$root/deploy/compose.obs-full.yaml" && ok "prod overlay publishes OTLP gRPC" || bad "prod overlay does not publish 4317"
grep -q 'OTLP_GRPC_BIND:-127.0.0.1' "$root/deploy/compose.obs-full.yaml" && ok "OTLP binds to loopback unless the host env says otherwise" || bad "OTLP default bind is not loopback"
! grep -q 'prometheus\|grafana\|loki\|tempo' "$root/deploy/compose.obs-forward.yaml" && ok "dev overlay touches only the collector" || bad "dev overlay mentions a storage service"
! grep -Eq 'PASSWORD: *[A-Za-z0-9]' "$root"/deploy/compose.obs-*.yaml && ok "no literal passwords in the overlays" || bad "literal password in an overlay"
[ "$fails" = 0 ] && echo "all observability host tests passed" || { echo "$fails failed"; exit 1; }
