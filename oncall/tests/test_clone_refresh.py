"""The separate clone is refreshed to origin/main before each agent run (drill S1, attempt 2)."""
# ruff: noqa: S607 (tests run git with fixed argv, no shell)

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from responder.agent import build_prompt, refresh_clone, run_agent
from responder.config import Settings
from responder.store import Incident

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def git(cwd: Path, *args: str) -> str:
    import os

    done = subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **GIT_ENV, "HOME": str(cwd.parent)},
    )
    return done.stdout.strip()


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    """A bare 'origin' with one commit on main, and a work repo to add commits to it."""
    bare = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q", "-b", "main")
    (work / "app.py").write_text("v1\n")
    git(work, "add", ".")
    git(work, "commit", "-q", "-m", "one")
    git(work, "remote", "add", "origin", str(bare))
    git(work, "push", "-q", "origin", "main")
    return work


@pytest.fixture
def clone_settings(agent_settings: Settings, origin: Path, tmp_path: Path) -> Settings:
    clone = tmp_path / "the-clone"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(clone)], check=True)
    agent_settings.agent_home.mkdir(parents=True, exist_ok=True)
    return replace(
        agent_settings,
        clone_dir=clone,
        clone_refresh_timeout_s=20.0,
        clone_origin_url=str(tmp_path / "origin.git"),
    )


def push_new_commit(work: Path, text: str) -> str:
    (work / "app.py").write_text(text)
    git(work, "commit", "-qam", "next")
    git(work, "push", "-q", "origin", "main")
    return git(work, "rev-parse", "--short=12", "HEAD")


def test_refresh_brings_a_stale_clone_to_origin_main(clone_settings: Settings, origin: Path):
    new = push_new_commit(origin, "v2 DemoFaultError\n")
    assert refresh_clone(clone_settings, "inc1") == new
    assert (clone_settings.clone_dir / "app.py").read_text() == "v2 DemoFaultError\n"
    grep = git(clone_settings.clone_dir, "grep", "-l", "DemoFaultError")
    assert grep == "app.py"


def test_refresh_drops_a_leftover_branch_and_local_changes(clone_settings: Settings, origin: Path):
    clone = clone_settings.clone_dir
    git(clone, "checkout", "-q", "-b", "oncall/old")
    (clone / "app.py").write_text("local edit\n")
    git(clone, "commit", "-qam", "agent commit")
    (clone / "app.py").write_text("uncommitted\n")
    (clone / "stray.txt").write_text("x")
    new = push_new_commit(origin, "v2\n")
    assert refresh_clone(clone_settings, "inc1") == new
    assert (clone / "app.py").read_text() == "v2\n"
    assert not (clone / "stray.txt").exists()
    assert git(clone, "rev-parse", "--short=12", "HEAD") == new
    # the agent's first step, per the prompt, works from here
    git(clone, "checkout", "-q", "-b", "oncall/new", "origin/main")


def test_failed_fetch_is_logged_without_secrets_and_the_run_continues(
    clone_settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    from responder.log import configure

    configure()
    secret_url = "https://x-access-token:ghp_supersecret@127.0.0.1:1/nope.git"
    git(clone_settings.clone_dir, "remote", "set-url", "origin", secret_url)
    clone_settings = replace(clone_settings, clone_origin_url=secret_url)
    assert refresh_clone(clone_settings, "inc1") is None
    out = capsys.readouterr().out
    assert "clone_refresh_failed" in out and "fetch failed" in out
    assert "ghp_supersecret" not in out and "nope.git" not in out


def test_not_a_git_clone_is_a_logged_failure(agent_settings: Settings):
    # the fixture's clone_dir is an empty directory
    assert refresh_clone(replace(agent_settings, clone_refresh_timeout_s=10.0), "inc1") is None


def test_a_hanging_git_is_cut_off_by_the_timeout(
    clone_settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    from responder.log import configure

    configure()
    shim = tmp_path / "bin"
    shim.mkdir()
    (shim / "git").write_text("#!/bin/sh\nsleep 30\n")
    (shim / "git").chmod(0o755)
    monkeypatch.setenv("PATH", f"{shim}:/usr/bin:/bin")
    s = replace(clone_settings, clone_refresh_timeout_s=0.5)
    assert refresh_clone(s, "inc1") is None
    assert '"reason": "timeout"' in capsys.readouterr().out


def test_prompt_tells_the_agent_the_clone_is_current(clone_settings: Settings, incident: Incident):
    alert = json.loads((incident.path / "alert.json").read_text())
    clone = str(clone_settings.clone_dir.resolve())
    fresh = build_prompt(incident, alert, clone_settings, "abc1234def56")
    assert "origin/main (abc1234def56, ref refs/remotes/origin/main)" in fresh
    assert f"checkout -b oncall/{incident.id} refs/remotes/origin/main" in fresh
    assert f"git -C {clone} grep" in fresh
    stale = build_prompt(incident, alert, clone_settings, None)
    assert "refresh" in stale and "may be out of date" in stale and "fetch origin" in stale


def test_run_agent_refreshes_before_it_starts_claude(
    clone_settings: Settings, incident: Incident, origin: Path, tmp_path: Path
):
    new = push_new_commit(origin, "v2\n")
    seen = tmp_path / "seen"
    claude = tmp_path / "claude"
    head = f"git -C {clone_settings.clone_dir} rev-parse --short=12 HEAD > {seen}"
    claude.write_text(f"#!/bin/sh\ncat > {seen}.prompt\n{head}\n")
    claude.chmod(0o755)
    s = replace(clone_settings, claude_bin=str(claude))
    assert run_agent(incident, s) == 0
    assert seen.read_text().strip() == new
    assert new in (tmp_path / "seen.prompt").read_text()


def test_run_agent_still_runs_when_the_refresh_fails(
    agent_settings: Settings, incident: Incident, tmp_path: Path
):
    claude = tmp_path / "claude"
    claude.write_text(f"#!/bin/sh\ncat > {tmp_path}/prompt\n")
    claude.chmod(0o755)
    s = replace(agent_settings, claude_bin=str(claude), clone_refresh_timeout_s=10.0)
    assert run_agent(incident, s) == 0
    assert "may be out of date" in (tmp_path / "prompt").read_text()


def real_main(origin: Path) -> str:
    return git(origin, "rev-parse", "HEAD")


def _assert_at_remote_main(s: Settings, origin: Path, result: str | None) -> None:
    full = real_main(origin)
    assert result == full[:12]
    assert git(s.clone_dir, "rev-parse", "HEAD") == full
    assert (s.clone_dir / "app.py").read_text() == "v2\n"


def test_a_local_branch_named_origin_main_cannot_hold_the_clone_back(
    clone_settings: Settings, origin: Path
):
    old = git(clone_settings.clone_dir, "rev-parse", "HEAD")
    git(clone_settings.clone_dir, "branch", "origin/main", old)  # shadows the short name
    push_new_commit(origin, "v2\n")
    _assert_at_remote_main(clone_settings, origin, refresh_clone(clone_settings, "inc1"))


def test_a_local_tag_named_origin_main_cannot_hold_the_clone_back(
    clone_settings: Settings, origin: Path
):
    old = git(clone_settings.clone_dir, "rev-parse", "HEAD")
    git(clone_settings.clone_dir, "tag", "origin/main", old)
    push_new_commit(origin, "v2\n")
    _assert_at_remote_main(clone_settings, origin, refresh_clone(clone_settings, "inc1"))


def test_a_remote_tag_named_origin_main_cannot_hold_the_clone_back(
    clone_settings: Settings, origin: Path
):
    old = git(origin, "rev-parse", "HEAD")
    push_new_commit(origin, "v2\n")
    git(origin, "tag", "origin/main", old)
    git(origin, "push", "-q", "origin", "origin/main")
    _assert_at_remote_main(clone_settings, origin, refresh_clone(clone_settings, "inc1"))


def test_a_clone_pointing_at_another_repository_is_not_refreshed(
    clone_settings: Settings, origin: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    from responder.log import configure

    configure()
    other = tmp_path / "other.git"
    subprocess.run(["git", "init", "-q", "--bare", str(other)], check=True)
    git(clone_settings.clone_dir, "remote", "set-url", "origin", str(other))
    assert refresh_clone(clone_settings, "inc1") is None
    out = capsys.readouterr().out
    assert "origin url does not match" in out and str(other) not in out


def test_a_hook_in_the_clone_does_not_run_during_the_refresh(
    clone_settings: Settings, origin: Path, tmp_path: Path
):
    marker = tmp_path / "hook-ran"
    hook = clone_settings.clone_dir / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
    hook.chmod(0o755)
    push_new_commit(origin, "v2\n")
    assert refresh_clone(clone_settings, "inc1") is not None
    assert not marker.exists()
