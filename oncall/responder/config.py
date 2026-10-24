"""Responder settings, read from environment variables (never from git)."""

from __future__ import annotations

import os
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


class ConfigError(RuntimeError):
    """The environment is missing something the service cannot run safely without."""


@dataclass(frozen=True)
class Settings:
    webhook_user: str
    webhook_password: str
    incidents_dir: Path
    prometheus_url: str
    loki_url: str
    tempo_url: str
    launcher_cmd: tuple[str, ...]
    launcher_timeout_s: float
    capture_timeout_s: float
    window_before_s: int
    window_after_s: int
    workers: int

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        password = e.get("ONCALL_WEBHOOK_PASSWORD", "")
        if not password:
            # Fail closed: an unauthenticated /alerts would let anyone start incident runs.
            raise ConfigError("ONCALL_WEBHOOK_PASSWORD must be set")
        return cls(
            webhook_user=e.get("ONCALL_WEBHOOK_USER", "grafana"),
            webhook_password=password,
            incidents_dir=Path(e.get("ONCALL_INCIDENTS_DIR", "incidents")),
            prometheus_url=e.get("ONCALL_PROMETHEUS_URL", "http://127.0.0.1:9090").rstrip("/"),
            loki_url=e.get("ONCALL_LOKI_URL", "http://127.0.0.1:3100").rstrip("/"),
            tempo_url=e.get("ONCALL_TEMPO_URL", "http://127.0.0.1:3200").rstrip("/"),
            launcher_cmd=tuple(shlex.split(e.get("ONCALL_LAUNCHER_CMD", ""))),
            launcher_timeout_s=float(e.get("ONCALL_LAUNCHER_TIMEOUT_S", "1260")),
            capture_timeout_s=float(e.get("ONCALL_CAPTURE_TIMEOUT_S", "10")),
            window_before_s=int(e.get("ONCALL_CAPTURE_WINDOW_BEFORE_S", "900")),
            window_after_s=int(e.get("ONCALL_CAPTURE_WINDOW_AFTER_S", "60")),
            workers=int(e.get("ONCALL_WORKERS", "4")),
        )
