"""Launcher hook: hands a new incident to whatever should investigate it.

ONCALL_LAUNCHER_CMD is a command line (split like a shell would, but run without a shell). The
incident folder is appended as the last argument and also passed as ONCALL_INCIDENT_DIR and
ONCALL_INCIDENT_ID (a test seam). With ONCALL_AGENT_ENABLED=1 the hook is the headless Claude
Code run in responder/agent.py (#69). With neither configured the hook only logs.
"""

from __future__ import annotations

import os
import subprocess
import time

from responder.agent import run_agent
from responder.config import Settings
from responder.log import log
from responder.store import Incident


def launch(incident: Incident, settings: Settings) -> int | None:
    """Run the hook; returns its exit code, or None if no hook is configured or it timed out."""
    if settings.agent_enabled:
        return run_agent(incident, settings)
    if not settings.launcher_cmd:
        log("launcher_noop", incident_id=incident.id, launcher="none")
        return None
    started = time.monotonic()
    env = {
        **os.environ,
        "ONCALL_INCIDENT_DIR": str(incident.path.resolve()),
        "ONCALL_INCIDENT_ID": incident.id,
    }
    # The responder's own credential must not leak into the launched agent's environment.
    env.pop("ONCALL_WEBHOOK_PASSWORD", None)
    try:
        result = subprocess.run(  # noqa: S603 (operator-configured command, no shell)
            [*settings.launcher_cmd, str(incident.path.resolve())],
            env=env,
            timeout=settings.launcher_timeout_s,
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        log("launcher_timeout", incident_id=incident.id, launcher="cmd")
        return None
    except OSError as exc:
        log("launcher_failed", incident_id=incident.id, error_type=type(exc).__name__)
        return None
    log(
        "launcher_done",
        incident_id=incident.id,
        launcher="cmd",
        exit_code=result.returncode,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return result.returncode
