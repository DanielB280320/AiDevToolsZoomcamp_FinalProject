"""Drives the alerts fire-and-resolve test (#97). Run through `run.sh` (needs the stack up).

Stdlib only. Steps, for each of KeyJourneyErrors and KeyJourneyLatency:

1. Healthy traffic on the logging routes (POST /sessions/{id}/sets and /finish; an unknown
   session id answers 403, which is a normal client error and not a failure).
2. Inject the fault (errors: break the database login; latency: oncall/ops/flag.sh
   fault_injection_latency_ms 1500) while traffic continues, and wait until the stub webhook
   receiver has captured a `firing` payload for the alert.
3. Remove the fault (start the database; flag back to 0), keep sending healthy traffic and wait
   for the `resolved` payload.

Every payload the stub receives (basic auth checked, like the on-call responder) is validated
(`check_payload`) and written with its arrival time to `out/webhook-payloads.jsonl`; the
timeline and a summary go to `out/timeline.md`. Exit status 0 only when all four payloads
arrived and passed the checks.
"""

import argparse
import base64
import datetime as dt
import http.client
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROUTES = {
    "sets": "/api/v1/sessions/{}/sets",
    "finish": "/api/v1/sessions/{}/finish",
}
ROUTE_TEMPLATES = {
    "sets": "/api/v1/sessions/{session_id}/sets",
    "finish": "/api/v1/sessions/{session_id}/finish",
}
RUNBOOKS = {
    "KeyJourneyErrors": "docs/runbooks/key-journey-errors.md",
    "KeyJourneyLatency": "docs/runbooks/key-journey-latency.md",
}
WINDOWS = {
    "KeyJourneyErrors": "5 minutes",
    "KeyJourneyLatency": "10 minutes",
}
LATENCY_FAULT_MS = 1500
WEBHOOK_USER = "grafana"


def now() -> str:
    return dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_time(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def check_payload(
    payload: dict[str, Any],
    alertname: str,
    status: str,
    not_before: dt.datetime | None = None,
) -> list[str]:
    """Problems with a Grafana webhook payload for `alertname` in `status` (empty = fine).

    With `not_before` (the moment the fault was injected / removed, minus one evaluation
    interval), `startsAt` (firing) or `endsAt` (resolved) must not be earlier: the alert has to be
    caused by this run, not be left over from earlier traffic.
    """
    problems: list[str] = []
    if payload.get("status") != status:
        problems.append(f"status is {payload.get('status')!r}, expected {status!r}")
    alerts = [a for a in payload.get("alerts", []) if a.get("labels", {}).get("alertname") == alertname]
    if not alerts:
        return [*problems, f"no alert named {alertname}"]
    alert = alerts[0]
    labels, notes = alert.get("labels", {}), alert.get("annotations", {})
    if alert.get("status") != status:
        problems.append(f"alert status is {alert.get('status')!r}, expected {status!r}")
    if labels.get("env") != "prod":
        problems.append(f"label env is {labels.get('env')!r}, expected 'prod'")
    if labels.get("route") not in ROUTE_TEMPLATES.values():
        problems.append(f"label route is {labels.get('route')!r}, not a logging route")
    if notes.get("route") != labels.get("route"):
        problems.append("annotation route is missing or differs from the label")
    if notes.get("window") is None or WINDOWS[alertname] not in notes["window"]:
        problems.append(f"annotation window is {notes.get('window')!r}")
    if "d/fitwise-key-journey/" not in notes.get("dashboard_url", ""):
        problems.append(f"annotation dashboard_url is {notes.get('dashboard_url')!r}")
    if not notes.get("runbook_url", "").endswith(RUNBOOKS[alertname]):
        problems.append(f"annotation runbook_url is {notes.get('runbook_url')!r}")
    if not_before is not None:
        stamp = alert.get("startsAt" if status == "firing" else "endsAt", "")
        if not stamp or parse_time(stamp) < not_before:
            problems.append(f"alert time {stamp!r} is earlier than {not_before:%H:%M:%S}")
    if not alert.get("startsAt", "").strip() or (status == "resolved" and alert.get("endsAt", "").startswith("0001")):
        problems.append("startsAt/endsAt missing")
    return problems


class Stub:
    """Webhook receiver that records every authenticated POST /alerts."""

    def __init__(self, port: int, password: str, out: Path) -> None:
        self.received: list[dict[str, Any]] = []
        self.lock = threading.Lock()
        self.out = out
        expected = "Basic " + base64.b64encode(f"{WEBHOOK_USER}:{password}".encode()).decode()
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                if self.path != "/alerts" or self.headers.get("Authorization") != expected:
                    self.send_response(401)
                    self.end_headers()
                    return
                stub.record(json.loads(body))
                self.send_response(200)
                self.end_headers()

            def log_message(self, *_: Any) -> None:
                return

        self.server = ThreadingHTTPServer(("0.0.0.0", port), Handler)  # noqa: S104 - Docker host
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def record(self, payload: dict[str, Any]) -> None:
        entry = {"received_at": now(), "payload": payload}
        with self.lock:
            self.received.append(entry)
            with self.out.open("a") as handle:
                handle.write(json.dumps(entry) + "\n")

    def count(self) -> int:
        with self.lock:
            return len(self.received)

    def wait_for(
        self, alertname: str, status: str, timeout: float, since: int = 0
    ) -> dict[str, Any] | None:
        """First payload for `alertname` in `status` among those received after the first `since`."""
        deadline = time.monotonic() + timeout
        seen = since
        while time.monotonic() < deadline:
            with self.lock:
                entries = list(self.received)
            for entry in entries[seen:]:
                payload = entry["payload"]
                names = {a.get("labels", {}).get("alertname") for a in payload.get("alerts", [])}
                if alertname in names and payload.get("status") == status:
                    return entry
            seen = len(entries)
            time.sleep(5)
        return None


class Traffic:
    """Background load on the logging routes; `workers` threads, one request per `pause` s each."""

    def __init__(self, app: str, cookie: str, workers: int, pause: float) -> None:
        self.app, self.cookie, self.pause = app, cookie, pause
        self.stop = threading.Event()
        self.counts: dict[int, int] = {}
        self.lock = threading.Lock()
        self.threads = [threading.Thread(target=self.loop, args=(i,), daemon=True) for i in range(workers)]

    def start(self) -> None:
        for thread in self.threads:
            thread.start()

    def finish(self) -> None:
        self.stop.set()
        for thread in self.threads:
            thread.join(timeout=30)

    def loop(self, index: int) -> None:
        kinds = list(ROUTES)
        n = index
        while not self.stop.is_set():
            kind = kinds[n % len(kinds)]
            n += 1
            body = {"exercise_id": str(uuid.uuid4()), "set_no": 1, "reps": 5} if kind == "sets" else {}
            code = request(self.app + ROUTES[kind].format(uuid.uuid4()), body, self.cookie)
            with self.lock:
                self.counts[code] = self.counts.get(code, 0) + 1
            self.stop.wait(self.pause)


def request(url: str, body: dict[str, Any], cookie: str = "") -> int:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "Cookie": cookie}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return int(response.status)
    except urllib.error.HTTPError as err:
        return err.code
    except (urllib.error.URLError, http.client.HTTPException, OSError):
        return 0


def sign_in(app: str) -> str:
    """Sign up a throwaway athlete and return its session cookie."""
    email = f"alerttest-{uuid.uuid4().hex[:12]}@example.test"
    password = uuid.uuid4().hex
    signup = {
        "email": email, "password": password, "display_name": "Alert Test", "role": "athlete",
        "birth_date": "1995-04-12", "units": "metric", "timezone": "UTC", "accept_disclaimer": True,
    }
    req = urllib.request.Request(
        app + "/api/v1/auth/signup", data=json.dumps(signup).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        cookies = response.headers.get_all("Set-Cookie") or []
    if not cookies:
        raise SystemExit("sign-up returned no session cookie")
    return cookies[0].split(";")[0]


def grafana_get(grafana: str, path: str, password: str) -> Any:
    token = base64.b64encode(f"admin:{password}".encode()).decode()
    req = urllib.request.Request(grafana + path, headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def run(cmd: list[str], stdin: str | None = None) -> None:
    subprocess.run(cmd, check=True, input=stdin, text=True)


def firing_rules(grafana: str, password: str) -> list[str]:
    """Names of the rules that are not in the normal state (precondition for a clean phase)."""
    data = grafana_get(grafana, "/api/prometheus/grafana/api/v1/rules", password)
    return [
        rule["name"]
        for group in data["data"]["groups"]
        for rule in group["rules"]
        if rule.get("state") not in ("inactive", "normal")
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--app", required=True)
    parser.add_argument("--grafana", required=True)
    parser.add_argument("--stub-port", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--only", choices=["errors", "latency"], help="run one alert only (default: both)"
    )
    parser.add_argument("--timeout", type=int, default=25 * 60, help="seconds to wait per firing/resolved")
    args = parser.parse_args()

    compose = os.environ["COMPOSE"].split()
    args.out.mkdir(parents=True, exist_ok=True)
    payloads = args.out / "webhook-payloads.jsonl"
    payloads.write_text("")
    timeline: list[str] = []

    def log(message: str) -> None:
        line = f"{now()}  {message}"
        timeline.append(line)
        print(line, flush=True)
        (args.out / "timeline.md").write_text("# Alert test timeline (UTC)\n\n" + "\n".join(f"- {t}" for t in timeline) + "\n")

    stub = Stub(args.stub_port, os.environ["ONCALL_WEBHOOK_PASSWORD"], payloads)
    graf_password = os.environ["GRAFANA_ADMIN_PASSWORD"]
    rules = {r["title"]: r for r in grafana_get(args.grafana, "/api/v1/provisioning/alert-rules", graf_password)}
    for name in WINDOWS:
        if name not in rules:
            log(f"FAIL: rule {name} is not provisioned")
            return 1
    log(f"rules provisioned: {sorted(rules)}; stub receiver on :{args.stub_port}")

    cookie = sign_in(args.app)
    failures: list[str] = []

    def phase(
        alertname: str,
        inject: tuple[list[str], str | None],
        remove: tuple[list[str], str | None],
        workers: int,
        pause: float,
    ) -> None:
        # A clean start: no rule may still be firing from an earlier phase or run.
        deadline = time.monotonic() + args.timeout
        while (busy := firing_rules(args.grafana, graf_password)) and time.monotonic() < deadline:
            log(f"[{alertname}] waiting for {busy} to return to normal")
            time.sleep(60)
        traffic = Traffic(args.app, cookie, workers, pause)
        traffic.start()
        removed = False
        try:
            log(f"[{alertname}] healthy traffic for 90 s")
            time.sleep(90)
            before = stub.count()
            injected_at = dt.datetime.now(dt.UTC)
            run(inject[0], inject[1])
            log(f"[{alertname}] fault injected: {' '.join(inject[0][-3:])}")
            fired = stub.wait_for(alertname, "firing", args.timeout, before)
            if fired is None:
                failures.append(f"{alertname}: no firing payload in {args.timeout}s")
                log(f"[{alertname}] FAIL no firing payload; traffic so far {traffic.counts}")
            else:
                problems = check_payload(
                    fired["payload"], alertname, "firing", injected_at - dt.timedelta(seconds=60)
                )
                failures.extend([f"{alertname} firing: {p}" for p in problems])
                log(f"[{alertname}] firing payload received at {fired['received_at']} problems={problems}")
            removed_at = stub.count()
            cleared_at = dt.datetime.now(dt.UTC)
            run(remove[0], remove[1])
            removed = True
            log(f"[{alertname}] fault removed: {' '.join(remove[0][-3:])}")
            resolved = stub.wait_for(alertname, "resolved", args.timeout, removed_at)
            if resolved is None:
                failures.append(f"{alertname}: no resolved payload in {args.timeout}s")
                log(f"[{alertname}] FAIL no resolved payload; traffic so far {traffic.counts}")
            else:
                problems = check_payload(
                    resolved["payload"], alertname, "resolved", cleared_at - dt.timedelta(seconds=60)
                )
                failures.extend([f"{alertname} resolved: {p}" for p in problems])
                log(f"[{alertname}] resolved payload received at {resolved['received_at']} problems={problems}")
        finally:
            if not removed:
                run(remove[0], remove[1])  # never leave the stack faulted
            traffic.finish()
            log(f"[{alertname}] traffic status counts (0 = connection error): {dict(sorted(traffic.counts.items()))}")

    # Errors: the fault is a database login failure (the role's password is changed and open
    # connections are cut, so the logging routes answer 500 at once). A stopped or paused database
    # also gives 500s, but slowly (connect timeouts), which trips KeyJourneyLatency as well.
    db_user = os.environ.get("POSTGRES_USER", "fitwise")
    db_pass = os.environ["POSTGRES_PASSWORD"]
    psql = [*compose, "exec", "-T", "db", "psql", "-q", "-v", "ON_ERROR_STOP=1", "-U", db_user, "-d", "postgres"]
    cut = f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = '{db_user}' AND pid <> pg_backend_pid();\n"
    if args.only in (None, "errors"):
        phase(
            "KeyJourneyErrors",
            (psql, f"ALTER ROLE {db_user} PASSWORD 'wrong-on-purpose';\n{cut}"),
            (psql, f"ALTER ROLE {db_user} PASSWORD '{db_pass}';\n"),
            workers=2,
            pause=1.0,
        )
    # Latency: the fault_injection_latency_ms flag (#15), set through the on-call tool.
    flag = str(Path(__file__).resolve().parents[2] / "oncall/ops/flag.sh")
    os.environ["FLAG_ACTOR"] = "alert-test"
    if args.only in (None, "latency"):
        phase(
            "KeyJourneyLatency",
            ([flag, "fault_injection_latency_ms", str(LATENCY_FAULT_MS)], None),
            ([flag, "fault_injection_latency_ms", "0"], None),
            workers=4,
            pause=0.5,
        )

    log("RESULT: " + ("PASS" if not failures else "FAIL " + "; ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
