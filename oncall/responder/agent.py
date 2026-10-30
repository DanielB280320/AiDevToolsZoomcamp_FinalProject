"""Headless Claude Code run for one incident (spec §15.2, ADR 0007, issue #69).

`run_agent` writes, into the incident folder:

    agent-settings.json   the permission allow-list and the guard hook (built by `build_settings`)
    guard.json            context for responder/guard.py (paths, repo, backend URLs)
    transcript            the agent's full stream-json output, mode 0600
    agent.json            exit code, duration, timeout flag (no content)
    mitigation.json       written by the guard when the one runtime mitigation is applied
    issue.md, pr.md       drafts written by the agent for `gh issue create` / `gh pr create`

and starts `claude -p` with the prompt on stdin (never in argv), a minimal environment (the
webhook password is not passed) and a hard timeout. The allow-list is deliberately built here, in
one function, so a test can assert it exactly.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from responder.config import Settings
from responder.log import log
from responder.store import Incident

GUARD = Path(__file__).with_name("guard.py")
_RUNBOOK_FILE = re.compile(r"[a-z0-9][a-z0-9-]*\.md")
_INCIDENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}")
# Environment passed to the agent: its own secrets plus what docker/gh/git need. Nothing else.
ENV_PASSTHROUGH = (
    "PATH",
    "LANG",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "GH_TOKEN",
    "DOCKER_HOST",
    "COMPOSE",
    "COMPOSE_FILE",
    "COMPOSE_PROJECT_NAME",
    "FITWISE_BIN_DIR",
)
MITIGATION_SCRIPTS = (
    "oncall/ops/flag.sh *",
    "oncall/ops/rollback.sh",
    "oncall/ops/restart.sh backend",
    "oncall/ops/restart.sh frontend",
)


def build_allowlist(settings: Settings, incident: Incident) -> dict[str, list[str]]:
    """The permission rules for one incident: `allow` and `deny` (deny always wins)."""
    inc = str(incident.path.resolve())
    clone = str(settings.clone_dir.resolve())
    prom, loki, tempo = settings.prometheus_url, settings.loki_url, settings.tempo_url
    repo = settings.github_repo
    bash = [
        # read-only queries (GET only; the guard also pins the endpoint paths)
        f"curl -sG {prom}/api/v1/query *",
        f"curl -sG {prom}/api/v1/query_range *",
        f"curl -sG {loki}/loki/api/v1/query *",
        f"curl -sG {loki}/loki/api/v1/query_range *",
        f"curl -sG {tempo}/api/search *",
        f"curl -s {tempo}/api/traces/*",
        # read-only compose
        "docker compose ps",
        "docker compose ps *",
        "docker compose logs *",
        # the three runtime mitigations (the guard allows only one per incident)
        *MITIGATION_SCRIPTS,
        # recovery check pacing
        "sleep *",
        # incident report and fix PR; everything git happens on the separate clone
        f"gh issue create --repo {repo} --label incident --title * --body-file {inc}/issue.md",
        f"gh pr create --repo {repo} --head oncall/* --base main --title * --body-file {inc}/pr.md",
        f"gh pr create --repo {repo} --head oncall/* --base main --title * "
        f"--body-file {inc}/pr.md --draft",
        *(
            f"git -C {clone} {sub}"
            for sub in (
                "status*",
                "diff*",
                "log*",
                "show*",
                "add *",
                "commit *",
                "checkout *",
                "switch *",
                "branch*",
                "fetch*",
                "rev-parse *",
                "ls-files*",
                "grep *",
                "push origin oncall/*",
                "push -u origin oncall/*",
            )
        ),
    ]
    protected = ("/.git/**", "/.github/**", "/.claude/**", "/oncall/**", "/deploy/**")
    allow = [f"Bash({rule})" for rule in bash]
    allow += [f"Read(/{inc}/**)", f"Read(/{clone}/**)", f"Edit(/{clone}/**)", f"Write(/{clone}/**)"]
    allow += [f"Write(/{inc}/{name})" for name in ("issue.md", "pr.md", "commit-msg.txt")]
    deny = [
        "WebFetch",
        "WebSearch",
        "Task",
        "NotebookEdit",
        "Bash(psql*)",
        "Bash(rm *)",
        "Bash(sudo *)",
        "Bash(docker compose exec*)",
        "Bash(docker compose down*)",
        "Bash(docker compose up*)",
        "Bash(docker compose restart*)",
        "Bash(docker compose logs * -f*)",
        "Bash(docker compose logs * --follow*)",
        "Bash(curl * -X *)",
        "Bash(curl * -d *)",
        "Bash(curl * -o *)",
        "Bash(curl *@*)",
        "Bash(git push origin main*)",
        "Bash(git * push * main*)",
        "Bash(git * push * master*)",
        "Bash(git * push *--force*)",
        "Bash(git * push * +*)",
        "Bash(gh api *)",
        "Bash(gh auth *)",
        "Read(**/.env*)",
        "Read(/etc/**)",
        "Read(~/**)",
    ]
    for tool in ("Edit", "Write"):
        deny += [f"{tool}(/{clone}{part})" for part in protected]
    return {"allow": allow, "deny": deny}


def build_settings(settings: Settings, incident: Incident) -> dict[str, Any]:
    rules = build_allowlist(settings, incident)
    return {
        "permissions": {**rules, "defaultMode": "dontAsk"},
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "^(Bash|Read|Write|Edit)$",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "python3",
                            "args": [str(GUARD)],
                            "timeout": 15,
                            "onFailure": "block",
                        }
                    ],
                }
            ]
        },
        "includeCoAuthoredBy": False,
    }


def guard_context(settings: Settings, incident: Incident) -> dict[str, str]:
    return {
        "incident_dir": str(incident.path.resolve()),
        "clone_dir": str(settings.clone_dir.resolve()),
        "repo": settings.github_repo,
        "prometheus_url": settings.prometheus_url,
        "loki_url": settings.loki_url,
        "tempo_url": settings.tempo_url,
    }


def _runbook(alert: dict[str, Any], settings: Settings) -> tuple[str, str]:
    """(file name, text) of the runbook named by the alert's runbook_url, from the local repo."""
    url = str((alert.get("annotations") or {}).get("runbook_url", ""))
    name = url.rsplit("/", 1)[-1].split("#", 1)[0]
    path = settings.repo_dir / "docs" / "runbooks" / name
    if _RUNBOOK_FILE.fullmatch(name) and path.is_file():
        return name, path.read_text()
    return "", ""


def build_prompt(incident: Incident, alert: dict[str, Any], settings: Settings) -> str:
    labels = alert.get("labels") or {}
    annotations = alert.get("annotations") or {}
    name, runbook = _runbook(alert, settings)
    inc = str(incident.path.resolve())
    clone = str(settings.clone_dir.resolve())
    repo = settings.github_repo
    summary = {
        "alertname": labels.get("alertname"),
        "route": labels.get("route"),
        "severity": labels.get("severity"),
        "env": labels.get("env"),
        "summary": annotations.get("summary"),
        "window": annotations.get("window"),
        "dashboard_url": annotations.get("dashboard_url"),
        "runbook_url": annotations.get("runbook_url"),
        "startsAt": alert.get("startsAt"),
        "values": alert.get("values"),
    }
    runbook_part = (
        f"The runbook for this alert (docs/runbooks/{name}) follows. Use it as your procedure.\n\n"
        f"<runbook>\n{runbook}\n</runbook>"
        if runbook
        else "No runbook is linked to this alert. Investigate read-only, apply NO mitigation, "
        "open the incident issue and stop."
    )
    return f"""You are the FitWise on-call agent. A production alert fired. Incident id: {incident.id}.

## Alert
{json.dumps(summary, indent=2, sort_keys=True)}

## Saved context
Folder {inc}/ holds alert.json, prometheus.json, loki.json, tempo.json and capture.json captured when the alert fired. Read them first (Read tool).

## Hard rules
- Work in the repository checkout (your current directory) for scripts and in the separate clone {clone} for code. Only the tools and commands in your allow-list work; a refused command is final, do not look for a way around it.
- Apply AT MOST ONE runtime mitigation (oncall/ops/flag.sh <key> <value>, oncall/ops/rollback.sh, or oncall/ops/restart.sh <backend|frontend>), only when the runbook's decision table matches the evidence. Never a second one, even if the first did not help.
- After a mitigation, check the alert condition (error ratio under 5 percent / p95 under 1 s) with the runbook's queries every minute (`sleep 60` between checks) for 5 consecutive minutes before you say it recovered. If it does not recover within 15 minutes, say so.
- You have 20 minutes in total. Be brief.
- Never write emails, names, passwords, tokens, body metrics, food names or notes anywhere. Users are identified only by user_hash.
- In titles and commit messages (double-quoted) never use $, !, backslashes or backticks: the guard refuses them. Put detail in the body file instead.
- Never push to main. Never touch deploy, workflows or this on-call code.

## Deliverables
1. Incident issue: write it to {inc}/issue.md (template in the runbook; timeline, evidence, mitigation, recovery check), then run exactly:
   gh issue create --repo {repo} --label incident --title "<title>" --body-file {inc}/issue.md
2. Root-cause fix PR from the separate clone, only if you can identify the cause in the code: `git -C {clone} fetch origin`, `git -C {clone} checkout -b oncall/{incident.id} origin/main`, edit files under {clone} (with a regression test), `git -C {clone} add ...`, `git -C {clone} commit -m "<message>"`, `git -C {clone} push origin oncall/{incident.id}`, write {inc}/pr.md (reference the incident issue), then run exactly:
   gh pr create --repo {repo} --head oncall/{incident.id} --base main --title "<title>" --body-file {inc}/pr.md
   If the cause is not clear from the code, skip the PR and say so in the issue.

{runbook_part}
"""


def _env(settings: Settings, incident: Incident) -> dict[str, str]:
    env = {k: os.environ[k] for k in ENV_PASSTHROUGH if os.environ.get(k)}
    if env.get("CLAUDE_CODE_OAUTH_TOKEN"):
        # Exactly one Claude credential: the subscription token wins, so a leftover API key can
        # never switch the run to pay-per-token billing.
        env.pop("ANTHROPIC_API_KEY", None)
    env.update(
        {
            "HOME": str(settings.agent_home),
            "ONCALL_INCIDENT_DIR": str(incident.path.resolve()),
            "ONCALL_INCIDENT_ID": incident.id,
            "ONCALL_GUARD_CONFIG": str((incident.path / "guard.json").resolve()),
            "GH_PROMPT_DISABLED": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return env


def command_line(settings: Settings, incident: Incident) -> list[str]:
    return [
        settings.claude_bin,
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--settings",
        str((incident.path / "agent-settings.json").resolve()),
        "--setting-sources",
        "user",
        "--tools",
        "Bash,Read,Write,Edit",
        "--permission-mode",
        "dontAsk",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--model",
        settings.agent_model,
        "--max-budget-usd",
        settings.agent_max_budget_usd,
    ]


def _write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(text)


def run_agent(incident: Incident, settings: Settings) -> int | None:
    """Run claude -p for the incident; returns its exit code, None on timeout or start failure."""
    if not _INCIDENT_ID.fullmatch(incident.id):
        log("agent_failed", incident_id=incident.id, error_type="BadIncidentId")
        return None
    try:
        alert = json.loads((incident.path / "alert.json").read_text())
        if not isinstance(alert, dict):
            raise ValueError("alert.json is not an object")
        settings.agent_home.mkdir(parents=True, exist_ok=True)
        _write_private(
            incident.path / "agent-settings.json",
            json.dumps(build_settings(settings, incident), indent=2),
        )
        _write_private(
            incident.path / "guard.json", json.dumps(guard_context(settings, incident), indent=2)
        )
        prompt = build_prompt(incident, alert, settings)
    except (OSError, ValueError) as exc:
        log("agent_failed", incident_id=incident.id, error_type=type(exc).__name__)
        return None

    started = time.monotonic()
    timed_out = False
    exit_code: int | None = None
    fd = os.open(incident.path / "transcript", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    errfd = os.open(
        incident.path / "transcript.stderr", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
    )
    try:
        with os.fdopen(fd, "wb") as out, os.fdopen(errfd, "wb") as err:
            try:
                proc = subprocess.Popen(  # noqa: S603 (fixed argv, no shell)
                    command_line(settings, incident),
                    cwd=settings.repo_dir,
                    env=_env(settings, incident),
                    stdin=subprocess.PIPE,
                    stdout=out,
                    stderr=err,
                    start_new_session=True,
                )
            except OSError as exc:
                log("agent_failed", incident_id=incident.id, error_type=type(exc).__name__)
                return None
            try:
                proc.communicate(prompt.encode(), timeout=settings.agent_timeout_s)
                exit_code = proc.returncode
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(proc.pid, signal.SIGKILL)  # the agent and anything it started
                proc.communicate()
    finally:
        duration = time.monotonic() - started
        _write_private(
            incident.path / "agent.json",
            json.dumps(
                {
                    "exit_code": exit_code,
                    "timed_out": timed_out,
                    "duration_s": round(duration, 1),
                    "max_budget_usd": settings.agent_max_budget_usd,
                    "timeout_s": settings.agent_timeout_s,
                }
            ),
        )
    if timed_out:
        log("agent_timeout", incident_id=incident.id, launcher="agent")
        return None
    log(
        "agent_done",
        incident_id=incident.id,
        launcher="agent",
        exit_code=exit_code,
        duration_ms=int(duration * 1000),
    )
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit("run through the responder")
