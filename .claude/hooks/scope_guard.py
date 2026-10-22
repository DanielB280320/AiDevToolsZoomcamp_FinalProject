#!/usr/bin/env python3
"""FitWise scope guard: a Claude Code PreToolUse hook (ADR 0008).

Blocks file writes by the ``qa`` and ``pm`` subagents outside the
directories docs/team.md allows them to write. All other agents and the
main session are not affected.

Claude Code sends the hook input as JSON on stdin. Inside a subagent the
input carries ``agent_type`` (the ``name`` from the agent's frontmatter);
the main session has no ``agent_type``. For a blocked call the hook prints
a ``permissionDecision: "deny"`` JSON object and exits 0; for an allowed
call it prints nothing and exits 0. Unreadable input exits 2 (block).

Covered tools: Write, Edit, MultiEdit, NotebookEdit (target path) and Bash
(a deny-list of shell forms that write files, including ``git add`` and
``git commit`` of out-of-scope files). PowerShell is blocked outright for
restricted agents. See docs/adr/0008-enforce-agent-write-scopes-with-a-hook.md
for the residual risks.

Standard library only, so it runs from a fresh clone with any python3 >= 3.9.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

# Write scopes per agent, relative to the repository root (docs/team.md, Roles).
SCOPES: dict[str, tuple[str, ...]] = {
    "qa": ("backend/tests/", "frontend/tests/", "e2e/"),
    "pm": ("docs/", ".github/ISSUE_TEMPLATE/"),
}

HINTS: dict[str, str] = {
    "qa": "QA writes tests only; report the defect on the issue instead of changing it.",
    "pm": "The PM writes docs and issue templates only; describe the change on the issue for the Engineer/DevOps.",
}

FILE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}

# Device files that are always safe write targets.
SAFE_DEVICES = ("/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty")


class Denied(Exception):
    """Raised with a human-readable reason when a write is out of scope."""


# --------------------------------------------------------------------------
# Path classification
# --------------------------------------------------------------------------


@dataclass
class Context:
    agent: str
    scopes: tuple[str, ...]
    project_dir: str | None
    scratchpad: str | None
    _project_common: str | None = None
    _repo_cache: dict[str, tuple[str, str] | None] = field(default_factory=dict)

    def scope_text(self) -> str:
        return ", ".join(self.scopes)


def _git(args: list[str], cwd: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )


def repo_of(directory: str, ctx: Context) -> tuple[str, str] | None:
    """Return (toplevel, common git dir) for the work tree containing directory."""
    if directory in ctx._repo_cache:
        return ctx._repo_cache[directory]
    result = None
    if os.path.isdir(directory):
        proc = _git(["rev-parse", "--path-format=absolute", "--show-toplevel", "--git-common-dir"], directory)
        lines = proc.stdout.splitlines()
        if proc.returncode == 0 and len(lines) == 2:
            result = (os.path.realpath(lines[0]), os.path.realpath(lines[1]))
    ctx._repo_cache[directory] = result
    return result


def project_common_dir(ctx: Context) -> str | None:
    if ctx._project_common is None and ctx.project_dir:
        repo = repo_of(os.path.realpath(ctx.project_dir), ctx)
        ctx._project_common = repo[1] if repo else ""
    return ctx._project_common or None


def _existing_ancestor(path: str) -> str:
    current = path
    while not os.path.isdir(current):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return current


def resolve(path: str, cwd: str | None) -> str:
    """Absolute, symlink-resolved, ``..``-free version of path."""
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        if not cwd:
            raise Denied(f"cannot verify the relative path {path!r} (unknown working directory)")
        path = os.path.join(cwd, path)
    return os.path.realpath(path)


def repo_relative(real: str, ctx: Context) -> str | None:
    """Path relative to its FitWise work tree, or None if outside the repository."""
    repo = repo_of(_existing_ancestor(real), ctx)
    if repo is None:
        return None
    top, common = repo
    expected = project_common_dir(ctx)
    if expected and common != expected:
        return None  # a different git repository
    return os.path.relpath(real, top)


def in_scope(rel: str, scopes: tuple[str, ...]) -> bool:
    if rel == "." or rel.startswith("../"):
        return False
    return any(rel == s.rstrip("/") or rel.startswith(s) for s in scopes)


def check_path(path: str, cwd: str | None, ctx: Context, action: str) -> None:
    """Raise Denied unless writing path is inside the agent's scope."""
    if "$" in path or "`" in path:
        raise Denied(f"{action}: cannot verify the target {path!r} because it contains a variable or command substitution")
    real = resolve(path, cwd)
    if real in SAFE_DEVICES or real.startswith(("/dev/fd/", "/proc/self/fd/")):
        return
    if ctx.scratchpad:
        pad = os.path.realpath(ctx.scratchpad)
        if real == pad or real.startswith(pad + os.sep):
            return
    rel = repo_relative(real, ctx)
    if rel is None:
        raise Denied(f"{action}: {real} is outside the FitWise repository")
    if not in_scope(rel, ctx.scopes):
        raise Denied(f"{action}: {rel} is outside the allowed directories")


# --------------------------------------------------------------------------
# Shell parsing (a small, conservative subset of bash)
# --------------------------------------------------------------------------


@dataclass
class Word:
    text: str
    dynamic: bool = False  # contains unquoted/double-quoted $ or a substitution


@dataclass
class SimpleCommand:
    words: list[Word] = field(default_factory=list)
    redirects: list[tuple[str, Word]] = field(default_factory=list)
    marker: str = ""  # "(" or ")" for subshell boundaries


SEPARATORS = ("&&", "||", ";;", ";", "|&", "|", "&", "\n", "(", ")")
REDIRECT_OPS = ("&>>", "&>", ">>", ">|", ">&", "<>", "<<<", "<<-", "<<", "<&", ">", "<")


class ShellParser:
    def __init__(self, text: str) -> None:
        self.s = text
        self.i = 0
        self.commands: list[SimpleCommand] = []
        self.pending_heredocs: list[tuple[str, bool]] = []

    # -- helpers ------------------------------------------------------------
    def _peek(self, n: int = 1) -> str:
        return self.s[self.i : self.i + n]

    def _read_balanced_subst(self) -> str:
        """Read after '$(' up to the matching ')' and return the inner text."""
        depth, start = 1, self.i
        quote = None
        heredocs: list[str] = []
        while self.i < len(self.s):
            c = self.s[self.i]
            if c == "\n" and heredocs and not quote:
                # Skip here-document bodies: they are data, not shell syntax.
                self.i += 1
                for delim in heredocs:
                    while self.i < len(self.s):
                        end = self.s.find("\n", self.i)
                        end = len(self.s) if end == -1 else end
                        line = self.s[self.i : end]
                        self.i = end + 1
                        if line.strip() == delim:
                            break
                heredocs = []
                continue
            if not quote and self.s.startswith("<<", self.i) and not self.s.startswith("<<<", self.i):
                m = re.match(r"<<-?\s*(['\"]?)([^\s'\"<>;&|()]+)\1", self.s[self.i :])
                if m:
                    heredocs.append(m.group(2))
                    self.i += m.end()
                    continue
            if quote:
                if c == "\\" and quote == '"':
                    self.i += 1
                elif c == quote:
                    quote = None
            elif c in "'\"":
                quote = c
            elif c == "\\":
                self.i += 1
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    inner = self.s[start : self.i]
                    self.i += 1
                    return inner
            self.i += 1
        return self.s[start:]

    def _read_backtick(self) -> str:
        start = self.i
        while self.i < len(self.s) and self.s[self.i] != "`":
            if self.s[self.i] == "\\":
                self.i += 1
            self.i += 1
        inner = self.s[start : self.i]
        self.i += 1
        return inner

    def _substitution(self, inner: str) -> None:
        self.commands.extend(parse_shell(inner))

    def _read_word(self) -> Word:
        buf: list[str] = []
        dynamic = False
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t\n;&|()<>":
                break
            if c == "\\":
                if self._peek(2) == "\\\n":
                    self.i += 2
                    continue
                buf.append(self.s[self.i + 1 : self.i + 2])
                self.i += 2
            elif c == "'":
                end = self.s.find("'", self.i + 1)
                end = len(self.s) if end == -1 else end
                buf.append(self.s[self.i + 1 : end])
                self.i = end + 1
            elif c == '"':
                self.i += 1
                while self.i < len(self.s) and self.s[self.i] != '"':
                    d = self.s[self.i]
                    if d == "\\" and self.i + 1 < len(self.s):
                        buf.append(self.s[self.i + 1])
                        self.i += 2
                    elif d == "$" and self._peek(2) == "$(":
                        self.i += 2
                        self._substitution(self._read_balanced_subst())
                        dynamic = True
                        buf.append("$")
                    elif d == "`":
                        self.i += 1
                        self._substitution(self._read_backtick())
                        dynamic = True
                        buf.append("`")
                    else:
                        if d == "$":
                            dynamic = True
                        buf.append(d)
                        self.i += 1
                self.i += 1
            elif c == "$" and self._peek(2) == "$(":
                self.i += 2
                self._substitution(self._read_balanced_subst())
                dynamic = True
                buf.append("$")
            elif c == "`":
                self.i += 1
                self._substitution(self._read_backtick())
                dynamic = True
                buf.append("`")
            else:
                if c == "$":
                    dynamic = True
                buf.append(c)
                self.i += 1
        return Word("".join(buf), dynamic)

    def _skip_heredoc_bodies(self) -> None:
        """At a newline: skip the bodies of here-documents opened on this line."""
        for delim, strip_tabs in self.pending_heredocs:
            while self.i < len(self.s):
                end = self.s.find("\n", self.i)
                end = len(self.s) if end == -1 else end
                line = self.s[self.i : end]
                self.i = end + 1
                if (line.lstrip("\t") if strip_tabs else line) == delim:
                    break
        self.pending_heredocs = []

    # -- main loop ------------------------------------------------------------
    def parse(self) -> list[SimpleCommand]:
        cmd = SimpleCommand()
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t":
                self.i += 1
                continue
            if c == "#" and (self.i == 0 or self.s[self.i - 1] in " \t\n;&|()"):
                end = self.s.find("\n", self.i)
                self.i = len(self.s) if end == -1 else end
                continue
            if self._peek(2) == "\\\n":
                self.i += 2
                continue
            # File-descriptor prefix of a redirection, e.g. 2> or 1>>.
            m = re.match(r"\d+(?=[<>])", self.s[self.i :])
            if m:
                self.i += m.end()
            op = next((o for o in REDIRECT_OPS if self.s.startswith(o, self.i)), None)
            if op:
                self.i += len(op)
                while self._peek() in (" ", "\t"):
                    self.i += 1
                target = self._read_word()
                if op in ("<<", "<<-"):
                    self.pending_heredocs.append((target.text, op == "<<-"))
                else:
                    cmd.redirects.append((op, target))
                continue
            sep = next((o for o in SEPARATORS if self.s.startswith(o, self.i)), None)
            if sep:
                self.i += len(sep)
                if cmd.words or cmd.redirects:
                    self.commands.append(cmd)
                cmd = SimpleCommand()
                if sep in ("(", ")"):
                    self.commands.append(SimpleCommand(marker=sep))
                if sep == "\n" and self.pending_heredocs:
                    self._skip_heredoc_bodies()
                continue
            cmd.words.append(self._read_word())
        if cmd.words or cmd.redirects:
            self.commands.append(cmd)
        return self.commands


def parse_shell(text: str) -> list[SimpleCommand]:
    return ShellParser(text).parse()


# --------------------------------------------------------------------------
# Bash command checks
# --------------------------------------------------------------------------

KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}", "time", "case", "esac"}
WRAPPERS = {"sudo", "nohup", "nice", "command", "builtin", "exec", "stdbuf", "ionice", "doas"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")

# Commands whose every positional argument is a path they create, change or delete.
ALL_ARGS_WRITERS = {"rm", "rmdir", "touch", "mkdir", "truncate", "shred", "unlink", "mv"}
# Commands that write their last positional argument (or -t DIR).
DEST_WRITERS = {"cp", "install", "ln", "rsync"}
# Commands that first take a mode/owner, then paths.
MODE_WRITERS = {"chmod", "chown", "chgrp"}
# Options that take a separate value, per command (short and long forms).
VALUE_OPTS = {
    "truncate": {"-s", "--size", "-r", "--reference"},
    "mkdir": {"-m", "--mode"},
    "touch": {"-d", "--date", "-t", "-r", "--reference"},
    "install": {"-m", "--mode", "-o", "--owner", "-g", "--group", "-S", "--suffix"},
    "cp": {"-S", "--suffix"},
    "mv": {"-S", "--suffix"},
    "ln": {"-S", "--suffix"},
    "shred": {"-n", "--iterations", "-s", "--size"},
    "tee": set(),
}
ALWAYS_DENIED = {
    "claude": "starting another Claude Code session would bypass the agent's scope",
    "patch": "patch can write any file; edit in-scope files with the Edit tool instead",
    "PowerShell": "PowerShell is not available to this agent",
}


def _positionals(args: list[Word], value_opts: set[str]) -> list[Word]:
    out: list[Word] = []
    skip = False
    end_of_opts = False
    for w in args:
        if skip:
            skip = False
            continue
        if not end_of_opts and w.text == "--":
            end_of_opts = True
            continue
        if not end_of_opts and w.text.startswith("-") and w.text != "-":
            if w.text in value_opts:
                skip = True
            continue
        out.append(w)
    return out


def _check_word(w: Word, cwd: str | None, ctx: Context, action: str) -> None:
    if w.dynamic:
        raise Denied(f"{action}: cannot verify the target {w.text!r} because it contains a variable or command substitution")
    check_path(w.text, cwd, ctx, action)


class BashChecker:
    def __init__(self, ctx: Context, cwd: str | None) -> None:
        self.ctx = ctx
        self.cwd = cwd

    def check(self, command: str, depth: int = 0) -> None:
        if depth > 5:
            raise Denied("command is nested too deeply to verify")
        stack: list[str | None] = []
        for cmd in parse_shell(command):
            if cmd.marker == "(":
                stack.append(self.cwd)  # a subshell's cd does not leak out
            elif cmd.marker == ")":
                self.cwd = stack.pop() if stack else None
            else:
                self._check_simple(cmd, depth)

    def _check_simple(self, cmd: SimpleCommand, depth: int) -> None:
        for op, target in cmd.redirects:
            if op in ("<", "<&", "<<<"):
                continue
            if op == ">&" and (target.text.isdigit() or target.text == "-"):
                continue
            _check_word(target, self.cwd, self.ctx, f"redirection {op} {target.text}")

        words = list(cmd.words)
        while words and (words[0].text in KEYWORDS or ASSIGNMENT.match(words[0].text)):
            words.pop(0)
        if not words:
            return
        self._check_argv(words, depth, unknown_args=False)

    def _check_argv(self, words: list[Word], depth: int, unknown_args: bool) -> None:
        while words:
            name = os.path.basename(words[0].text)
            if name in WRAPPERS:
                words = words[1:]
            elif name == "env":
                words = words[1:]
                while words and (words[0].text.startswith("-") or ASSIGNMENT.match(words[0].text)):
                    words = words[1:]
            elif name == "timeout":
                rest = _positionals(words[1:], {"-s", "--signal", "-k", "--kill-after"})
                words = rest[1:]
            elif name == "xargs":
                words = _positionals(words[1:], {"-I", "-n", "-L", "-P", "-d", "-a", "-E", "-s"})
                unknown_args = True
            else:
                break
        if not words:
            return
        name = os.path.basename(words[0].text)
        args = words[1:]
        ctx, cwd = self.ctx, self.cwd

        if name in ALWAYS_DENIED:
            raise Denied(f"{name}: {ALWAYS_DENIED[name]}")
        if name in ("cd", "pushd"):
            pos = _positionals(args, set())
            if not pos:
                self.cwd = os.path.expanduser("~")
            elif pos[0].dynamic or pos[0].text == "-":
                self.cwd = None
            else:
                try:
                    self.cwd = resolve(pos[0].text, cwd)
                except Denied:
                    self.cwd = None
            return
        if name == "popd":
            self.cwd = None
            return
        if name in SHELLS:
            for idx, w in enumerate(args):
                if w.text == "-c" or (w.text.startswith("-") and not w.text.startswith("--") and "c" in w.text):
                    if idx + 1 < len(args):
                        if args[idx + 1].dynamic:
                            raise Denied(f"{name} -c: cannot verify a command built from variables")
                        self.check(args[idx + 1].text, depth + 1)
                    return
            if not _positionals(args, {"-o", "+o", "-O", "+O"}):
                raise Denied(f"{name}: cannot verify commands read from standard input")
            return  # running a script file: residual risk, see ADR 0008
        if name == "eval":
            self.check(" ".join(w.text for w in args), depth + 1)
            return
        if name == "git":
            self._check_git(args)
            return

        is_writer = (
            name in ALL_ARGS_WRITERS
            or name in DEST_WRITERS
            or name in MODE_WRITERS
            or name in ("tee", "dd")
            or (name == "sed" and _sed_in_place(args))
            or (name == "perl" and _perl_in_place(args))
        )
        if not is_writer:
            return
        if unknown_args:
            raise Denied(f"xargs {name}: cannot verify the files it would write")

        action = name
        if name in ALL_ARGS_WRITERS or name == "tee":
            for w in _positionals(args, VALUE_OPTS.get(name, set())):
                if name == "tee" and w.text == "-":
                    continue
                _check_word(w, cwd, ctx, action)
        elif name in MODE_WRITERS:
            pos = _positionals(args, set())
            if any(a.text.startswith("--reference") for a in args):
                targets = pos
            else:
                targets = pos[1:]
            for w in targets:
                _check_word(w, cwd, ctx, action)
        elif name in DEST_WRITERS:
            target_dir = _option_value(args, "-t", "--target-directory")
            if target_dir is not None:
                _check_word(target_dir, cwd, ctx, action)
            else:
                pos = _positionals(args, VALUE_OPTS.get(name, set()) | {"-t", "--target-directory"})
                if pos:
                    _check_word(pos[-1], cwd, ctx, action)
        elif name == "dd":
            for w in args:
                if w.text.startswith("of="):
                    _check_word(Word(w.text[3:], w.dynamic), cwd, ctx, "dd of=")
        elif name == "sed":
            for w in _sed_files(args):
                _check_word(w, cwd, ctx, "sed -i")
        elif name == "perl":
            for w in _perl_files(args):
                _check_word(w, cwd, ctx, "perl -i")

    # -- git -----------------------------------------------------------------
    def _check_git(self, args: list[Word]) -> None:
        ctx = self.ctx
        cwd = self.cwd
        i = 0
        while i < len(args) and args[i].text.startswith("-"):
            opt = args[i].text
            if opt == "-C" and i + 1 < len(args):
                target = args[i + 1]
                cwd = None if target.dynamic else resolve(target.text, cwd)
                i += 2
            elif opt in ("-c", "--git-dir", "--work-tree", "--namespace"):
                if opt in ("--git-dir", "--work-tree"):
                    raise Denied(f"git {opt}: cannot verify which work tree is written")
                i += 2
            elif opt.startswith(("--git-dir=", "--work-tree=")):
                raise Denied(f"git {opt.split('=')[0]}: cannot verify which work tree is written")
            else:
                i += 1
        if i >= len(args):
            return
        sub = args[i].text
        rest = args[i + 1 :]

        if sub in ("add", "stage"):
            self._git_add(rest, cwd)
        elif sub == "commit":
            self._git_commit(rest, cwd)
        elif sub in ("mv", "rm"):
            for w in _positionals(rest, set()):
                _check_word(w, cwd, ctx, f"git {sub}")
        elif sub in ("apply", "am"):
            raise Denied(f"git {sub}: applying patches can write any file")
        elif sub == "restore":
            for w in _positionals(rest, {"-s", "--source"}):
                _check_word(w, cwd, ctx, "git restore")
        elif sub == "checkout":
            words = [w.text for w in rest]
            if "--" in words:
                for w in rest[words.index("--") + 1 :]:
                    _check_word(w, cwd, ctx, "git checkout --")

    def _git_add(self, rest: list[Word], cwd: str | None) -> None:
        if not cwd:
            raise Denied("git add: cannot verify the files it would stage (unknown working directory)")
        if any(w.dynamic for w in rest):
            raise Denied("git add: cannot verify pathspecs that contain variables or substitutions")
        opts = [w.text for w in rest if w.text not in ("-n", "--dry-run")]
        proc = _git(["add", "--dry-run", *opts], cwd)
        if proc.returncode != 0:
            # Fall back to checking the pathspecs as paths.
            for w in _positionals(rest, {"--chmod", "--pathspec-from-file"}):
                _check_word(w, cwd, self.ctx, "git add")
            return
        repo = repo_of(_existing_ancestor(os.path.realpath(cwd)), self.ctx)
        for line in proc.stdout.splitlines():
            m = re.match(r"^(?:add|remove) '(.*)'$", line)
            if m:
                self._check_git_file(m.group(1), repo, "git add")

    def _git_commit(self, rest: list[Word], cwd: str | None) -> None:
        if not cwd:
            raise Denied("git commit: cannot verify the staged files (unknown working directory)")
        value_opts = set("mFCct") | {"S"}
        long_value = {"--message", "--file", "--reuse-message", "--reedit-message", "--author", "--date",
                      "--template", "--fixup", "--squash", "--cleanup", "--trailer", "--pathspec-from-file"}
        commit_all = False
        pathspecs: list[Word] = []
        skip = False
        end_opts = False
        for w in rest:
            t = w.text
            if skip:
                skip = False
                continue
            if end_opts or not t.startswith("-") or t == "-":
                pathspecs.append(w)
            elif t == "--":
                end_opts = True
            elif t.startswith("--"):
                if t in ("--all",):
                    commit_all = True
                elif t in long_value:
                    skip = True
                elif t.startswith("--pathspec-from-file"):
                    raise Denied("git commit --pathspec-from-file: cannot verify the committed files")
            else:
                for j, ch in enumerate(t[1:]):
                    if ch == "a":
                        commit_all = True
                    if ch in value_opts:
                        if j == len(t) - 2:
                            skip = ch != "S"
                        break
        repo = repo_of(_existing_ancestor(os.path.realpath(cwd)), self.ctx)
        staged = _git(["diff", "--cached", "--name-only"], cwd).stdout.splitlines()
        for f in staged:
            self._check_git_file(f, repo, "git commit")
        if commit_all:
            for f in _git(["diff", "--name-only"], cwd).stdout.splitlines():
                self._check_git_file(f, repo, "git commit -a")
        for w in pathspecs:
            _check_word(w, cwd, self.ctx, "git commit")

    def _check_git_file(self, rel: str, repo: tuple[str, str] | None, action: str) -> None:
        if repo is None:
            raise Denied(f"{action}: not inside the FitWise repository")
        check_path(os.path.join(repo[0], rel), None, self.ctx, action)


def _option_value(args: list[Word], short: str, long: str) -> Word | None:
    for idx, w in enumerate(args):
        if w.text == short or w.text == long:
            return args[idx + 1] if idx + 1 < len(args) else None
        if w.text.startswith(long + "="):
            return Word(w.text[len(long) + 1 :], w.dynamic)
    return None


def _sed_options(args: list[Word]) -> tuple[bool, bool, list[Word]]:
    """Return (in_place, has_script_option, positional words) for a sed argv."""
    in_place = has_script = False
    pos: list[Word] = []
    skip = False
    for w in args:
        t = w.text
        if skip:
            skip = False
            continue
        if t.startswith("--"):
            if t.startswith("--in-place"):
                in_place = True
            elif t in ("--expression", "--file"):
                has_script = skip = True
            elif t.startswith(("--expression=", "--file=")):
                has_script = True
            elif t == "--line-length":
                skip = True
        elif t.startswith("-") and t != "-":
            for k, ch in enumerate(t[1:]):
                if ch == "i":  # the rest of the bundle is the backup suffix
                    in_place = True
                    break
                if ch in "efl":
                    has_script = has_script or ch in "ef"
                    skip = k == len(t) - 2  # value is the next word
                    break
        else:
            pos.append(w)
    return in_place, has_script, pos


def _sed_in_place(args: list[Word]) -> bool:
    return _sed_options(args)[0]


def _sed_files(args: list[Word]) -> list[Word]:
    _, has_script, pos = _sed_options(args)
    return pos if has_script else pos[1:]


def _perl_in_place(args: list[Word]) -> bool:
    return any(w.text.startswith("-") and not w.text.startswith("--") and "i" in w.text[1:].split("e")[0]
               for w in args)


def _perl_files(args: list[Word]) -> list[Word]:
    has_e = False
    pos: list[Word] = []
    skip = False
    for w in args:
        if skip:
            skip = False
            continue
        t = w.text
        if t.startswith("-") and not t.startswith("--") and t != "-":
            if t.endswith(("e", "E")):
                has_e = True
                skip = True
            continue
        pos.append(w)
    return pos if has_e else pos[1:]


# --------------------------------------------------------------------------
# Hook entry point
# --------------------------------------------------------------------------


def decide(event: dict[str, Any]) -> str | None:
    """Return a denial message, or None when the tool call may proceed."""
    agent = str(event.get("agent_type") or "").strip().lower()
    scopes = SCOPES.get(agent)
    if scopes is None:
        return None  # main session, engineer, devops or any other agent

    ctx = Context(
        agent=agent,
        scopes=scopes,
        project_dir=os.environ.get("CLAUDE_PROJECT_DIR") or event.get("cwd"),
        scratchpad=event.get("scratchpad_dir"),
    )
    tool = event.get("tool_name", "")
    tool_input = event.get("tool_input") or {}
    try:
        if tool in FILE_TOOLS:
            path = tool_input.get(FILE_TOOLS[tool]) or tool_input.get("file_path")
            if not path:
                raise Denied(f"{tool}: no target path")
            check_path(str(path), event.get("cwd"), ctx, tool)
        elif tool == "Bash":
            BashChecker(ctx, event.get("cwd")).check(str(tool_input.get("command", "")))
        elif tool == "PowerShell":
            raise Denied(f"PowerShell: {ALWAYS_DENIED['PowerShell']}")
    except Denied as exc:
        return (
            f"FitWise scope guard blocked this {tool} call. The {agent} agent may only write under "
            f"{ctx.scope_text()} (docs/team.md, ADR 0008). Reason: {exc}. {HINTS[agent]}"
        )
    except Exception as exc:  # noqa: BLE001 - fail closed for restricted agents
        return f"FitWise scope guard could not verify this {tool} call ({type(exc).__name__}: {exc}); blocked for the {agent} agent."
    return None


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except (ValueError, OSError) as exc:
        print(f"FitWise scope guard: unreadable hook input ({exc}); blocking.", file=sys.stderr)
        return 2
    if not isinstance(event, dict):
        print("FitWise scope guard: unreadable hook input (not a JSON object); blocking.", file=sys.stderr)
        return 2
    reason = decide(event)
    if reason:
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            },
            sys.stdout,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
