#!/usr/bin/env python3
"""Test traffic for demo scenario S2 (spec §15.3, issue #33): repeated finishes of a session
that contains a bodyweight exercise.

    DEMO_S2_BASE_URL=https://<host> DEMO_S2_EMAIL=... DEMO_S2_PASSWORD=... \\
        scripts/demo-s2-traffic.py [--signup] [--requests 30] [--interval 4] [--expect errors|ok]

Why this generates the alert: `POST /sessions/{id}/finish` runs the progression engine. With the
flag `progression_engine=v2` (demo-only fault, backend/app/engines/progression_v2.py) it raises
for bodyweight exercises and the endpoint answers 500; with `v1` the same request answers 200.
Finishing again inside the edit window is allowed (F10.3: it recomputes and replaces the pending
suggestions), so ONE session finished N times gives N requests on the KeyJourneyErrors route.

Environment (nothing secret in git, in arguments or in the output):
  DEMO_S2_BASE_URL    base URL of the frontend/nginx, e.g. http://localhost:18433 (required)
  DEMO_S2_EMAIL       dedicated test account, e.g. demo-s2@example.test (required)
  DEMO_S2_PASSWORD    its password, at least 10 characters (required)
  DEMO_S2_TIMEZONE    IANA zone of the account, default UTC
  DEMO_S2_ALLOW_REMOTE=1   required when the host is not localhost/127.0.0.1 (a guard against
                      pointing the script at prod by accident; the dev host needs it too)

`--signup` creates the account (fake data only: a 1990 birth date, fake body metrics, the
bodyweight_only plan) when the sign-in is refused; without it the account must exist.
`--expect errors` exits 1 unless every finish answered 5xx; `--expect ok` exits 1 unless every
finish answered 200 (use it to check the dev or local stack before and after the flag change).

Output: the target host name, step names, HTTP status codes and a status count. Never the
account, request or response bodies, ids or exercise names (CLAUDE.md rule 6). Standard library only.
"""

import argparse
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def die(message: str, code: int = 2) -> "None":
    print(f"demo-s2-traffic: {message}", file=sys.stderr)
    raise SystemExit(code)


class Client:
    def __init__(self, base: str) -> None:
        self.api = base.rstrip("/") + "/api/v1"
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, body: object = None) -> tuple[int, object]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(
            self.api + path, data=data, method=method, headers={"Content-Type": "application/json"}
        )
        try:
            with self.opener.open(req, timeout=30) as response:
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        except urllib.error.URLError:
            return 0, None  # connection failure; the reason is not printed
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, None


def step(client: Client, name: str, method: str, path: str, body: object, ok: set[int]) -> object:
    status, payload = client.call(method, path, body)
    print(f"   {name}: HTTP {status}", flush=True)
    if status not in ok:
        die(f"{name} failed (HTTP {status})", 1)
    return payload


def sign_up_and_onboard(client: Client, email: str, password: str, tz: str) -> None:
    me = step(client, "sign up (fake athlete)", "POST", "/auth/signup", {
        "email": email, "password": password, "display_name": "Demo S2", "role": "athlete",
        "birth_date": "1990-01-01", "units": "metric", "timezone": tz, "accept_disclaimer": True,
    }, {201})
    today = datetime.now(ZoneInfo(tz)).date()
    # Six training days, resting on tomorrow: the plan starts today, so today has a session.
    rest = WEEKDAYS[(today.weekday() + 1) % 7]
    step(client, "onboarding (bodyweight_only plan)", "POST", f"/athletes/{me['id']}/onboarding", {  # type: ignore[index]
        "profile": {
            "sex": "female", "height_cm": 165, "lifestyle": "lightly_active", "goal": "maintenance",
            "experience": "beginner", "days_per_week": 6,
            "preferred_days": [d for d in WEEKDAYS if d != rest], "session_minutes": 45,
            "equipment": "bodyweight_only", "avoided_exercise_ids": [], "diet": "omnivore",
            "allergies": [], "meals_per_day": 3,
        },
        "body_metric": {"weight_kg": 65, "body_fat_method": "skip"},
    }, {201})


def find_session(client: Client, athlete_id: str, tz: str) -> dict:
    today = datetime.now(ZoneInfo(tz)).date()
    for back in range(7):
        day = (today - timedelta(days=back)).isoformat()
        view = step(client, f"day view ({back} d ago)", "GET", f"/athletes/{athlete_id}/days/{day}", None, {200})
        session = view.get("session") if isinstance(view, dict) else None  # type: ignore[union-attr]
        if session and any(e["exercise"]["type"] == "bodyweight" for e in session["exercises"]):
            return session
    die("no session with a bodyweight exercise in the last 7 days; use --signup on a fresh account", 1)
    raise AssertionError  # unreachable


def main() -> int:
    parser = argparse.ArgumentParser(description="Failing-finish test traffic for demo scenario S2.")
    parser.add_argument("--signup", action="store_true", help="create the test account if sign-in is refused")
    parser.add_argument("--requests", type=int, default=30, help="number of finish requests (default 30; the alert needs >= 20 in 5 min)")
    parser.add_argument("--interval", type=float, default=4.0, help="seconds between finish requests (default 4)")
    parser.add_argument("--expect", choices=["errors", "ok"], help="exit 1 unless all finishes failed (errors) / succeeded (ok)")
    args = parser.parse_args()
    if args.requests < 1 or args.interval < 0:
        die("--requests must be >= 1 and --interval >= 0")

    base = os.environ.get("DEMO_S2_BASE_URL", "")
    email = os.environ.get("DEMO_S2_EMAIL", "")
    password = os.environ.get("DEMO_S2_PASSWORD", "")
    tz = os.environ.get("DEMO_S2_TIMEZONE", "UTC")
    if not (base and email and password):
        die("set DEMO_S2_BASE_URL, DEMO_S2_EMAIL and DEMO_S2_PASSWORD")
    if len(password) < 10:
        die("DEMO_S2_PASSWORD must have at least 10 characters")
    try:
        ZoneInfo(tz)
    except Exception:
        die("DEMO_S2_TIMEZONE is not an IANA zone")
    host = urllib.parse.urlparse(base).hostname or ""
    if host not in LOCAL_HOSTS and os.environ.get("DEMO_S2_ALLOW_REMOTE") != "1":
        die(f"{host or 'the target'} is not local; set DEMO_S2_ALLOW_REMOTE=1 to confirm you mean it")
    print(f"demo-s2-traffic: target host {host}, {args.requests} finishes every {args.interval:g} s")

    client = Client(base)
    status, me = client.call("POST", "/auth/login", {"email": email, "password": password})
    print(f"   sign in: HTTP {status}", flush=True)
    if status != 200:
        if status == 401 and args.signup:
            client = Client(base)
            sign_up_and_onboard(client, email, password, tz)
            status, me = client.call("GET", "/me")
            if status != 200:
                die(f"reading the new account failed (HTTP {status})", 1)
        else:
            die(f"sign-in failed (HTTP {status}); use --signup for a new account", 1)
    athlete_id = me["id"]  # type: ignore[index]
    tz = me.get("timezone") or tz  # type: ignore[union-attr]

    session = find_session(client, athlete_id, tz)
    sid = session["id"]
    bodyweight = [e for e in session["exercises"] if e["exercise"]["type"] == "bodyweight"]
    # Log every planned exercise as planned (finishing needs logs). A session that is already done
    # keeps its sets: editing them re-runs the engine, so under v2 that call would fail too.
    for exercise in [] if session["status"] == "done" else session["exercises"]:
        if exercise["planned_exercise_id"] is None:
            continue
        for set_no in range(1, len(exercise["sets"]) + 1):
            # A strength set without a planned weight cannot be logged as planned (D96).
            target = exercise["sets"][set_no - 1]
            if exercise["exercise"]["type"] == "strength" and target.get("target_weight_kg") is None:
                values: dict[str, object] = {"reps": target.get("target_reps") or 8, "weight_kg": 20}
            else:
                values = {"as_planned": True}
            status, _ = client.call("POST", f"/sessions/{sid}/sets", {
                "exercise_id": exercise["exercise"]["id"],
                "planned_exercise_id": exercise["planned_exercise_id"],
                "set_no": set_no, **values,
            })
            if status not in (200, 201):
                die(f"logging a set failed (HTTP {status})", 1)
    print(f"   logged the planned sets ({len(session['exercises'])} exercises, {len(bodyweight)} bodyweight)")

    counts: Counter[int] = Counter()
    for i in range(args.requests):
        status, _ = client.call("POST", f"/sessions/{sid}/finish")
        counts[status] += 1
        print(f"   finish {i + 1}/{args.requests}: HTTP {status}", flush=True)
        if i + 1 < args.requests:
            time.sleep(args.interval)

    errors = sum(n for s, n in counts.items() if s >= 500 or s == 0)
    print("demo-s2-traffic: " + ", ".join(f"HTTP {s} x{n}" for s, n in sorted(counts.items())) + f" ({errors} errors)")
    if args.expect == "errors" and errors != args.requests:
        print("demo-s2-traffic: expected every finish to fail (is progression_engine v2?)", file=sys.stderr)
        return 1
    if args.expect == "ok" and counts[200] != args.requests:
        print("demo-s2-traffic: expected every finish to succeed (is progression_engine v1?)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
