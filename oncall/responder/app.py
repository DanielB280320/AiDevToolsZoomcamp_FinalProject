"""FastAPI app: POST /alerts (Grafana unified-alerting webhook)."""

from __future__ import annotations

import base64
import binascii
import json
import secrets
from collections.abc import AsyncIterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from responder import log as logmod
from responder.capture import capture_context
from responder.config import Settings
from responder.launcher import launch
from responder.log import log
from responder.store import Incident, IncidentStore, InvalidFingerprintError, check_fingerprint


def is_test_notification(alert: dict[str, Any]) -> bool:
    """Grafana's "Test" button on a contact point sends alertname=TestAlert."""
    labels = alert.get("labels") or {}
    annotations = alert.get("annotations") or {}
    return labels.get("alertname") == "TestAlert" and annotations.get("summary") == (
        "Notification test"
    )


def _authorized(header: str | None, settings: Settings) -> bool:
    if not header or not header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:].strip(), validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        return False
    user, sep, password = decoded.partition(":")
    if not sep:
        return False
    # Evaluate both comparisons so timing does not reveal which part was wrong.
    user_ok = secrets.compare_digest(user.encode(), settings.webhook_user.encode())
    pass_ok = secrets.compare_digest(password.encode(), settings.webhook_password.encode())
    return user_ok and pass_ok


class Responder:
    """Dedupe state plus the background work (capture, then launcher) for new incidents."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.store = IncidentStore(settings.incidents_dir)
        self.pool = ThreadPoolExecutor(max_workers=settings.workers, thread_name_prefix="incident")
        self.futures: list[Future[None]] = []

    def handle_alert(self, alert: dict[str, Any]) -> None:
        fingerprint = check_fingerprint(str(alert.get("fingerprint", "")))
        status = alert.get("status")
        if status == "firing":
            incident = self.store.open_incident(fingerprint)
            if incident is None:
                log("alert_duplicate", fingerprint=fingerprint, alert_status="firing")
                return
            (incident.path / "alert.json").write_text(json.dumps(alert, indent=2, sort_keys=True))
            log("incident_opened", incident_id=incident.id, fingerprint=fingerprint)
            self.futures.append(self.pool.submit(self._run, incident, alert))
        elif status == "resolved":
            closed = self.store.close_incident(fingerprint)
            log(
                "alert_resolved",
                fingerprint=fingerprint,
                incident_id=closed.id if closed else None,
                closed=closed is not None,
            )
        else:
            log("alert_ignored", fingerprint=fingerprint, reason="unknown status")

    def _run(self, incident: Incident, alert: dict[str, Any]) -> None:
        try:
            capture_context(alert, incident.path, self.settings)
            launch(incident, self.settings)
        except Exception as exc:
            log("incident_failed", incident_id=incident.id, error_type=type(exc).__name__)

    def wait(self) -> None:
        """Block until the background work is done (tests, shutdown)."""
        for future in list(self.futures):
            future.result()
        self.futures.clear()

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


def create_app(settings: Settings | None = None) -> FastAPI:
    logmod.configure()
    settings = settings or Settings.from_env()
    responder = Responder(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        responder.shutdown()

    app = FastAPI(
        lifespan=lifespan,
        title="FitWise on-call responder",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.responder = responder

    @app.post("/alerts")
    async def alerts(request: Request) -> Response:
        if not _authorized(request.headers.get("authorization"), settings):
            log("alert_rejected", reason="unauthorized", status_code=401)
            raise HTTPException(
                status_code=401,
                detail="unauthorized",
                headers={"WWW-Authenticate": 'Basic realm="oncall"'},
            )
        try:
            payload = await request.json()
            alerts_list = payload["alerts"]
            if not isinstance(alerts_list, list) or not all(
                isinstance(a, dict) for a in alerts_list
            ):
                raise TypeError("alerts must be a list of objects")
        except (ValueError, KeyError, TypeError):
            log("alert_rejected", reason="malformed payload", status_code=400)
            return JSONResponse({"detail": "malformed payload"}, status_code=400)

        real = [a for a in alerts_list if not is_test_notification(a)]
        if len(real) != len(alerts_list):
            log("test_notification", alerts=len(alerts_list) - len(real))
        try:
            for alert in real:
                check_fingerprint(str(alert.get("fingerprint", "")))
            for alert in real:
                responder.handle_alert(alert)
        except InvalidFingerprintError:
            log("alert_rejected", reason="invalid fingerprint", status_code=400)
            return JSONResponse({"detail": "invalid fingerprint"}, status_code=400)
        return JSONResponse({"status": "accepted", "alerts": len(real)}, status_code=202)

    return app
