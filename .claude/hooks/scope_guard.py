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

import glob
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


class Unexpandable(Denied):
    """A brace expansion the checks don't model (sequences, empty results)."""


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
    # marks[i] is True when text[i] was unquoted (subject to brace expansion and
    # globbing). Empty means "all unquoted", for words built by the checks.
    marks: list[bool] = field(default_factory=list)

    def unquoted(self) -> list[bool]:
        return self.marks if len(self.marks) == len(self.text) else [True] * len(self.text)


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
        marks: list[bool] = []
        dynamic = False

        def add(text: str, unquoted: bool) -> None:
            buf.append(text)
            marks.extend([unquoted] * len(text))

        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t\n;&|()<>":
                break
            if c == "\\":
                if self._peek(2) == "\\\n":
                    self.i += 2
                    continue
                add(self.s[self.i + 1 : self.i + 2], False)
                self.i += 2
            elif c == "'":
                end = self.s.find("'", self.i + 1)
                end = len(self.s) if end == -1 else end
                add(self.s[self.i + 1 : end], False)
                self.i = end + 1
            elif c == '"':
                self.i += 1
                while self.i < len(self.s) and self.s[self.i] != '"':
                    d = self.s[self.i]
                    if d == "\\" and self.i + 1 < len(self.s):
                        add(self.s[self.i + 1], False)
                        self.i += 2
                    elif d == "$" and self._peek(2) == "$(":
                        self.i += 2
                        self._substitution(self._read_balanced_subst())
                        dynamic = True
                        add("$", False)
                    elif d == "`":
                        self.i += 1
                        self._substitution(self._read_backtick())
                        dynamic = True
                        add("`", False)
                    else:
                        if d == "$":
                            dynamic = True
                        add(d, False)
                        self.i += 1
                self.i += 1
            elif c == "$" and self._peek(2) == "$(":
                self.i += 2
                self._substitution(self._read_balanced_subst())
                dynamic = True
                add("$", True)
            elif c == "`":
                self.i += 1
                self._substitution(self._read_backtick())
                dynamic = True
                add("`", True)
            else:
                if c == "$":
                    dynamic = True
                add(c, True)
                self.i += 1
        return Word("".join(buf), dynamic, marks)

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

KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}", "case", "esac"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
MAX_EXPANSIONS = 256


@dataclass(frozen=True)
class OptSpec:
    """Options of a wrapper command, which runs the command that follows them.

    ``flags``/``values``: short option letters without/with a value.
    ``optional``: short options whose value may only be attached (``xargs -i{}``).
    ``chdir``/``output``: options whose value is a new working directory / a file it writes.
    ``deny``: options that make the wrapped command impossible to verify.
    ``positionals``: words between the options and the command (``timeout DURATION``).
    Any other option is unknown, and the call is denied (fail closed).
    """

    flags: str = ""
    values: str = ""
    optional: str = ""
    long_flags: frozenset[str] = frozenset()
    long_values: frozenset[str] = frozenset()
    chdir: frozenset[str] = frozenset()
    output: frozenset[str] = frozenset()
    deny: frozenset[str] = frozenset()
    positionals: int = 0
    numeric: bool = False  # accepts -N (nice -10)


def _f(*names: str) -> frozenset[str]:
    return frozenset(names)


WRAPPERS: dict[str, OptSpec] = {
    "sudo": OptSpec(
        flags="AbEHiKklnPSsVv", values="CDghpRrTtUu",
        long_flags=_f("--askpass", "--background", "--preserve-env", "--set-home", "--login", "--remove-timestamp",
                      "--reset-timestamp", "--list", "--non-interactive", "--preserve-groups", "--stdin", "--shell",
                      "--validate", "--bell"),
        long_values=_f("--close-from", "--chdir", "--group", "--host", "--prompt", "--chroot", "--role", "--type",
                       "--command-timeout", "--other-user", "--user"),
        chdir=_f("-D", "--chdir"), deny=_f("-e", "--edit", "-R", "--chroot")),
    "doas": OptSpec(flags="Lns", values="Cu"),
    "nice": OptSpec(values="n", long_values=_f("--adjustment"), numeric=True),
    "nohup": OptSpec(),
    "setsid": OptSpec(flags="cfw", long_flags=_f("--ctty", "--fork", "--wait")),
    "command": OptSpec(flags="pvV"),
    "builtin": OptSpec(),
    "exec": OptSpec(flags="cl", values="a"),
    "busybox": OptSpec(),
    "stdbuf": OptSpec(values="ioe", long_values=_f("--input", "--output", "--error")),
    "ionice": OptSpec(flags="t", values="cnpPu",
                      long_flags=_f("--ignore"), long_values=_f("--class", "--classdata", "--pid", "--pgid", "--uid")),
    "env": OptSpec(flags="i0v", values="uCS",
                   long_flags=_f("--ignore-environment", "--null", "--debug"),
                   long_values=_f("--unset", "--chdir", "--split-string"),
                   chdir=_f("-C", "--chdir"), deny=_f("-S", "--split-string")),
    "timeout": OptSpec(flags="v", values="sk", long_flags=_f("--preserve-status", "--foreground", "--verbose"),
                       long_values=_f("--signal", "--kill-after"), positionals=1),
    # The bash keyword (time -p) and GNU time (-o FILE writes FILE).
    "time": OptSpec(flags="pvaq", values="of", long_flags=_f("--portability", "--verbose", "--append", "--quiet"),
                    long_values=_f("--output", "--format"), output=_f("-o", "--output")),
    "xargs": OptSpec(
        flags="0prtxo", values="adEILnPs", optional="eil",
        long_flags=_f("--null", "--interactive", "--no-run-if-empty", "--verbose", "--exit", "--show-limits",
                      "--open-tty"),
        long_values=_f("--arg-file", "--delimiter", "--max-lines", "--max-args", "--max-procs", "--max-chars",
                       "--process-slot-var"),
        # Optional-value long options only take their value with "=".
        chdir=_f()),
}
# Long options that take an optional value, attached with "=" only.
OPTIONAL_LONG = {"xargs": {"--eof", "--replace"}, "sudo": {"--preserve-env"}}

# Commands whose every positional argument is a path they create, change or delete.
ALL_ARGS_WRITERS = {"rm", "rmdir", "touch", "mkdir", "truncate", "shred", "unlink", "mv", "link"}
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
    "sudoedit": "sudoedit can write any file",
    "su": "su runs a command that cannot be verified",
    "runuser": "runuser runs a command that cannot be verified",
    "parallel": "parallel builds commands from its input, so the files it writes cannot be verified",
}
# find actions that run a command or write files.
FIND_EXEC = {"-exec", "-execdir", "-ok", "-okdir"}
FIND_OUTPUT = {"-fprint": 1, "-fprint0": 1, "-fls": 1, "-fprintf": 2}
# git subcommands that the checks verify from their arguments; with unknown (xargs/find) arguments they are denied.
GIT_WRITE_SUBCOMMANDS = {"add", "stage", "commit", "mv", "rm", "restore", "checkout", "apply", "am"}


def _short_has(word: str, letter: str) -> bool:
    """True if a short-option bundle such as -sf contains letter."""
    return word.startswith("-") and not word.startswith("--") and letter in word[1:]


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


# -- brace expansion and globbing --------------------------------------------


def _brace_alternatives(text: str, marks: list[bool]) -> tuple[int, int, list[int]] | None:
    """Find the first unquoted {a,b} group: (open index, close index, top-level comma indexes)."""
    for start, ch in enumerate(text):
        if ch != "{" or not marks[start] or (start and text[start - 1] == "$" and marks[start - 1]):
            continue
        depth = 0
        commas: list[int] = []
        for k in range(start + 1, len(text)):
            if not marks[k]:
                continue
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                if depth == 0:
                    inner = text[start + 1 : k]
                    if commas:
                        return start, k, commas
                    if re.fullmatch(r"(-?\d+|[A-Za-z])\.\.(-?\d+|[A-Za-z])(\.\.-?\d+)?", inner):
                        raise Unexpandable(f"cannot verify the brace sequence {{{inner}}}; list the paths explicitly")
                    break
                depth -= 1
            elif text[k] == "," and depth == 0:
                commas.append(k)
    return None


def brace_expand(word: Word) -> list[Word]:
    """Expand unquoted {a,b} groups like bash does; quoted braces stay literal."""
    pending = [(word.text, word.unquoted())]
    done: list[Word] = []
    while pending:
        text, marks = pending.pop(0)
        found = _brace_alternatives(text, marks)
        if found is None:
            done.append(Word(text, word.dynamic, marks))
        else:
            start, close, commas = found
            bounds = [start, *commas, close]
            for n in range(len(bounds) - 1):
                a, b = bounds[n], bounds[n + 1]
                pending.append((text[:start] + text[a + 1 : b] + text[close + 1 :],
                                marks[:start] + marks[a + 1 : b] + marks[close + 1 :]))
        if len(done) + len(pending) > MAX_EXPANSIONS:
            raise Denied(f"the brace expansion in {word.text!r} produces too many words to verify")
    if len(done) > 1 and any(not w.text for w in done):
        # bash drops empty results, which shifts positional arguments; don't try to model that.
        raise Unexpandable(f"cannot verify the brace expansion {word.text!r} because it produces empty words")
    return done


def expand_words(words: list[Word]) -> tuple[list[Word], bool]:
    """Brace-expand an argv. The flag is True when a word could not be expanded reliably;
    the caller then treats the arguments as unknown (writers are denied, readers pass)."""
    out: list[Word] = []
    unknown = False
    for w in words:
        try:
            out.extend(brace_expand(w))
        except Unexpandable:
            out.append(w)
            unknown = True
    return out, unknown


def _glob_matches(w: Word, cwd: str | None) -> list[str]:
    """Paths an unquoted glob in w matches (bash replaces the word with them)."""
    marks = w.unquoted()
    if not any(m and c in "*?[" for c, m in zip(w.text, marks)):
        return []
    pattern = "".join(c if m else glob.escape(c) for c, m in zip(w.text, marks))
    pattern = os.path.expanduser(pattern)
    if not os.path.isabs(pattern):
        if not cwd:
            raise Denied(f"cannot verify the glob {w.text!r} (unknown working directory)")
        pattern = os.path.join(cwd, pattern)
    matches = glob.glob(pattern)
    if len(matches) > MAX_EXPANSIONS:
        raise Denied(f"the glob {w.text!r} matches too many files to verify")
    return matches


def _check_word(w: Word, cwd: str | None, ctx: Context, action: str) -> None:
    if w.dynamic:
        raise Denied(f"{action}: cannot verify the target {w.text!r} because it contains a variable or command substitution")
    for expanded in brace_expand(w):
        check_path(expanded.text, cwd, ctx, action)
        for match in _glob_matches(expanded, cwd):
            check_path(match, cwd, ctx, action)


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
        expanded, unknown = expand_words(words)
        self._check_argv(expanded, depth, unknown_args=unknown)

    def _strip_wrapper(self, name: str, words: list[Word]) -> list[Word]:
        """Drop a wrapper's own options (and env assignments); return the wrapped command."""
        spec = WRAPPERS[name]
        optional_long = OPTIONAL_LONG.get(name, set())
        i = 0
        while i < len(words):
            w = words[i]
            t = w.text
            if name == "env" and ASSIGNMENT.match(t):
                i += 1
                continue
            if t == "--":
                i += 1
                break
            if t == "-" and name == "env":
                i += 1
                continue
            if not t.startswith("-") or t == "-":
                break
            value: Word | None = None
            opt = t
            if t.startswith("--"):
                opt, eq, val = t.partition("=")
                if opt in spec.long_values:
                    if eq:
                        value = Word(val, w.dynamic)
                    elif i + 1 < len(words):
                        i += 1
                        value = words[i]
                elif opt in spec.long_flags or opt in optional_long:
                    pass
                else:
                    raise Denied(f"{name} {opt}: unknown option, so the wrapped command cannot be verified")
                self._wrapper_option(name, spec, opt, value)
                i += 1
                continue
            if spec.numeric and re.fullmatch(r"-\d+", t):
                i += 1
                continue
            k = 1
            while k < len(t):
                ch = t[k]
                opt = "-" + ch
                if ch in spec.optional:
                    self._wrapper_option(name, spec, opt, None)
                    break  # the rest of the bundle is the optional value
                if ch in spec.values:
                    if k + 1 < len(t):
                        value = Word(t[k + 1 :], w.dynamic)
                    elif i + 1 < len(words):
                        i += 1
                        value = words[i]
                    self._wrapper_option(name, spec, opt, value)
                    break
                if ch not in spec.flags:
                    raise Denied(f"{name} {opt}: unknown option, so the wrapped command cannot be verified")
                self._wrapper_option(name, spec, opt, None)
                k += 1
            i += 1
        rest = words[i:]
        return rest[spec.positionals :]

    def _wrapper_option(self, name: str, spec: OptSpec, opt: str, value: Word | None) -> None:
        if opt in spec.deny:
            raise Denied(f"{name} {opt}: the wrapped command cannot be verified")
        if opt in spec.output and value is not None:
            _check_word(value, self.cwd, self.ctx, f"{name} {opt}")
        if opt in spec.chdir:
            if value is None or value.dynamic:
                self.cwd = None
            else:
                try:
                    self.cwd = resolve(value.text, self.cwd)
                except Denied:
                    self.cwd = None

    def _check_argv(self, words: list[Word], depth: int, unknown_args: bool) -> None:
        saved_cwd = self.cwd
        chdir_by_wrapper = False
        while words:
            name = os.path.basename(words[0].text)
            if name not in WRAPPERS:
                break
            before = self.cwd
            words = self._strip_wrapper(name, words[1:])
            chdir_by_wrapper = chdir_by_wrapper or self.cwd != before
            if name == "xargs":
                unknown_args = True
        try:
            self._check_command(words, depth, unknown_args)
        finally:
            if chdir_by_wrapper:
                self.cwd = saved_cwd  # env -C / sudo -D only change the wrapped command's directory

    def _check_command(self, words: list[Word], depth: int, unknown_args: bool) -> None:
        if not words:
            return
        name = os.path.basename(words[0].text)
        args = words[1:]
        ctx, cwd = self.ctx, self.cwd

        if name in ALWAYS_DENIED:
            raise Denied(f"{name}: {ALWAYS_DENIED[name]}")
        if unknown_args and (name in SHELLS or name in ("eval", "find")):
            raise Denied(f"{name}: cannot verify a command whose arguments come from xargs, find or a brace expansion")
        if name in ("cd", "pushd"):
            pos = _positionals(args, set())
            if not pos:
                self.cwd = os.path.expanduser("~")
            elif pos[0].dynamic or pos[0].text == "-" or len(pos) > 1 or _glob_matches(pos[0], cwd):
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
            self._check_git(args, unknown_args)
            return
        if name == "find":
            self._check_find(args, depth)
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
            raise Denied(f"{name}: cannot verify the files it would write (arguments from xargs, find -exec or a brace expansion)")

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
            self._check_dest_writer(name, args)
        elif name == "dd":
            for w in args:
                if w.text.startswith("of="):
                    _check_word(Word(w.text[3:], w.dynamic, w.marks[3:]), cwd, ctx, "dd of=")
        elif name == "sed":
            for w in _sed_files(args):
                _check_word(w, cwd, ctx, "sed -i")
        elif name == "perl":
            for w in _perl_files(args):
                _check_word(w, cwd, ctx, "perl -i")

    def _check_dest_writer(self, name: str, args: list[Word]) -> None:
        ctx, cwd = self.ctx, self.cwd
        texts = [a.text for a in args]
        target_dir = _option_value(args, "-t", "--target-directory")
        pos = _positionals(args, VALUE_OPTS.get(name, set()) | {"-t", "--target-directory"})
        if name == "install" and any(t == "--directory" or _short_has(t, "d") for t in texts):
            for w in pos:  # install -d creates every directory it is given
                _check_word(w, cwd, ctx, "install -d")
            return
        if target_dir is not None:
            dests, sources = [target_dir], pos
        elif len(pos) == 1 and name == "ln":
            # ln TARGET creates a link named after TARGET in the working directory.
            dests, sources = [Word(os.path.basename(pos[0].text.rstrip("/")), pos[0].dynamic)], pos
        else:
            dests, sources = pos[-1:], pos[:-1]
        for w in dests:
            _check_word(w, cwd, ctx, action=name)
        # A hard link shares the file's content: writing the in-scope name changes the original.
        hard_link = (name == "ln" and not any(t in ("--symbolic",) or _short_has(t, "s") for t in texts)) or (
            name == "cp" and any(t == "--link" or (_short_has(t, "l") and not t.startswith("-S")) for t in texts))
        if hard_link:
            for w in sources:
                _check_word(w, cwd, ctx, f"{name} (hard link from)")

    # -- find ----------------------------------------------------------------
    def _check_find(self, args: list[Word], depth: int) -> None:
        i, follow = 0, False
        while i < len(args):
            t = args[i].text
            if t in ("-H", "-P"):
                i += 1
            elif t == "-L":
                follow, i = True, i + 1
            elif t == "-D":
                i += 2
            elif re.fullmatch(r"-O\d*", t):
                i += 1
            else:
                break
        starts: list[Word] = []
        while i < len(args) and not (args[i].text.startswith("-") or args[i].text in ("(", ")", "!", ",")):
            starts.append(args[i])
            i += 1
        if not starts:
            starts = [Word(".")]
        expr = args[i:]
        follow = follow or any(w.text == "-follow" for w in expr)
        j = 0
        while j < len(expr):
            t = expr[j].text
            if t in FIND_EXEC:
                k = j + 1
                while k < len(expr) and expr[k].text not in (";", "+"):
                    k += 1
                saved = self.cwd
                if t in ("-execdir", "-okdir"):
                    self.cwd = None  # runs in each file's directory
                try:
                    # The command gets the found files as arguments, so any writer is denied.
                    self._check_argv(expr[j + 1 : k], depth + 1, unknown_args=True)
                finally:
                    self.cwd = saved
                j = k + 1
            elif t == "-delete":
                if follow:
                    raise Denied("find -L/-follow -delete: cannot verify which files it deletes")
                for w in starts:
                    _check_word(w, self.cwd, self.ctx, "find -delete")
                j += 1
            elif t in FIND_OUTPUT:
                if j + 1 < len(expr):
                    _check_word(expr[j + 1], self.cwd, self.ctx, f"find {t}")
                j += 1 + FIND_OUTPUT[t]
            else:
                j += 1

    # -- git -----------------------------------------------------------------
    def _check_git(self, args: list[Word], unknown_args: bool = False) -> None:
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
        if unknown_args and sub in GIT_WRITE_SUBCOMMANDS:
            raise Denied(f"git {sub}: cannot verify the files it would change (arguments from xargs, find -exec or a brace expansion)")

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
