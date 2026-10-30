"""On-call agent launcher (#69): allow-list, guard hook, restart.sh, claude -p invocation."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from responder.agent import build_allowlist, build_prompt, build_settings, run_agent
from responder.config import ConfigError, Settings
from responder.guard import Blocked, Context, decide
from responder.store import Incident
from tests.conftest import fixture, incident_dirs, responder_of

ROOT = Path(__file__).resolve().parents[2]
RESTART = ROOT / "oncall" / "ops" / "restart.sh"
GUARD = ROOT / "oncall" / "responder" / "guard.py"
SECRET_KEY = "sk-ant-test-secret-value"
SECRET_GH = "ghp_testsecretvalue"
SECRET_OAUTH = "sk-ant-oat-test-oauth-value"


@pytest.fixture
def agent_settings(settings: Settings, tmp_path: Path) -> Settings:
    clone = tmp_path / "clone"
    clone.mkdir()
    return replace(
        settings,
        agent_enabled=True,
        clone_dir=clone,
        repo_dir=ROOT,
        agent_home=tmp_path / "home",
        github_repo="owner/repo",
    )


@pytest.fixture
def incident(tmp_path: Path) -> Incident:
    path = tmp_path / "incidents" / "20261024T100000Z-9d1f0c2a7b3e"
    path.mkdir(parents=True)
    (path / "alert.json").write_text(json.dumps(fixture("firing")["alerts"][0]))
    return Incident(id=path.name, path=path)


# --- allow-list ------------------------------------------------------------------------------


def _bash_rules(rules: list[str]) -> list[str]:
    return [r[5:-1] for r in rules if r.startswith("Bash(")]


def test_allow_list_is_exactly_the_documented_set(agent_settings: Settings, incident: Incident):
    rules = build_allowlist(agent_settings, incident)
    inc = str(incident.path.resolve())
    clone = str(agent_settings.clone_dir.resolve())
    prom, loki, tempo = (
        agent_settings.prometheus_url,
        agent_settings.loki_url,
        agent_settings.tempo_url,
    )
    expected_bash = {
        f"curl -sG {prom}/api/v1/query *",
        f"curl -sG {prom}/api/v1/query_range *",
        f"curl -sG {loki}/loki/api/v1/query *",
        f"curl -sG {loki}/loki/api/v1/query_range *",
        f"curl -sG {tempo}/api/search *",
        f"curl -s {tempo}/api/traces/*",
        "docker compose ps",
        "docker compose ps *",
        "docker compose logs *",
        "oncall/ops/flag.sh *",
        "oncall/ops/rollback.sh",
        "oncall/ops/restart.sh backend",
        "oncall/ops/restart.sh frontend",
        "sleep *",
        f"gh issue create --repo owner/repo --label incident --title * --body-file {inc}/issue.md",
        f"gh pr create --repo owner/repo --head oncall/* --base main --title * "
        f"--body-file {inc}/pr.md",
        f"gh pr create --repo owner/repo --head oncall/* --base main --title * "
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
    }
    assert set(_bash_rules(rules["allow"])) == expected_bash
    # File access: the incident folder and the clone, nothing else.
    others = [r for r in rules["allow"] if not r.startswith("Bash(")]
    assert all(f"/{inc}" in r or f"/{clone}" in r for r in others)
    assert f"Write(/{inc}/**)" not in others  # only three named files are writable there


def test_settings_file_uses_dont_ask_and_the_guard_hook(
    agent_settings: Settings, incident: Incident
):
    cfg = build_settings(agent_settings, incident)
    assert cfg["permissions"]["defaultMode"] == "dontAsk"
    hook = cfg["hooks"]["PreToolUse"][0]["hooks"][0]
    assert hook["onFailure"] == "block"
    assert hook["args"] == [str(GUARD)]
    assert GUARD.is_file()


def _glob(pattern: str, text: str) -> bool:
    regex = "".join(".*" if c == "*" else re.escape(c) for c in pattern)
    return re.fullmatch(regex, text) is not None


@pytest.fixture
def guard_ctx(agent_settings: Settings, incident: Incident) -> Context:
    from responder.agent import guard_context

    cfg = tmp = Path(agent_settings.agent_home)
    tmp.mkdir(parents=True, exist_ok=True)
    path = cfg / "guard.json"
    path.write_text(json.dumps(guard_context(agent_settings, incident)))
    return Context.load(str(path))


@pytest.fixture
def permitted(
    agent_settings: Settings, incident: Incident, guard_ctx: Context
) -> Callable[[str], bool]:
    """Would Claude Code run this Bash command? deny wins; no allow match means denied."""
    rules = build_allowlist(agent_settings, incident)
    allow, deny = _bash_rules(rules["allow"]), _bash_rules(rules["deny"])

    def check(command: str) -> bool:
        if any(_glob(p, command) for p in deny):
            return False
        if not any(_glob(p, command) for p in allow):
            return False
        try:
            # a throw-away copy of the marker state: probing must not consume the mitigation
            from responder.guard import check_bash

            check_bash(command, guard_ctx)
        except Blocked:
            return False
        return True

    return check


def test_permitted_commands(
    permitted: Callable[[str], bool], agent_settings: Settings, incident: Incident
):
    s = agent_settings
    inc = incident.path.resolve()
    clone = s.clone_dir.resolve()
    good = [
        f"curl -sG {s.prometheus_url}/api/v1/query --data-urlencode 'query=up'",
        f"curl -sG {s.prometheus_url}/api/v1/query_range --data-urlencode 'query=up'",
        f"curl -sG {s.loki_url}/loki/api/v1/query_range --data-urlencode "
        '\'query={service_name="fitwise-backend"} | detected_level=~"error"\' '
        "--data-urlencode since=30m",
        f"curl -sG {s.tempo_url}/api/search --data-urlencode 'q={{ status = error }}'",
        f"curl -s {s.tempo_url}/api/traces/abc123",
        "docker compose ps",
        "docker compose logs --since 30m --tail 200 backend",
        "oncall/ops/flag.sh progression_engine v1",
        "oncall/ops/rollback.sh",
        "oncall/ops/restart.sh backend",
        "oncall/ops/restart.sh frontend",
        "sleep 60",
        f'gh issue create --repo owner/repo --label incident --title "Incident: x" '
        f"--body-file {inc}/issue.md",
        f"git -C {clone} status",
        f"git -C {clone} checkout -b oncall/{incident.id} origin/main",
        f'git -C {clone} commit -m "Fix finish"',
        f"git -C {clone} push origin oncall/{incident.id}",
        f"git -C {clone} push -u origin oncall/{incident.id}",
        f'gh pr create --repo owner/repo --head oncall/{incident.id} --base main --title "Fix" '
        f"--body-file {inc}/pr.md",
    ]
    for command in good:
        assert permitted(command), command


@pytest.mark.parametrize(
    "command",
    [
        "psql -h localhost fitwise",
        "rm -rf /",
        "rm incidents/x",
        "sudo oncall/ops/rollback.sh",
        "cat /etc/passwd",
        "env",
        "docker compose exec db psql",
        "docker compose exec backend sh",
        "docker compose down",
        "docker compose restart db",
        "docker compose logs -f backend",
        "docker compose logs --follow backend",
        "oncall/ops/restart.sh db",
        "oncall/ops/restart.sh backend frontend",
        "oncall/ops/rollback.sh abc123",
        "oncall/ops/flag.sh progression_engine",
        "oncall/ops/flag.sh a b; rm x",
        "git push origin main",
        "git push origin HEAD:main",
        "git push --force origin oncall/x",
        "git -C /tmp/other status",
        "git status",
        "gh api repos/o/r -X DELETE",
        "gh repo delete owner/repo",
        "gh issue create --repo owner/repo --label incident --title t --body-file /etc/shadow",
        "gh issue create --repo other/repo --label incident --title t --body-file x",
        "curl -X POST http://127.0.0.1:9090/api/v1/admin/tsdb/delete_series",
        "curl -sG http://127.0.0.1:9090/api/v1/query -o /tmp/x",
        "curl http://169.254.169.254/latest/meta-data/",
        "oncall/ops/rollback.sh && rm -rf /",
        "oncall/ops/rollback.sh; id",
        "docker compose ps | sh",
        "docker compose ps > /tmp/x",
        "docker compose ps $(id)",
        "docker compose ps `id`",
        "sleep 600",
        "python3 -c 'print(1)'",
        "bash -c id",
    ],
)
def test_everything_else_is_denied(
    command: str, permitted: Callable[[str], bool], agent_settings: Settings, incident: Incident
):
    assert not permitted(command)


def test_chained_and_unsafe_forms_of_allowed_commands_are_denied(
    permitted: Callable[[str], bool], agent_settings: Settings
):
    s = agent_settings
    base = f"curl -sG {s.prometheus_url}/api/v1/query --data-urlencode 'query=up'"
    assert permitted(base)
    assert not permitted(base + " --data-urlencode 'x=@/etc/passwd'")
    assert not permitted(base + " -o /tmp/x")
    assert not permitted(base + " ; id")
    assert not permitted(base + " | sh")
    assert not permitted(f"curl -sG {s.prometheus_url}/api/v1/admin/tsdb/snapshot")
    assert not permitted(f"curl -sG {s.prometheus_url}/api/v1/query/../admin/x")


# --- guard: one mitigation, paths, hook protocol ----------------------------------------------


def _bash(command: str) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def test_only_one_mitigation_per_incident(guard_ctx: Context):
    decide(_bash("oncall/ops/flag.sh progression_engine v1"), guard_ctx)
    marker = json.loads((guard_ctx.incident_dir / "mitigation.json").read_text())
    assert marker["command"] == "oncall/ops/flag.sh progression_engine v1"
    for second in (
        "oncall/ops/rollback.sh",
        "oncall/ops/restart.sh backend",
        "oncall/ops/flag.sh progression_engine v1",
    ):
        with pytest.raises(Blocked, match="already applied"):
            decide(_bash(second), guard_ctx)
    # read-only investigation still works after the mitigation (recovery check)
    decide(_bash("docker compose ps"), guard_ctx)
    decide(_bash("sleep 60"), guard_ctx)


def test_invalid_mitigation_does_not_consume_the_slot(guard_ctx: Context):
    with pytest.raises(Blocked):
        decide(_bash("oncall/ops/restart.sh db"), guard_ctx)
    decide(_bash("oncall/ops/restart.sh frontend"), guard_ctx)


def test_file_access_is_limited(guard_ctx: Context):
    inc, clone = guard_ctx.incident_dir, guard_ctx.clone_dir

    def tool(name: str, path: Path | str) -> dict[str, object]:
        return {"tool_name": name, "tool_input": {"file_path": str(path)}}

    decide(tool("Read", inc / "prometheus.json"), guard_ctx)
    decide(tool("Write", inc / "issue.md"), guard_ctx)
    decide(tool("Write", inc / "pr.md"), guard_ctx)
    decide(tool("Edit", clone / "backend" / "app" / "x.py"), guard_ctx)
    cases: list[tuple[str, Path | str]] = [
        ("Write", inc / "alert.json"),
        ("Write", inc / "agent-settings.json"),
        ("Write", inc / "mitigation.json"),
        ("Write", clone / "oncall" / "responder" / "guard.py"),
        ("Edit", clone / ".github" / "workflows" / "ci.yml"),
        ("Write", clone / ".git" / "hooks" / "pre-commit"),
        ("Edit", clone / "deploy" / "poll.sh"),
        ("Edit", clone / ".claude" / "settings.json"),
        ("Read", "/etc/passwd"),
        ("Read", clone / ".env"),
        ("Write", clone / ".." / "elsewhere.txt"),
        ("Write", inc / ".." / ".." / "x"),
    ]
    for name, path in cases:
        with pytest.raises(Blocked):
            decide(tool(name, path), guard_ctx)
    with pytest.raises(Blocked, match="tool not allowed"):
        decide({"tool_name": "WebFetch", "tool_input": {"url": "http://x"}}, guard_ctx)


def test_symlink_out_of_the_clone_is_refused(guard_ctx: Context, tmp_path: Path):
    (tmp_path / "secret.txt").write_text("x")
    link = guard_ctx.clone_dir / "link.txt"
    link.symlink_to(tmp_path / "secret.txt")
    with pytest.raises(Blocked):
        decide({"tool_name": "Read", "tool_input": {"file_path": str(link)}}, guard_ctx)


def _run_hook(event: object, config: Path | None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"]}
    if config:
        env["ONCALL_GUARD_CONFIG"] = str(config)
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=json.dumps(event) if not isinstance(event, str) else event,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_hook_protocol_exit_codes(guard_ctx: Context, agent_settings: Settings):
    config = agent_settings.agent_home / "guard.json"
    assert _run_hook(_bash("docker compose ps"), config).returncode == 0
    denied = _run_hook(_bash("psql"), config)
    assert denied.returncode == 2
    assert "not on the allow-list" in denied.stderr
    # fail closed: unparsable input and a missing config both block
    assert _run_hook("not json", config).returncode == 2
    assert _run_hook(_bash("docker compose ps"), None).returncode == 2


# --- restart.sh ------------------------------------------------------------------------------


def _fake_compose(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "compose.log"
    script = tmp_path / "fake-compose"
    script.write_text(f'#!/bin/sh\necho "$@" >> {log}\nexit "${{FAKE_EXIT:-0}}"\n')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script, log


@pytest.mark.parametrize("service", ["backend", "frontend"])
def test_restart_accepts_backend_and_frontend(service: str, tmp_path: Path):
    compose, log = _fake_compose(tmp_path)
    result = subprocess.run(
        [str(RESTART), service],
        env={**os.environ, "COMPOSE": str(compose)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert log.read_text().strip() == f"restart {service}"


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["db"],
        ["grafana"],
        ["all"],
        ["backend", "frontend"],
        [""],
        ["Backend"],
        ["-h"],
        ["backend;id"],
        ["--all"],
        ["backend "],
        ["../backend"],
    ],
)
def test_restart_rejects_anything_else(args: list[str], tmp_path: Path):
    compose, log = _fake_compose(tmp_path)
    result = subprocess.run(
        [str(RESTART), *args],
        env={**os.environ, "COMPOSE": str(compose)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert not log.exists()  # docker compose was never called


def test_restart_passes_compose_failure_through(tmp_path: Path):
    compose, _ = _fake_compose(tmp_path)
    result = subprocess.run(
        [str(RESTART), "backend"],
        env={**os.environ, "COMPOSE": str(compose), "FAKE_EXIT": "7"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 7


# --- claude -p invocation ----------------------------------------------------------------------


def _fake_claude(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "fake-claude"
    text = textwrap.dedent(body).replace("@RECORD@", str(tmp_path / "record.json"))
    script.write_text("#!/usr/bin/env python3\n" + text)
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


RECORD = """
    import json, os, sys
    rec = {"argv": sys.argv[1:], "env": dict(os.environ), "stdin": sys.stdin.read(),
           "cwd": os.getcwd()}
    open("@RECORD@", "w").write(json.dumps(rec))
    print(json.dumps({"type": "result", "subtype": "success"}))
"""


def test_run_agent_builds_the_claude_command(
    agent_settings: Settings, incident: Incident, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    record = tmp_path / "record.json"
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", SECRET_OAUTH)
    monkeypatch.setenv("GH_TOKEN", SECRET_GH)
    monkeypatch.setenv("ONCALL_WEBHOOK_PASSWORD", "webhook-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    s = replace(agent_settings, claude_bin=str(_fake_claude(tmp_path, RECORD)))
    assert run_agent(incident, s) == 0
    rec = json.loads(record.read_text())
    argv = rec["argv"]
    assert argv[0] == "-p"
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--max-budget-usd") + 1] == "5"
    assert argv[argv.index("--tools") + 1] == "Bash,Read,Write,Edit"
    assert argv[argv.index("--settings") + 1] == str(
        incident.path.resolve() / "agent-settings.json"
    )
    assert "--strict-mcp-config" in argv
    # the prompt travels on stdin, not in argv; it carries alert, incident folder and runbook
    prompt = rec["stdin"]
    assert not any("KeyJourneyErrors" in a for a in argv)
    assert "KeyJourneyErrors" in prompt
    assert str(incident.path.resolve()) in prompt
    assert "<runbook>" in prompt and "Runbook: KeyJourneyErrors" in prompt
    assert "AT MOST ONE runtime mitigation" in prompt
    # least privilege: own secrets yes, the webhook password and cloud credentials no
    env = rec["env"]
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == SECRET_OAUTH and env["GH_TOKEN"] == SECRET_GH
    assert "ANTHROPIC_API_KEY" not in env  # the subscription token wins; one credential only
    assert "ONCALL_WEBHOOK_PASSWORD" not in env and "AWS_SECRET_ACCESS_KEY" not in env
    assert env["ONCALL_GUARD_CONFIG"].endswith("guard.json")
    assert rec["cwd"] == str(ROOT)
    # transcript saved, private, secrets nowhere in the incident folder
    transcript = incident.path / "transcript"
    assert '"type": "result"' in transcript.read_text()
    assert stat.S_IMODE(transcript.stat().st_mode) == 0o600
    meta = json.loads((incident.path / "agent.json").read_text())
    assert meta["exit_code"] == 0 and meta["timed_out"] is False
    for f in incident.path.iterdir():
        text = f.read_text()
        assert SECRET_KEY not in text and SECRET_GH not in text and "webhook-secret" not in text
        assert SECRET_OAUTH not in text


def test_run_agent_passes_an_api_key_when_it_is_the_only_credential(
    agent_settings: Settings, incident: Incident, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    record = tmp_path / "record.json"
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_KEY)
    s = replace(agent_settings, claude_bin=str(_fake_claude(tmp_path, RECORD)))
    assert run_agent(incident, s) == 0
    env = json.loads(record.read_text())["env"]
    assert env["ANTHROPIC_API_KEY"] == SECRET_KEY and "CLAUDE_CODE_OAUTH_TOKEN" not in env


def test_run_agent_times_out_and_kills_the_process_group(
    agent_settings: Settings, incident: Incident, tmp_path: Path
):
    pidfile = tmp_path / "child.pid"
    script = _fake_claude(
        tmp_path,
        f"""
        import subprocess, time
        child = subprocess.Popen(["sleep", "300"])
        open({str(pidfile)!r}, "w").write(str(child.pid))
        time.sleep(300)
        """,
    )
    s = replace(agent_settings, claude_bin=str(script), agent_timeout_s=1.5)
    assert run_agent(incident, s) is None
    meta = json.loads((incident.path / "agent.json").read_text())
    assert meta["timed_out"] is True and meta["exit_code"] is None
    pid = int(pidfile.read_text())
    for _ in range(50):  # the kernel may need a moment to reap the killed group
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_run_agent_without_runbook_says_to_apply_no_mitigation(
    agent_settings: Settings, incident: Incident
):
    alert = fixture("firing")["alerts"][0]
    alert["annotations"]["runbook_url"] = "https://x/y/../../etc/passwd"
    prompt = build_prompt(incident, alert, agent_settings)
    assert "No runbook is linked" in prompt and "<runbook>" not in prompt


def test_missing_claude_binary_is_logged_not_raised(
    agent_settings: Settings, incident: Incident, tmp_path: Path
):
    s = replace(agent_settings, claude_bin=str(tmp_path / "nope"))
    assert run_agent(incident, s) is None


def test_default_timeout_and_budget_are_the_documented_ones():
    s = Settings.from_env({"ONCALL_WEBHOOK_PASSWORD": "x"})
    assert s.agent_timeout_s == 1200.0  # 20 min (spec §15.2)
    assert s.agent_max_budget_usd == "5"
    assert s.agent_enabled is False


def test_agent_requires_its_own_secrets_and_a_sane_budget():
    base = {"ONCALL_WEBHOOK_PASSWORD": "x", "ONCALL_AGENT_ENABLED": "1"}
    with pytest.raises(ConfigError, match="CLAUDE_CODE_OAUTH_TOKEN"):
        Settings.from_env({**base, "GH_TOKEN": "t"})  # neither credential: fail closed
    with pytest.raises(ConfigError, match="CLAUDE_CODE_OAUTH_TOKEN"):
        Settings.from_env({**base, "GH_TOKEN": "t", "CLAUDE_CODE_OAUTH_TOKEN": ""})
    with pytest.raises(ConfigError, match="GH_TOKEN"):
        Settings.from_env({**base, "CLAUDE_CODE_OAUTH_TOKEN": "o"})
    with pytest.raises(ConfigError, match="GH_TOKEN"):
        Settings.from_env({**base, "ANTHROPIC_API_KEY": "k"})
    ok = Settings.from_env({**base, "ANTHROPIC_API_KEY": "k", "GH_TOKEN": "t"})
    assert ok.agent_enabled
    only_oauth = Settings.from_env({**base, "CLAUDE_CODE_OAUTH_TOKEN": "o", "GH_TOKEN": "t"})
    assert only_oauth.agent_enabled
    with pytest.raises(ConfigError, match="BUDGET"):
        Settings.from_env({"ONCALL_WEBHOOK_PASSWORD": "x", "ONCALL_AGENT_MAX_BUDGET_USD": "0"})
    with pytest.raises(ConfigError, match="BUDGET"):
        Settings.from_env({"ONCALL_WEBHOOK_PASSWORD": "x", "ONCALL_AGENT_MAX_BUDGET_USD": "5; x"})


def test_new_alert_starts_claude_p_via_the_receiver(
    agent_settings: Settings,
    make_client: Callable[[Settings], TestClient],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    record = tmp_path / "record.json"
    s = replace(agent_settings, claude_bin=str(_fake_claude(tmp_path, RECORD)))
    client = make_client(s)
    assert client.post("/alerts", json=fixture("firing")).status_code == 202
    responder_of(client).wait()
    (inc,) = incident_dirs(s)
    rec = json.loads(record.read_text())
    assert rec["argv"][0] == "-p"
    assert "KeyJourneyErrors" in rec["stdin"]
    assert (inc / "transcript").is_file() and (inc / "prometheus.json").is_file()
    # a duplicate notification does not start a second agent
    record.unlink()
    assert client.post("/alerts", json=fixture("firing")).status_code == 202
    responder_of(client).wait()
    assert not record.exists()
