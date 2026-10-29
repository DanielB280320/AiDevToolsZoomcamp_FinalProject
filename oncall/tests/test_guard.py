"""responder/guard.py on its own: no settings allow-list in front of it (#69 QA round 2).

The combined fixture in test_agent.py also applies the settings patterns, which hides gaps in the
guard. Here only `decide()` / `check_bash()` decide.
"""

from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest

from responder.guard import Blocked, Context, check_bash, decide


@pytest.fixture
def ctx(tmp_path: Path) -> Context:
    incident = tmp_path / "inc"
    clone = tmp_path / "clone"
    incident.mkdir()
    clone.mkdir()
    return Context(
        incident_dir=incident,
        clone_dir=clone,
        repo="owner/repo",
        prometheus_url="http://127.0.0.1:9090",
        loki_url="http://127.0.0.1:3100",
        tempo_url="http://127.0.0.1:3200",
    )


def bash(command: str) -> dict[str, object]:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


# --- gap 1: oncall/ops/* spellings -------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "oncall/ops/other.sh",
        "oncall/ops/",
        "oncall/ops/flag.sh.bak a b",
        "oncall/ops/../ops/rollback.sh",
        "oncall//ops/rollback.sh",
        "./oncall/ops/rollback.sh",
        "/opt/fitwise-oncall/app/oncall/ops/rollback.sh",
        "oncall/ops/rollback.sh/",
        "ONCALL/ops/rollback.sh",
        "bash oncall/ops/rollback.sh",
        "sh -c oncall/ops/rollback.sh",
        "env oncall/ops/rollback.sh",
        "FOO=1 oncall/ops/rollback.sh",
        "rollback.sh",
        "/opt/fitwise/bin/rollback.sh",
        "deploy/rollback.sh",
        "oncall/ops/rollback.sh abc",
        "oncall/ops/restart.sh db",
        "oncall/ops/flag.sh onlykey",
    ],
)
def test_unrecognised_spellings_are_blocked_and_never_take_the_slot(command: str, ctx: Context):
    with pytest.raises(Blocked):
        decide(bash(command), ctx)
    assert not (ctx.incident_dir / "mitigation.json").exists()
    # the slot is still free for a correct call
    decide(bash("oncall/ops/rollback.sh"), ctx)
    assert (ctx.incident_dir / "mitigation.json").exists()


def test_canonical_mitigations_share_one_slot(ctx: Context):
    decide(bash("oncall/ops/restart.sh backend"), ctx)
    for second in (
        "oncall/ops/restart.sh frontend",
        "oncall/ops/rollback.sh",
        "oncall/ops/flag.sh progression_engine v1",
    ):
        with pytest.raises(Blocked, match="already applied"):
            decide(bash(second), ctx)
    assert json.loads((ctx.incident_dir / "mitigation.json").read_text())["command"] == (
        "oncall/ops/restart.sh backend"
    )


def test_check_bash_reports_mitigation_only_for_canonical_calls(ctx: Context):
    assert check_bash("oncall/ops/rollback.sh", ctx) is True
    assert check_bash("sleep 5", ctx) is False
    with pytest.raises(Blocked):
        check_bash("oncall/ops/unknown.sh", ctx)


# --- gap 2: git options are an allow-list ------------------------------------------------------


def git(ctx: Context, *args: str) -> str:
    return shlex.join(["git", "-C", str(ctx.clone_dir), *args])


@pytest.mark.parametrize(
    "args",
    [
        ("status",),
        ("status", "--short", "--branch"),
        ("diff",),
        ("diff", "--stat", "origin/main"),
        ("diff", "--cached", "--name-only"),
        ("diff", "origin/main..HEAD", "--", "backend/app/x.py"),
        ("log", "--oneline", "-n", "5"),
        ("log", "-5", "--stat"),
        ("show", "HEAD~1", "--stat"),
        ("show", "HEAD:backend/app/x.py"),
        ("grep", "-n", "-i", "-e", "finish", "--", "backend"),
        ("grep", "-C", "3", "-e", "raise", "origin/main"),
        ("checkout", "-b", "oncall/20261024T100000Z-abc", "origin/main"),
        ("checkout", "oncall/fix"),
        ("checkout", "--", "backend/app/x.py"),
        ("switch", "-c", "oncall/fix"),
        ("branch", "--list", "-a"),
        ("branch", "--show-current"),
        ("add", "backend/app/x.py", "backend/tests/test_x.py"),
        ("add", "-A"),
        ("commit", "-m", "Fix finish error"),
        ("commit", "-a", "--amend", "--no-edit"),
        ("fetch",),
        ("fetch", "origin"),
        ("rev-parse", "--short", "HEAD"),
        ("ls-files", "-o", "--exclude-standard"),
        ("push", "origin", "oncall/fix"),
        ("push", "-u", "origin", "oncall/fix"),
    ],
)
def test_allowed_git_shapes(args: tuple[str, ...], ctx: Context):
    check_bash(git(ctx, *args), ctx)


@pytest.mark.parametrize(
    "args",
    [
        # abbreviated long options: git would expand each of these to a dangerous one
        ("diff", "--out=/tmp/x"),
        ("diff", "--output=/tmp/x"),
        ("log", "--out", "/tmp/x"),
        ("log", "--output=/tmp/x"),
        ("show", "--ext", "HEAD"),
        ("diff", "--ext-diff"),
        ("diff", "--no-ind", "/etc/passwd", "/etc/hosts"),
        ("diff", "--no-index", "/etc/passwd", "/etc/hosts"),
        ("grep", "--no-ind", "-e", "root", "/etc/passwd"),
        ("grep", "--no-index", "-e", "root", "/etc/passwd"),
        ("grep", "--open-files-in-pager=sh", "-e", "x"),
        ("grep", "--open-f=sh", "-e", "x"),
        ("grep", "-O", "-e", "x"),
        ("grep", "-Osh", "-e", "x"),
        ("grep", "-f", "/etc/passwd"),
        ("grep", "--file=/etc/passwd"),
        ("grep", "--recurse-submodules", "-e", "x"),
        ("grep", "--cache", "-e", "x"),  # abbreviation of --cached: still refused, exact only
        ("grep", "-ni", "-e", "x"),  # combined short flags are not parsed
        ("log", "--format=%H"),
        ("log", "--pretty=oneline"),
        ("log", "--exec-path=/tmp"),
        ("log", "--all"),
        ("log", "-n", "five"),
        ("checkout", "-B", "main"),
        ("checkout", "-b", "main"),
        ("checkout", "-b", "feature/x"),
        ("checkout", "--orphan", "x"),
        ("checkout", "--force", "main"),
        ("checkout", "-f", "main"),
        ("checkout", "--track", "origin/main"),
        ("checkout", "--", "/etc/passwd"),
        ("checkout", "--", "../outside"),
        ("checkout", "../outside"),
        ("branch", "-D", "main"),
        ("branch", "--delete", "x"),
        ("branch", "-m", "main", "x"),
        ("branch", "--set-upstream-to=origin/main"),
        ("add", "--intent-to-add", "x"),
        ("add", "-i"),
        ("add", "/etc/passwd"),
        ("add", "~/x"),
        ("add", "../x"),
        ("commit", "-m", "x", "--no-verify"),
        ("commit", "-n", "-m", "x"),
        ("commit", "--author=a", "-m", "x"),
        ("commit", "-F", "/etc/passwd"),
        ("commit", "-m", "x", "extra-path"),
        ("fetch", "origin", "--upload-pack=sh"),
        ("fetch", "https://evil.example/x.git"),
        ("fetch", "--all"),
        ("status", "--git-dir=/tmp"),
        ("status", "--ignored=matching"),
        ("rev-parse", "--git-dir"),
        ("ls-files", "--others", "--directory"),
        ("ls-files", "--exclude-from=/etc/passwd"),
        ("show", "--output=/tmp/x", "HEAD"),
        ("show", "/etc/passwd"),
        ("diff", "HEAD", "--", "/etc/passwd"),
        ("push", "origin", "main"),
        ("push", "origin", "HEAD:main"),
        ("push", "origin", "oncall/x:main"),
        ("push", "--force", "origin", "oncall/x"),
        ("push", "--mirror", "origin"),
        ("push", "origin", "oncall/x", "main"),
        ("config", "alias.x", "!sh"),
        ("remote", "add", "x", "https://evil.example"),
        ("reset", "--hard"),
        ("clean", "-fdx"),
        ("clone", "https://evil.example/x.git"),
        ("submodule", "update"),
        ("-c", "core.pager=sh", "log"),
    ],
)
def test_other_git_shapes_are_blocked(args: tuple[str, ...], ctx: Context):
    with pytest.raises(Blocked):
        check_bash(git(ctx, *args), ctx)


def test_git_must_target_the_separate_clone(ctx: Context, tmp_path: Path):
    for command in (
        "git status",
        f"git -C {tmp_path} status",
        f"git -C {ctx.clone_dir}/.. status",
        f"git --git-dir={ctx.clone_dir}/.git status",
        f"git -c core.pager=sh -C {ctx.clone_dir} log",
    ):
        with pytest.raises(Blocked):
            check_bash(command, ctx)


def test_git_option_table_has_no_prefix_matching():
    from responder.guard import GIT_OPTIONS

    for sub, (flags, valued) in GIT_OPTIONS.items():
        for opt in (*flags, *valued):
            assert not opt.endswith("="), (sub, opt)
