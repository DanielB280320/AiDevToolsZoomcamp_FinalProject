"""PreToolUse hook for the on-call agent: the second, structural layer behind the allow-list.

The settings file (responder/agent.py) lists permission patterns. Patterns are prefix/glob
matches, so this hook re-checks every tool call against the exact shapes that are allowed:

* Bash: one simple command, no pipes, redirects, `;`, `&&`, `$(...)` or backticks, and then one of
  the allow-listed shapes (read-only curl to Prometheus/Loki/Tempo, read-only `docker compose`,
  the three mitigation scripts, `gh issue create`, `gh pr create`, `git` on the separate clone).
* At most ONE runtime mitigation per incident (flag.sh, rollback.sh or restart.sh): the first one
  writes `mitigation.json` into the incident folder, any further one is refused.
* Read/Write/Edit only inside the incident folder and the separate clone, never the paths that
  define the agent's own rules or the pipeline (.git, .github, .claude, oncall, deploy).

Standard library only: it runs as `python3 guard.py` with the context in the file named by
ONCALL_GUARD_CONFIG. Exit 0 allows, exit 2 blocks and prints the reason to the agent. Anything
unexpected (bad input, missing config) blocks.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MITIGATION_MARKER = "mitigation.json"
BRANCH = re.compile(r"oncall/[A-Za-z0-9][A-Za-z0-9._-]{0,80}")
FORBIDDEN_GIT_PREFIXES = (
    "--output",
    "--ext-diff",
    "--no-index",
    "--upload-pack",
    "--receive-pack",
    "--exec",
    "--git-dir",
    "--work-tree",
    "--force",
    "--delete",
    "--mirror",
    "--all",
    "--tags",
    "--no-verify",
)
GIT_SUBCOMMANDS = frozenset(
    {
        "status",
        "diff",
        "log",
        "show",
        "add",
        "commit",
        "checkout",
        "switch",
        "branch",
        "fetch",
        "rev-parse",
        "ls-files",
        "grep",
    }
)
WRITE_DENIED_PARTS = (".git", ".github", ".claude", "oncall", "deploy")
SERVICE = re.compile(r"[a-z][a-z0-9_-]{0,40}")
FLAG_ARG = re.compile(r"[A-Za-z0-9_-]{1,64}")
INCIDENT_FILES = ("issue.md", "pr.md", "commit-msg.txt")


class Blocked(Exception):  # noqa: N818 (a decision, not an error)
    """The tool call is refused; the message is shown to the agent."""


@dataclass(frozen=True)
class Context:
    incident_dir: Path
    clone_dir: Path
    repo: str
    prometheus_url: str
    loki_url: str
    tempo_url: str

    @classmethod
    def load(cls, path: str) -> Context:
        raw: dict[str, Any] = json.loads(Path(path).read_text())
        return cls(
            incident_dir=Path(raw["incident_dir"]),
            clone_dir=Path(raw["clone_dir"]),
            repo=raw["repo"],
            prometheus_url=raw["prometheus_url"],
            loki_url=raw["loki_url"],
            tempo_url=raw["tempo_url"],
        )


def tokenize(command: str) -> list[str]:
    """Split one simple command; refuse anything that chains, redirects or substitutes."""
    if "\n" in command or "\r" in command or "`" in command or "$(" in command or "${" in command:
        raise Blocked("shell substitution and multi-line commands are not allowed")
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise Blocked("could not parse the command") from exc
    for token in tokens:
        if token and all(c in lexer.punctuation_chars for c in token):
            raise Blocked("pipes, redirects, `;`, `&&` and subshells are not allowed")
    if not tokens:
        raise Blocked("empty command")
    return tokens


def _curl(tokens: list[str], ctx: Context) -> None:
    prom, loki, tempo = ctx.prometheus_url, ctx.loki_url, ctx.tempo_url
    allowed_urls = (
        re.compile(re.escape(prom) + r"/api/v1/(query|query_range|series|labels)"),
        re.compile(re.escape(loki) + r"/loki/api/v1/(query|query_range|labels)"),
        re.compile(re.escape(tempo) + r"/api/search"),
        re.compile(re.escape(tempo) + r"/api/traces/[A-Fa-f0-9]{1,64}"),
    )
    simple = {"-s", "-sG", "-G", "-Gs", "-sS", "--get", "--silent", "-f"}
    url: str | None = None
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok in simple:
            i += 1
        elif tok == "--data-urlencode" and i + 1 < len(tokens):
            if "@" in tokens[i + 1]:
                raise Blocked("curl may not read data from files")
            i += 2
        elif tok == "--max-time" and i + 1 < len(tokens) and tokens[i + 1].isdigit():
            i += 2
        elif tok.startswith("http://") and url is None:
            url = tok
            i += 1
        else:
            raise Blocked(f"curl option not allowed: {tok}")
    if url is None:
        raise Blocked("curl needs a Prometheus, Loki or Tempo URL")
    if not any(p.fullmatch(url) for p in allowed_urls):
        raise Blocked("curl URL is not an allow-listed read-only query endpoint")


def _compose(tokens: list[str]) -> None:
    sub = tokens[2] if len(tokens) > 2 else ""
    if sub == "ps":
        flags = {"-a", "--all", "--services", "--quiet", "-q"}
        i = 3
        while i < len(tokens):
            if tokens[i] in flags:
                i += 1
            elif tokens[i] in {"--format", "--status"} and i + 1 < len(tokens):
                i += 2
            else:
                raise Blocked(f"docker compose ps option not allowed: {tokens[i]}")
    elif sub == "logs":
        flags = {"--no-color", "--timestamps", "-t", "--no-log-prefix"}
        i = 3
        while i < len(tokens):
            if tokens[i] in flags or SERVICE.fullmatch(tokens[i]):
                i += 1
            elif tokens[i] in {"--since", "--until", "--tail", "-n"} and i + 1 < len(tokens):
                i += 2
            else:
                raise Blocked(f"docker compose logs option not allowed: {tokens[i]}")
    else:
        raise Blocked("only `docker compose ps` and `docker compose logs` are allowed")


def _mitigation(tokens: list[str]) -> bool:
    """True if this is an allow-listed runtime mitigation (and its arguments are well-formed)."""
    script = tokens[0]
    if script == "oncall/ops/flag.sh":
        if len(tokens) != 3 or not all(FLAG_ARG.fullmatch(t) for t in tokens[1:]):
            raise Blocked("usage: oncall/ops/flag.sh <key> <value>")
    elif script == "oncall/ops/rollback.sh":
        if len(tokens) != 1:
            raise Blocked("oncall/ops/rollback.sh takes no arguments")
    elif script == "oncall/ops/restart.sh":
        if len(tokens) != 2 or tokens[1] not in {"backend", "frontend"}:
            raise Blocked("usage: oncall/ops/restart.sh <backend|frontend>")
    else:
        return False
    return True


def _gh(tokens: list[str], ctx: Context) -> None:
    inc = str(ctx.incident_dir)
    if tokens[1:3] == ["issue", "create"]:
        want = [
            "--repo",
            ctx.repo,
            "--label",
            "incident",
            "--title",
            None,
            "--body-file",
            f"{inc}/issue.md",
        ]
        rest = tokens[3:]
    elif tokens[1:3] == ["pr", "create"]:
        if tokens[-1] == "--draft":
            tokens = tokens[:-1]
        want = [
            "--repo",
            ctx.repo,
            "--head",
            None,
            "--base",
            "main",
            "--title",
            None,
            "--body-file",
            f"{inc}/pr.md",
        ]
        rest = tokens[3:]
    else:
        raise Blocked("only `gh issue create` and `gh pr create` are allowed")
    if len(rest) != len(want):
        raise Blocked("use exactly the documented option order (see the prompt)")
    for got, expected in zip(rest, want, strict=True):
        if expected is not None and got != expected:
            raise Blocked(f"unexpected gh argument: {got}")
    if tokens[1] == "pr" and not BRANCH.fullmatch(rest[3]):
        raise Blocked("the PR head must be a branch named oncall/<name>")


def _git(tokens: list[str], ctx: Context) -> None:
    if len(tokens) < 4 or tokens[1] != "-C" or tokens[2] != str(ctx.clone_dir):
        raise Blocked("git is only allowed as `git -C <the separate clone> ...`")
    sub, args = tokens[3], tokens[4:]
    if any(a.startswith(FORBIDDEN_GIT_PREFIXES) for a in args):
        raise Blocked("git option not allowed")
    if sub == "push":
        rest = args[1:] if args[:1] in (["-u"], ["--set-upstream"]) else args
        if len(rest) != 2 or rest[0] != "origin" or not BRANCH.fullmatch(rest[1]):
            raise Blocked("push is only allowed as `push [-u] origin oncall/<branch>`")
        return
    if sub not in GIT_SUBCOMMANDS:
        raise Blocked(f"git {sub} is not allowed")
    if sub == "fetch" and args not in ([], ["origin"]):
        raise Blocked("only `git fetch [origin]` is allowed")
    if sub == "commit":
        i = 0
        while i < len(args):
            if args[i] in {"-m", "-F"} and i + 1 < len(args):
                if args[i] == "-F" and args[i + 1] != f"{ctx.incident_dir}/commit-msg.txt":
                    raise Blocked("commit -F may only read commit-msg.txt of this incident")
                i += 2
            elif args[i] in {"-a", "--amend", "-s"}:
                i += 1
            else:
                raise Blocked(f"git commit option not allowed: {args[i]}")


def check_bash(command: str, ctx: Context) -> bool:
    """Validate a command; returns True when it is a runtime mitigation."""
    tokens = tokenize(command)
    head = tokens[0]
    if head == "curl":
        _curl(tokens, ctx)
    elif head == "docker" and tokens[1:2] == ["compose"]:
        _compose(tokens)
    elif head == "gh":
        _gh(tokens, ctx)
    elif head == "git":
        _git(tokens, ctx)
    elif head == "sleep":
        if len(tokens) != 2 or not tokens[1].isdigit() or not 0 < int(tokens[1]) <= 120:
            raise Blocked("usage: sleep <1-120 seconds>")
    elif head.startswith("oncall/ops/"):
        return _mitigation(tokens)
    else:
        raise Blocked(f"command not on the allow-list: {head}")
    return False


def record_mitigation(command: str, ctx: Context) -> None:
    """First mitigation wins; the marker is created atomically so two calls cannot both pass."""
    marker = ctx.incident_dir / MITIGATION_MARKER
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise Blocked(
            "a runtime mitigation was already applied for this incident; apply no second one, "
            "record that in the incident issue instead"
        ) from None
    with os.fdopen(fd, "w") as fh:
        json.dump(
            {"command": command, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, fh
        )


def check_path(tool: str, file_path: str, ctx: Context) -> None:
    path = Path(os.path.realpath(file_path))
    incident = Path(os.path.realpath(ctx.incident_dir))
    clone = Path(os.path.realpath(ctx.clone_dir))
    if path.is_relative_to(incident):
        if tool == "Read":
            return
        if path.parent == incident and path.name in INCIDENT_FILES:
            return
        raise Blocked(
            "only issue.md, pr.md and commit-msg.txt may be written in the incident folder"
        )
    if path.is_relative_to(clone):
        rel = path.relative_to(clone)
        if tool != "Read" and rel.parts and rel.parts[0] in WRITE_DENIED_PARTS:
            raise Blocked(f"{rel.parts[0]}/ may not be modified by the on-call agent")
        if ".env" in path.name:
            raise Blocked("env files may not be touched")
        return
    raise Blocked("path outside the incident folder and the separate clone")


def decide(event: dict[str, Any], ctx: Context) -> None:
    tool = event.get("tool_name")
    tool_input = event.get("tool_input") or {}
    if tool == "Bash":
        command = str(tool_input.get("command", ""))
        if check_bash(command, ctx):
            record_mitigation(command, ctx)
    elif tool in {"Read", "Write", "Edit"}:
        check_path(str(tool), str(tool_input.get("file_path", "")), ctx)
    else:
        raise Blocked(f"tool not allowed: {tool}")


def main() -> int:
    try:
        ctx = Context.load(os.environ["ONCALL_GUARD_CONFIG"])
        event = json.load(sys.stdin)
        decide(event, ctx)
    except Blocked as exc:
        print(f"blocked by the on-call guard: {exc}", file=sys.stderr)  # noqa: T201
        return 2
    except Exception as exc:  # fail closed
        print(f"blocked by the on-call guard: {type(exc).__name__}", file=sys.stderr)  # noqa: T201
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
