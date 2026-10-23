#!/usr/bin/env bash
# Observability smoke check for `make up-obs` (#17; spec §14, §6.5, CLAUDE.md rule 6).
#
#   make check-obs        (needs `make up-obs` first)
#
# Through Grafana's datasource proxy (so the provisioned datasources are exercised too):
#   1. One request (GET /api/v1/me without a session -> 401 Problem; request_id = trace_id) is
#      visible as a metric with env, as an exemplar carrying its trace_id, as a trace in Tempo
#      and as log lines in Loki found by that trace_id.
#   2. Privacy: a sign-up and login carrying a unique marker in the email, password, display name,
#      query string and headers leave no trace of the marker in Loki, Tempo or Prometheus. Two lines
#      are written straight to the backend's stdout, bypassing the app logger: a non-JSON line and a
#      JSON line with forbidden fields (email, weight_kg, note). The collector must drop the first
#      and strip the forbidden fields from the second (its own allow-list, independent of the app).
#   3. Only the backend's logs reach Loki (no db/frontend/other projects), labels are only
#      service_name and env, and filtering by env works.
#   4. The three dashboards are provisioned, anonymous access is refused.
set -euo pipefail

COMPOSE=${COMPOSE:-docker compose -f compose.yaml -f compose.observability.yaml}
TIMEOUT=${CHECK_OBS_TIMEOUT:-240}

env_value() { # value from the environment, else .env, else $2
  local name=$1 default=${2:-}
  if [[ -n "${!name:-}" ]]; then printf '%s' "${!name}"; return; fi
  local v
  v=$(sed -n "s/^${name}=//p" .env 2>/dev/null | tail -1)
  printf '%s' "${v:-$default}"
}

app_port=$($COMPOSE port frontend 8080 2>/dev/null | sed 's/.*://' || true)
graf_port=$($COMPOSE port grafana 3000 2>/dev/null | sed 's/.*://' || true)
if [[ -z "$app_port" || -z "$graf_port" ]]; then
  echo "check-obs: the stack is not running; run 'make up-obs' first." >&2
  exit 1
fi
app="http://localhost:${app_port}"
graf="http://localhost:${graf_port}"
graf_user=$(env_value GRAFANA_ADMIN_USER admin)
graf_pass=$(env_value GRAFANA_ADMIN_PASSWORD)
app_env=$(env_value APP_ENV local)
# Basic-auth credentials via a curl config on stdin, so the password never shows in `ps`.
gcurl() { printf 'user = "%s:%s"\n' "$graf_user" "$graf_pass" | curl -sf --max-time 90 -K - "$@"; }

marker="OBSPRIV$(date +%s)$RANDOM"
fails=0
pass() { echo "  PASS  $*"; }
fail() { echo "  FAIL  $*"; fails=$((fails + 1)); }

# wait_for <description> <command...>: retry until the command succeeds or TIMEOUT expires.
wait_for() {
  local what=$1; shift
  local deadline=$((SECONDS + TIMEOUT))
  until "$@" >/dev/null 2>&1; do
    if ((SECONDS > deadline)); then fail "$what (no result after ${TIMEOUT}s)"; return 0; fi
    sleep 5
  done
  pass "$what"
}

prom() { gcurl -G "$graf/api/datasources/proxy/uid/prometheus/api/v1/$1" "${@:2}"; }
loki() { gcurl -G "$graf/api/datasources/proxy/uid/loki/loki/api/v1/$1" "${@:2}"; }
tempo() { gcurl "$graf/api/datasources/proxy/uid/tempo/api/v2/traces/$1"; }

start_ns=$(( $(date +%s) - 60 ))000000000
echo "check-obs: app ${app}, Grafana ${graf}, env ${app_env}, marker ${marker}"

# --- 1. one request, three signals --------------------------------------------------------------
echo "1. correlation (metric + exemplar -> trace -> logs)"
problem=$(curl -s --max-time 60 "${app}/api/v1/me" || true)
trace_id=$(sed -n 's/.*"request_id":"\([0-9a-f]\{32\}\)".*/\1/p' <<<"$problem")
if [[ -z "$trace_id" ]]; then
  fail "GET /api/v1/me returned no request_id: ${problem:0:200}"
  exit 1
fi
echo "  request GET /api/v1/me -> 401, trace_id ${trace_id}"

has_metric() {
  prom query --data-urlencode \
    "query=http_server_duration_seconds_count{env=\"${app_env}\",route=\"/api/v1/me\",method=\"GET\",status=\"401\"}" |
    grep -q '"result":\[{'
}
has_exemplar() {
  prom query_exemplars --data-urlencode \
    "query=http_server_duration_seconds_bucket{env=\"${app_env}\",route=\"/api/v1/me\",status=\"401\"}" \
    --data-urlencode "start=$(( $(date +%s) - 900 ))" --data-urlencode "end=$(( $(date +%s) + 60 ))" |
    grep -q "\"trace_id\":\"${trace_id}\""
}
has_trace() { tempo "$trace_id" | grep -q '"/api/v1/me'; }
has_logs() {
  loki query_range --data-urlencode \
    "query={service_name=\"fitwise-backend\", env=\"${app_env}\"} | trace_id=\"${trace_id}\"" \
    --data-urlencode "start=${start_ns}" | grep -q '"route":"/api/v1/me"'
}
wait_for "metric http_server_duration_seconds_count{env=\"${app_env}\",route=\"/api/v1/me\"} in Prometheus" has_metric
wait_for "exemplar with trace_id ${trace_id} on the histogram" has_exemplar
wait_for "trace ${trace_id} in Tempo" has_trace
wait_for "Loki log line with trace_id ${trace_id} (route=/api/v1/me)" has_logs
if tempo "$trace_id" | grep -q "\"key\":\"env\",\"value\":{\"stringValue\":\"${app_env}\"}"; then
  pass "trace carries resource attribute env=${app_env}"
else
  fail "trace has no env=${app_env} resource attribute"
fi

# --- 2. privacy -----------------------------------------------------------------------------------
echo "2. privacy (marker ${marker})"
email="${marker,,}@example.com"
password="${marker}Pw-0123456789"
signup=$(cat <<JSON
{"email":"${email}","password":"${password}","display_name":"${marker} Name","role":"athlete",
 "birth_date":"1990-01-01","units":"metric","timezone":"Europe/Berlin","accept_disclaimer":true}
JSON
)
hdrs=(-H "User-Agent: ${marker}agent" -H "Referer: http://ref.example/?q=${marker}ref"
  -H "X-Forwarded-For: 203.0.113.77" -H "Content-Type: application/json")
jar=$(mktemp)
trap 'rm -f "$jar"' EXIT
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "${hdrs[@]}" -c "$jar" \
  --data "$signup" "${app}/api/v1/auth/signup?email=${email}&note=${marker}note" || true)
echo "  POST /auth/signup -> ${code}"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "${hdrs[@]}" -c "$jar" -b "$jar" \
  --data "{\"email\":\"${email}\",\"password\":\"${password}\"}" "${app}/api/v1/auth/login" || true)
echo "  POST /auth/login  -> ${code}"
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 60 "${hdrs[@]}" -b "$jar" \
  "${app}/api/v1/me?q=${marker}food" || true)
echo "  GET  /me (signed in) -> ${code}"

# Bypass the app logger: write to the backend's stdout directly (what a stray print would do).
$COMPOSE exec -T backend sh -c "
  echo 'NONJSON ${marker}raw Traceback with ${email}' > /proc/1/fd/1
  echo '{\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%S.000Z)\",\"level\":\"info\",\"message\":\"injected ${marker}inject for ${email} Bearer abc.def\",\"logger\":\"app.check\",\"trace_id\":null,\"span_id\":null,\"env\":\"${app_env}\",\"service\":\"fitwise-backend\",\"version\":\"check\",\"route\":\"/check\",\"email\":\"${email}\",\"weight_kg\":81.5,\"note\":\"${marker}note\"}' > /proc/1/fd/1
" || fail "could not write to the backend's stdout"

injected() {
  loki query_range --data-urlencode \
    "query={service_name=\"fitwise-backend\"} |= \"injected ${marker}inject\"" \
    --data-urlencode "start=${start_ns}" | grep -q '"logger":"app.check"'
}
wait_for "injected JSON line reached Loki (message kept)" injected

# Wait for the sign-up's logs and traces to land (same pipeline, already proven above).
signed_up() {
  loki query_range --data-urlencode \
    "query={service_name=\"fitwise-backend\"} | route=\"/api/v1/me\" | status=\"200\" | user_hash=~\"[0-9a-f]{16}\"" \
    --data-urlencode "start=${start_ns}" | grep -q '"user_hash"'
}
wait_for "signed-in GET /api/v1/me access log carries user_hash (16 hex) in Loki" signed_up
sleep 20 # one more metric export + batch flush

all_logs=$(loki query_range --data-urlencode "query={service_name=~\".+\"}" \
  --data-urlencode "start=${start_ns}" --data-urlencode "limit=5000" || echo QUERY_FAILED)
[[ "$all_logs" == QUERY_FAILED ]] && fail "Loki bulk query failed"
injected_line=$(grep -o "\"injected ${marker}inject for \[email\] Bearer \[token\]\"" <<<"$all_logs" || true)
# The marker may appear only inside the one message we injected on purpose; its email and token are masked by the collector.
leaks=$(sed "s/injected ${marker}inject//g" <<<"$all_logs" | grep -o "${marker}[A-Za-z]*" | sort -u || true)
[[ -z "$leaks" ]] && pass "Loki: marker absent outside the injected message" || fail "Loki contains: ${leaks}"
grep -qi "${marker,,}@example.com\|@example.com" <<<"$all_logs" && fail "Loki contains an email" || pass "Loki: no email (the injected message had its email and Bearer token masked)"
grep -q '"weight_kg"\|"note"\|"email"' <<<"$all_logs" && fail "Loki kept a forbidden field (email/weight_kg/note)" ||
  pass "Loki: forbidden fields of the injected line were stripped by the collector"
grep -q 'NONJSON' <<<"$all_logs" && fail "Loki contains the non-JSON line" || pass "Loki: non-JSON line dropped"
grep -q '203\.0\.113\.77' <<<"$all_logs" && fail "Loki contains the forwarded client IP" || pass "Loki: no client IP"
[[ -n "$injected_line" ]] || fail "injected line not found in the bulk query"

traces=$( (gcurl -G "$graf/api/datasources/proxy/uid/tempo/api/search" \
  --data-urlencode 'q={ resource.service.name = "fitwise-backend" && span.http.route =~ "/api/v1/(auth/.*|me)" }' \
  --data-urlencode "start=$(( $(date +%s) - 900 ))" --data-urlencode "end=$(( $(date +%s) + 60 ))" \
  --data-urlencode "limit=20" || true) | grep -o '"traceID":"[0-9a-f]*"' | cut -d'"' -f4 | sort -u || true)
n=0; tleak=0
for t in $traces; do
  n=$((n + 1))
  body=$(tempo "$t" || true)
  if grep -q "${marker}\|@example.com\|203\.0\.113\.77\|Traceback" <<<"$body"; then tleak=$((tleak + 1)); fi
done
if ((n == 0)); then fail "Tempo: no auth/me traces found to inspect"
elif ((tleak == 0)); then pass "Tempo: ${n} auth/me traces, no marker, email, client IP or traceback"
else fail "Tempo: ${tleak}/${n} traces contain the marker, an email, the client IP or a traceback"; fi

series=$(prom series --data-urlencode 'match[]={__name__=~"http_server_duration_seconds_count|target_info|fitwise_.+"}' || echo QUERY_FAILED)
[[ "$series" == QUERY_FAILED ]] && fail "Prometheus series query failed"
grep -q "${marker}\|@example.com" <<<"$series" && fail "Prometheus labels contain the marker or an email" ||
  pass "Prometheus: no marker or email in any label ($(grep -o '"__name__"' <<<"$series" | wc -l) series)"
grep -q '"user_hash"\|"user_id"' <<<"$series" && fail "Prometheus has a user label" || pass "Prometheus: no user labels"

# --- 3. only backend logs, labels, env filter ----------------------------------------------------
echo "3. log sources, labels, env"
services=$(loki label/service_name/values --data-urlencode "start=${start_ns}" || true)
grep -q '"data":\["fitwise-backend"\]' <<<"$services" && pass "Loki service_name values: fitwise-backend only" ||
  fail "Loki service_name values: ${services}"
labels=$(loki labels --data-urlencode "start=${start_ns}" || true)
extra=$(grep -o '"[a-z_]*"' <<<"$labels" | tr -d '"' | grep -v -x -E 'status|data|success|service_name|env|__stream_shard__' || true)
[[ -z "$extra" ]] && pass "Loki index labels: service_name, env only" || fail "Loki unexpected labels: ${extra}"
other=$(prom query --data-urlencode "query=count(http_server_duration_seconds_count{env=\"no-such-env\"})" || true)
grep -q '"result":\[\]' <<<"$other" && pass "env filter: env=\"no-such-env\" selects nothing" || fail "env filter: ${other}"

# --- 4. Grafana provisioning and access ----------------------------------------------------------
echo "4. Grafana"
for uid in fitwise-key-journey fitwise-engines fitwise-service-health; do
  meta=$(gcurl "$graf/api/dashboards/uid/$uid" || true)
  if grep -q '"provisioned":true' <<<"$meta"; then pass "dashboard ${uid} provisioned from file"; else fail "dashboard ${uid} missing"; fi
done
ds=$(gcurl "$graf/api/datasources" || true)
for uid in prometheus loki tempo; do
  grep -q "\"uid\":\"${uid}\"" <<<"$ds" && pass "datasource ${uid}" || fail "datasource ${uid} missing"
done
anon=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$graf/api/dashboards/uid/fitwise-key-journey")
[[ "$anon" == "401" ]] && pass "anonymous access refused (401)" || fail "anonymous request returned ${anon}"

echo
if ((fails)); then echo "check-obs: ${fails} check(s) FAILED"; exit 1; fi
echo "check-obs: all checks passed"
