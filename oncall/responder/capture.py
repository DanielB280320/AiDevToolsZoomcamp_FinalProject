"""Save the telemetry around an alert into the incident folder.

Files written (each independently, so one backend being down does not lose the others):

    prometheus.json    range-query results for the key-journey error and latency series
    loki.json          error log lines as Loki returned them
    tempo.json         IDs of failing traces in the alert window (IDs only)
    capture.json       per backend "ok" or the failure (exception type / HTTP status only)

Privacy (spec §6.5): the responder stores Loki and Tempo results exactly as returned and does not
filter them. That is safe because the backend only ever emits allow-listed log fields and span
attributes (backend/app/telemetry/privacy.py); nothing here adds data of its own beyond the alert.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from responder.config import Settings
from responder.log import log

ROUTE_REGEX = (
    "/api/v1/sessions/{session_id}/sets|/api/v1/sessions/{session_id}/finish"
    "|/api/v1/athletes/{athlete_id}/meal-logs"
)


def _selector_value(value: str) -> str:
    """Escape a label value for a PromQL / LogQL string literal."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def prometheus_queries(labels: dict[str, str]) -> dict[str, str]:
    env = _selector_value(labels.get("env", "prod"))
    route = labels.get("route")
    route_sel = f'route="{_selector_value(route)}"' if route else f'route=~"{ROUTE_REGEX}"'
    base = f'env="{env}", method="POST", {route_sel}'
    return {
        "error_requests_5xx": (
            "sum by (route) "
            f'(increase(http_server_duration_seconds_count{{{base}, status=~"5.."}}[5m]))'
        ),
        "all_requests": (
            f"sum by (route) (increase(http_server_duration_seconds_count{{{base}}}[5m]))"
        ),
        "p95_latency_seconds": (
            "histogram_quantile(0.95, sum by (route, le) "
            f"(increase(http_server_duration_seconds_bucket{{{base}}}[10m])))"
        ),
    }


def loki_query(labels: dict[str, str]) -> str:
    env = _selector_value(labels.get("env", "prod"))
    # The collector turns the JSON line into a message-only body and moves the level to the
    # severity, which Loki exposes as detected_level (same filter as the service-health dashboard).
    service = _selector_value(labels.get("service", "fitwise-backend"))
    return f'{{service_name="{service}", env="{env}"}} | detected_level=~"error|critical|fatal"'


def _get_json(url: str, params: dict[str, str], timeout: float) -> Any:
    full = f"{url}?{urllib.parse.urlencode(params)}"
    if not full.startswith(("http://", "https://")):
        raise ValueError("unsupported URL scheme")
    request = urllib.request.Request(full, method="GET")  # noqa: S310 (scheme checked above)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return json.loads(response.read())


def _parse_time(value: str, default: datetime) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return default
    if parsed.year < 2000:  # Grafana sends 0001-01-01T00:00:00Z for "no end yet"
        return default
    return parsed.astimezone(UTC)


def window(alert: dict[str, Any], before_s: int, after_s: int) -> tuple[datetime, datetime]:
    now = datetime.now(UTC)
    start = _parse_time(str(alert.get("startsAt", "")), now)
    end = _parse_time(str(alert.get("endsAt", "")), now)
    return start - timedelta(seconds=before_s), max(end, start) + timedelta(seconds=after_s)


def _write(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def capture_context(
    alert: dict[str, Any], incident_dir: Path, settings: Settings
) -> dict[str, str]:
    """Run all captures; returns the per backend outcome (also saved as capture.json)."""
    labels = {str(k): str(v) for k, v in (alert.get("labels") or {}).items()}
    start, end = window(alert, settings.window_before_s, settings.window_after_s)
    timeout = settings.capture_timeout_s

    def prometheus() -> object:
        out = {}
        for name, query in prometheus_queries(labels).items():
            out[name] = {
                "query": query,
                "result": _get_json(
                    f"{settings.prometheus_url}/api/v1/query_range",
                    {
                        "query": query,
                        "start": str(start.timestamp()),
                        "end": str(end.timestamp()),
                        "step": "30",
                    },
                    timeout,
                ),
            }
        return out

    def loki() -> object:
        query = loki_query(labels)
        return {
            "query": query,
            "result": _get_json(
                f"{settings.loki_url}/loki/api/v1/query_range",
                {
                    "query": query,
                    "start": str(int(start.timestamp() * 1e9)),
                    "end": str(int(end.timestamp() * 1e9)),
                    "limit": "200",
                    "direction": "backward",
                },
                timeout,
            ),
        }

    def tempo() -> object:
        body = _get_json(
            f"{settings.tempo_url}/api/search",
            {
                "q": "{ status = error }",
                "start": str(int(start.timestamp())),
                "end": str(int(end.timestamp())),
                "limit": "20",
            },
            timeout,
        )
        ids = [t["traceID"] for t in body.get("traces", []) if "traceID" in t]
        return {"trace_ids": ids}

    steps: dict[str, Callable[[], object]] = {
        "prometheus": prometheus,
        "loki": loki,
        "tempo": tempo,
    }
    outcome: dict[str, str] = {}
    for name, step in steps.items():
        try:
            _write(incident_dir / f"{name}.json", step())
            outcome[name] = "ok"
        except urllib.error.HTTPError as exc:
            outcome[name] = f"failed: HTTP {exc.code}"
            log("capture_failed", backend=name, status_code=exc.code)
        except Exception as exc:
            outcome[name] = f"failed: {type(exc).__name__}"
            log("capture_failed", backend=name, error_type=type(exc).__name__)
    _write(incident_dir / "capture.json", outcome)
    return outcome
