"""Responder settings, read from environment variables (never from git)."""

from __future__ import annotations

import os
import re
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
    # Headless on-call agent (#69). Off unless ONCALL_AGENT_ENABLED=1.
    agent_enabled: bool = False
    claude_bin: str = "claude"
    agent_model: str = "sonnet"
    agent_timeout_s: float = 1200.0  # 20 min (spec §15.2)
    agent_max_budget_usd: str = "5"  # per run, enforced by the claude CLI
    agent_home: Path = Path("/var/lib/fitwise-oncall/home")
    repo_dir: Path = Path(__file__).resolve().parent.parent.parent
    clone_dir: Path = Path("/var/lib/fitwise-oncall/clone")
    github_repo: str = "DanielB280320/AiDevToolsZoomcamp_FinalProject"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        e = os.environ if env is None else env
        password = e.get("ONCALL_WEBHOOK_PASSWORD", "")
        if not password:
            # Fail closed: an unauthenticated /alerts would let anyone start incident runs.
            raise ConfigError("ONCALL_WEBHOOK_PASSWORD must be set")
        enabled = e.get("ONCALL_AGENT_ENABLED", "") == "1"
        if enabled:
            # Fail closed: an agent without its own credentials or spend cap must not start.
            for name in ("ANTHROPIC_API_KEY", "GH_TOKEN"):
                if not e.get(name):
                    raise ConfigError(f"{name} must be set when ONCALL_AGENT_ENABLED=1")
        budget = e.get("ONCALL_AGENT_MAX_BUDGET_USD", "5")
        if not re.fullmatch(r"[0-9]+(\.[0-9]+)?", budget) or float(budget) <= 0:
            raise ConfigError("ONCALL_AGENT_MAX_BUDGET_USD must be a positive number")
        defaults = cls.__dataclass_fields__
        return cls(
            agent_enabled=enabled,
            claude_bin=e.get("ONCALL_CLAUDE_BIN", "claude"),
            agent_model=e.get("ONCALL_AGENT_MODEL", "sonnet"),
            agent_timeout_s=float(e.get("ONCALL_AGENT_TIMEOUT_S", "1200")),
            agent_max_budget_usd=budget,
            agent_home=Path(e.get("ONCALL_AGENT_HOME", str(defaults["agent_home"].default))),
            repo_dir=Path(e.get("ONCALL_REPO_DIR", str(defaults["repo_dir"].default))),
            clone_dir=Path(e.get("ONCALL_CLONE_DIR", str(defaults["clone_dir"].default))),
            github_repo=e.get("ONCALL_GITHUB_REPO", str(defaults["github_repo"].default)),
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
