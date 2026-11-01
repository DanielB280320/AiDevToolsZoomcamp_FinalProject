"""Core write journeys against the running backend (issue #172; used by scripts/rollback-compat.sh).

Runs INSIDE the backend container (stdlib only) while the PREVIOUS release's image serves the
NEW schema, and performs one authenticated write per core journey:

  1. register + log in      POST /auth/signup, /auth/login
  2. onboarding             POST /athletes/{id}/onboarding (creates targets, plan, body metric)
  3. log a set              POST /sessions/{id}/sets
  4. check off a planned meal   POST /athletes/{id}/meal-logs  (status eaten)
  5. log an extra meal      POST /athletes/{id}/meal-logs  (status extra)

Any 5xx fails the run (a 5xx on a write means the old code no longer fits the schema). Any other
unexpected status also fails, so the guard cannot pass without writing. Only synthetic data is
used (a random example.com account); the script prints step names and HTTP status codes only,
never request or response bodies (CLAUDE.md rule 6).
"""
import http.cookiejar
import json
import secrets
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

BASE = "http://127.0.0.1:8000/api/v1"
TZ = "Europe/Madrid"
jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
failures = []


def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with opener.open(req, timeout=30) as r:
            status, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        return status, json.loads(raw) if raw else None
    except ValueError:
        return status, None


def step(name, method, path, body, ok):
    status, payload = call(method, path, body)
    verdict = "ok" if status in ok else ("SERVER ERROR" if status >= 500 else "UNEXPECTED")
    print(f"   {name}: HTTP {status} {verdict}", flush=True)
    if status not in ok:
        failures.append(f"{name}: HTTP {status}")
        raise SystemExit(finish())
    return payload


def finish():
    for f in failures:
        print(f"rollback-compat writes: FAILED: {f}", file=sys.stderr)
    return 1 if failures else 0


suffix = secrets.token_hex(6)
email = f"rollback-{suffix}@example.com"
password = f"rb-{secrets.token_hex(12)}"

me = step("register", "POST", "/auth/signup", {
    "email": email, "password": password, "display_name": "Rollback", "role": "athlete",
    "birth_date": "1995-04-12", "units": "metric", "timezone": TZ, "accept_disclaimer": True,
}, {201})
jar.clear()
step("log in", "POST", "/auth/login", {"email": email, "password": password}, {200})
aid = me["id"]

today = datetime.now(ZoneInfo(TZ)).date()

# Train six days a week, resting on the day after today, so the plan (which
# starts today) always has a session today whatever weekday CI runs on.
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
rest_day = WEEKDAYS[(today.weekday() + 1) % 7]
preferred_days = [d for d in WEEKDAYS if d != rest_day]

step("onboarding", "POST", f"/athletes/{aid}/onboarding", {
    "profile": {
        "sex": "female", "height_cm": 165, "lifestyle": "lightly_active", "goal": "cutting",
        "experience": "beginner", "days_per_week": 6,
        "preferred_days": preferred_days, "session_minutes": 45,
        "equipment": "full_gym", "avoided_exercise_ids": [], "diet": "omnivore", "allergies": [],
        "meals_per_day": 4,
    },
    "body_metric": {"weight_kg": 72.5, "body_fat_method": "entered", "body_fat_pct": 28},
}, {201})

# A session to log into: today, or the closest day in the last week that has one.
session = None
for back in range(0, 7):
    day = today - timedelta(days=back)
    view = step(f"day view {back}d ago", "GET", f"/athletes/{aid}/days/{day.isoformat()}", None, {200})
    if view.get("session"):
        session = view["session"]
        break
if session is None:
    failures.append("no training session found to log a set into")
    raise SystemExit(finish())
planned = session["exercises"][0]
step("log a set", "POST", f"/sessions/{session['id']}/sets", {
    "exercise_id": planned["exercise"]["id"],
    "planned_exercise_id": planned["planned_exercise_id"],
    "set_no": 1, "as_planned": True,
}, {200, 201})

view = step("day view (meals)", "GET", f"/athletes/{aid}/days/{today.isoformat()}", None, {200})
meal = view["meals"][0]["planned_meal"]
step("check off a planned meal", "POST", f"/athletes/{aid}/meal-logs",
     {"date": today.isoformat(), "planned_meal_id": meal["id"], "status": "eaten"}, {200, 201})

# Extra meal: the food of the planned meal's first item.
food_id = meal["items"][0]["food"]["id"]
step("log an extra meal", "POST", f"/athletes/{aid}/meal-logs", {
    "date": today.isoformat(), "planned_meal_id": None, "status": "extra", "slot": "snack",
    "items": [{"food_id": food_id, "grams": 30}],
}, {201})

print("   all core writes accepted (no 5xx)")
sys.exit(finish())
