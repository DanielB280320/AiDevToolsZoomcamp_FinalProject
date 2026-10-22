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

The file tools (Write, Edit, MultiEdit, NotebookEdit) check the target path.
Bash is checked with an **allow-list**: every simple command on the line
(after splitting on ``;`` ``&&`` ``||`` ``|`` newlines, subshells and
command substitution) must be on the agent's per-role allow-list, and
anything the parser cannot confidently understand is DENIED (fail closed).
See docs/adr/0008-enforce-agent-write-scopes-with-a-hook.md for the design
and the residual risks (allow-listed tools such as ``make``/``pytest``/npm
scripts can still run arbitrary repository code; the git-commit check and
owner review are the backstop).

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

ADR_HINT = "see ADR 0008 to request adding it (ADR + owner approval)"


class Denied(Exception):
    """Raised with a human-readable reason when a call is out of scope or not allowed."""


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

    def all_unquoted(self) -> bool:
        return all(self.unquoted())


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
# Allow-list constants
# --------------------------------------------------------------------------

KEYWORDS = {"if", "then", "else", "elif", "fi", "do", "done", "while", "until", "!", "{", "}",
            "case", "esac", "for", "select", "in", "function"}
# Loop headers (for/select NAME in LIST) do not run commands; they are skipped whole.
LOOP_HEADERS = {"for", "select"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
MAX_EXPANSIONS = 256

# A literal command name: no variable/substitution, no quoting, no glob/brace characters.
LITERAL_NAME = re.compile(r"[A-Za-z0-9_./+-]+")

# Read-only commands, allowed for both restricted agents with any arguments.
READ_ONLY = {
    "cat", "head", "tail", "less", "more", "wc", "grep", "egrep", "fgrep", "rg", "jq", "diff",
    "ls", "printf", "echo", "test", "[", "true", "false", "pwd", "basename", "dirname",
    "realpath", "stat", "date", "which", "sleep", "cut", "tr", "comm", "column", "nl",
}
# Read-only commands that can also write through an option; allowed only in read-only form.
GUARDED_READERS = {"sort", "uniq", "sed", "find"}
# Writers allowed only when every target they write is inside the agent's scope.
WRITE_TOOLS = {"mkdir", "touch", "rm", "mv", "cp", "tee"}
# Commands that create links; always denied for restricted agents (they can point out of scope).
LINK_COMMANDS = {"ln", "link"}
# Navigation builtins that change the working directory used for later checks.
NAV = {"cd", "pushd", "popd"}

# QA-only tools (engineers run everything; PM does not run the build tool chain).
QA_TOOLS = {"make", "uv", "uvx", "npm", "npx", "node", "curl"}

# Project scripts each agent may run directly (checked to live under scripts/).
SCRIPTS = {"qa": {"issue-status.sh", "test-hooks.sh"}, "pm": {"issue-status.sh"}}

# git subcommands that only read.
GIT_READONLY = {
    "log", "show", "diff", "status", "blame", "ls-files", "grep", "rev-parse", "branch",
    "remote", "describe", "shortlog", "reflog", "for-each-ref", "symbolic-ref", "cat-file",
    "ls-tree", "tag", "whatchanged", "name-rev", "merge-base", "config", "rev-list",
    "cherry", "range-diff", "show-ref", "var", "count-objects", "verify-commit",
}
# git write subcommands allowed per role (with path/staging checks where relevant).
GIT_WRITE = {
    "qa": {"add", "stage", "commit", "push", "fetch", "worktree", "switch", "checkout", "restore"},
    "pm": {"add", "stage", "commit", "push", "fetch", "worktree", "switch"},
}

NPM_SUBCOMMANDS = {"ci", "test", "run", "run-script", "exec"}
NPX_PACKAGES = {"@redocly/cli", "redocly", "playwright", "@playwright/test", "tsc", "typescript",
                "vitest", "openapi-typescript"}
UV_RUN_TOOLS = {"pytest", "ruff", "mypy", "alembic"}
UVX_TOOLS = {"ruff", "mypy", "openapi-spec-validator"}
MAKE_TARGETS = {"lint", "test", "e2e"}
MAKE_DENY_OPTS = {"-C", "--directory", "-f", "--file", "--makefile", "-o", "--old-file",
                  "-W", "--what-if", "--new-file", "--assume-new", "--eval", "-I", "--include-dir"}
NODE_EVAL_OPTS = {"-e", "--eval", "-p", "--print", "-pe", "--input-type"}
CURL_DENY = {"-o", "--output", "-O", "--remote-name", "--remote-name-all", "--output-dir",
             "--create-dirs", "-J", "--remote-header-name", "-D", "--dump-header", "--trace",
             "--trace-ascii", "--etag-save", "-c", "--cookie-jar", "-K", "--config"}
CURL_VALUE = {"-H", "--header", "-d", "--data", "--data-raw", "--data-binary", "--data-ascii",
              "--data-urlencode", "-X", "--request", "-u", "--user", "-A", "--user-agent",
              "-e", "--referer", "-b", "--cookie", "-F", "--form", "-x", "--proxy", "-m",
              "--max-time", "--connect-timeout", "--retry", "--resolve", "-E", "--cert",
              "--cacert", "--capath", "--key", "-T", "--upload-file", "-w", "--write-out"}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


def _f(*names: str) -> frozenset[str]:
    return frozenset(names)


@dataclass(frozen=True)
class OptSpec:
    """Options of a wrapper command, which runs the command that follows them."""

    flags: str = ""
    values: str = ""
    optional: str = ""
    long_flags: frozenset[str] = frozenset()
    long_values: frozenset[str] = frozenset()
    chdir: frozenset[str] = frozenset()
    output: frozenset[str] = frozenset()
    deny: frozenset[str] = frozenset()
    positionals: int = 0
    numeric: bool = False


# The only wrappers on the allow-list: timeout (bounds an allowed command) and xargs
# (runs an allowed command on stdin arguments, so any writer it runs is denied).
WRAPPERS: dict[str, OptSpec] = {
    "timeout": OptSpec(flags="v", values="sk",
                       long_flags=_f("--preserve-status", "--foreground", "--verbose"),
                       long_values=_f("--signal", "--kill-after"), positionals=1),
    "xargs": OptSpec(
        flags="0prtxo", values="adEILnPs", optional="eil",
        long_flags=_f("--null", "--interactive", "--no-run-if-empty", "--verbose", "--exit",
                      "--show-limits", "--open-tty"),
        long_values=_f("--arg-file", "--delimiter", "--max-lines", "--max-args", "--max-procs",
                       "--max-chars", "--process-slot-var")),
}
OPTIONAL_LONG = {"xargs": {"--eof", "--replace"}}

VALUE_OPTS = {
    "mkdir": {"-m", "--mode", "-Z", "--context"},
    "touch": {"-d", "--date", "-t", "-r", "--reference"},
    "cp": {"-S", "--suffix", "-t", "--target-directory", "--preserve", "--no-preserve",
           "-Z", "--context", "--sparse", "--reflink"},
    "mv": {"-S", "--suffix", "-t", "--target-directory", "-Z", "--context"},
    "tee": set(),
    "rm": set(),
}

_SED_W_CMD = re.compile(r"(?:^|[;{}\n])\s*(?:\d+(?:\s*,\s*\d+)?\s*)?[wWe](?:\s|$)")
_SED_W_FLAG = re.compile(r"s(.).*?\1.*?\1[0-9gpiImMe]*[wWe]")


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


def _option_value(args: list[Word], short: str, long: str) -> Word | None:
    for idx, w in enumerate(args):
        if w.text == short or w.text == long:
            return args[idx + 1] if idx + 1 < len(args) else None
        if w.text.startswith(long + "="):
            return Word(w.text[len(long) + 1 :], w.dynamic)
    return None


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


# --------------------------------------------------------------------------
# Bash allow-list checker
# --------------------------------------------------------------------------


class BashChecker:
    def __init__(self, ctx: Context, cwd: str | None) -> None:
        self.ctx = ctx
        self.cwd = cwd

    @property
    def role(self) -> str:
        return self.ctx.agent

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
            if words[0].text in LOOP_HEADERS:
                return  # "for NAME in LIST" / "select NAME in LIST" run no commands here
            words.pop(0)
        if not words:
            return
        self._require_literal_name(words[0])
        expanded, unknown = expand_words(words)
        self._check_argv(expanded, depth, unknown_args=unknown)

    def _require_literal_name(self, w: Word) -> None:
        if w.dynamic:
            raise Denied(f"the command name {w.text!r} is built from a variable or command substitution and cannot be verified")
        if not w.all_unquoted():
            raise Denied(f"the command name {w.text!r} is quoted or escaped and cannot be verified")
        if w.text != "[" and not LITERAL_NAME.fullmatch(w.text):
            raise Denied(f"the command name {w.text!r} contains special characters and cannot be verified")

    # -- wrapper unwrapping --------------------------------------------------
    def _check_argv(self, words: list[Word], depth: int, unknown_args: bool) -> None:
        while words:
            name = os.path.basename(words[0].text)
            if name not in WRAPPERS:
                break
            self._require_literal_name(words[0])
            words = self._strip_wrapper(name, words[1:])
            if name == "xargs":
                unknown_args = True
        self._check_command(words, depth, unknown_args)

    def _strip_wrapper(self, name: str, words: list[Word]) -> list[Word]:
        spec = WRAPPERS[name]
        optional_long = OPTIONAL_LONG.get(name, set())
        i = 0
        while i < len(words):
            w = words[i]
            t = w.text
            if t == "--":
                i += 1
                break
            if not t.startswith("-") or t == "-":
                break
            if t.startswith("--"):
                opt, eq, _ = t.partition("=")
                if opt in spec.long_values:
                    if not eq and i + 1 < len(words):
                        i += 1
                elif opt in spec.long_flags or opt in optional_long:
                    pass
                else:
                    raise Denied(f"{name} {opt}: unknown option, so the wrapped command cannot be verified")
                i += 1
                continue
            if spec.numeric and re.fullmatch(r"-\d+", t):
                i += 1
                continue
            k = 1
            while k < len(t):
                ch = t[k]
                if ch in spec.optional:
                    break  # the rest of the bundle is the optional value
                if ch in spec.values:
                    if k + 1 >= len(t) and i + 1 < len(words):
                        i += 1
                    break
                if ch not in spec.flags:
                    raise Denied(f"{name} -{ch}: unknown option, so the wrapped command cannot be verified")
                k += 1
            i += 1
        return words[i:][spec.positionals :]

    # -- command dispatch ----------------------------------------------------
    def _check_command(self, words: list[Word], depth: int, unknown_args: bool) -> None:
        if not words:
            return
        self._require_literal_name(words[0])
        name = os.path.basename(words[0].text)
        args = words[1:]

        if name in NAV:
            self._check_nav(name, args)
            return
        if name in READ_ONLY:
            return
        if name == "env":
            if args:
                self._not_allowed("env with arguments")
            return
        if name == "command":
            if args and args[0].text in ("-v", "-V"):
                return
            self._not_allowed(name)
        if name == "sort":
            self._check_sort(args)
            return
        if name == "uniq":
            self._check_uniq(args)
            return
        if name == "sed":
            self._check_sed(args)
            return
        if name == "find":
            self._check_find(args)
            return
        if name in LINK_COMMANDS:
            raise Denied(f"{name}: creating links is not allowed for the {self.role} agent (a link can point out of scope)")
        if name in ("mkdir", "touch", "rm", "mv"):
            self._check_all_args_writer(name, args, unknown_args)
            return
        if name == "cp":
            self._check_cp(args, unknown_args)
            return
        if name == "tee":
            self._check_tee(args, unknown_args)
            return
        if name == "gh":
            return
        if name == "git":
            self._check_git(args, unknown_args)
            return
        if name in SCRIPTS.get(self.role, set()):
            self._check_script(words[0])
            return
        if self.role == "qa" and name in QA_TOOLS:
            getattr(self, f"_check_{name}")(args)
            return
        self._not_allowed(name)

    def _not_allowed(self, what: str) -> None:
        raise Denied(f"{what} is not on the {self.role} allow-list; {ADR_HINT}")

    # -- navigation ----------------------------------------------------------
    def _check_nav(self, name: str, args: list[Word]) -> None:
        if name == "popd":
            self.cwd = None
            return
        pos = _positionals(args, set())
        if not pos:
            self.cwd = os.path.expanduser("~")
        elif pos[0].dynamic or pos[0].text == "-" or len(pos) > 1 or _glob_matches(pos[0], self.cwd):
            self.cwd = None
        else:
            try:
                self.cwd = resolve(pos[0].text, self.cwd)
            except Denied:
                self.cwd = None

    # -- guarded readers -----------------------------------------------------
    def _check_sort(self, args: list[Word]) -> None:
        for w in args:
            t = w.text
            if t in ("-o", "--output") or t.startswith("--output=") or (t.startswith("-o") and t != "-o" and not t.startswith("--")):
                raise Denied(f"sort {t}: writing to a file is not on the {self.role} allow-list; {ADR_HINT}")

    def _check_uniq(self, args: list[Word]) -> None:
        pos = _positionals(args, {"-f", "--skip-fields", "-s", "--skip-chars", "-w", "--check-chars"})
        if len(pos) > 1:
            raise Denied(f"uniq writing to a second file argument is not on the {self.role} allow-list; {ADR_HINT}")

    def _check_sed(self, args: list[Word]) -> None:
        in_place, scripts = _sed_scan(args)
        if in_place:
            raise Denied(f"sed -i: in-place editing is not on the {self.role} allow-list; {ADR_HINT}")
        for s in scripts:
            if _SED_W_CMD.search(s) or _SED_W_FLAG.search(s):
                raise Denied(f"sed w/W/e command: writing or running files from a sed script is not on the {self.role} allow-list; {ADR_HINT}")

    def _check_find(self, args: list[Word]) -> None:
        for w in args:
            t = w.text
            if t in ("-exec", "-execdir", "-ok", "-okdir", "-delete") or t in ("-fprint", "-fprint0", "-fprintf", "-fls"):
                raise Denied(f"find {t}: running commands or writing files is not on the {self.role} allow-list; {ADR_HINT}")

    # -- writers -------------------------------------------------------------
    def _check_all_args_writer(self, name: str, args: list[Word], unknown_args: bool) -> None:
        if unknown_args:
            raise Denied(f"{name}: cannot verify the files it would write (arguments from xargs or an unexpandable expansion)")
        target_dir = _option_value(args, "-t", "--target-directory") if name == "mv" else None
        pos = _positionals(args, VALUE_OPTS.get(name, set()))
        targets = [target_dir] if target_dir is not None else pos
        for w in targets:
            if w is not None:
                _check_word(w, self.cwd, self.ctx, name)

    def _check_cp(self, args: list[Word], unknown_args: bool) -> None:
        texts = [a.text for a in args]
        if any(t in ("-s", "--symbolic-link") or _short_has(t, "s") for t in texts):
            raise Denied(f"cp -s: creating symlinks is not allowed for the {self.role} agent")
        if any(t == "--link" or _short_has(t, "l") for t in texts):
            raise Denied(f"cp -l: creating hard links is not allowed for the {self.role} agent")
        if unknown_args:
            raise Denied("cp: cannot verify the destination (arguments from xargs or an unexpandable expansion)")
        target_dir = _option_value(args, "-t", "--target-directory")
        pos = _positionals(args, VALUE_OPTS.get("cp", set()))
        dests = [target_dir] if target_dir is not None else pos[-1:]
        for w in dests:
            if w is not None:
                _check_word(w, self.cwd, self.ctx, "cp")

    def _check_tee(self, args: list[Word], unknown_args: bool) -> None:
        if unknown_args:
            raise Denied("tee: cannot verify the files it would write (arguments from xargs or an unexpandable expansion)")
        for w in _positionals(args, set()):
            if w.text == "-":
                continue
            _check_word(w, self.cwd, self.ctx, "tee")

    def _check_script(self, word: Word) -> None:
        try:
            rel = repo_relative(resolve(word.text, self.cwd), self.ctx)
        except Denied:
            rel = None
        if rel not in ("scripts/issue-status.sh", "scripts/test-hooks.sh"):
            self._not_allowed(word.text)

    # -- QA tool chain -------------------------------------------------------
    def _check_make(self, args: list[Word]) -> None:
        targets: list[str] = []
        skip = False
        for w in args:
            t = w.text
            if skip:
                skip = False
                continue
            if t in MAKE_DENY_OPTS or t.split("=")[0] in MAKE_DENY_OPTS:
                raise Denied(f"make {t}: cannot verify which makefile would run; {ADR_HINT}")
            if t.startswith("-"):
                continue
            if "=" in t:
                continue  # VAR=value assignment
            targets.append(t)
        if not targets:
            raise Denied(f"make with no target runs the default target, which is not on the {self.role} allow-list; {ADR_HINT}")
        bad = [t for t in targets if t not in MAKE_TARGETS]
        if bad:
            raise Denied(f"make {' '.join(bad)}: only {', '.join(sorted(MAKE_TARGETS))} are on the {self.role} allow-list; {ADR_HINT}")

    def _check_uv(self, args: list[Word]) -> None:
        i = 0
        while i < len(args) and args[i].text.startswith("-"):
            i += 1
        if i >= len(args):
            raise Denied(f"uv with no subcommand is not on the {self.role} allow-list; {ADR_HINT}")
        sub = args[i].text
        if sub == "sync":
            return
        if sub == "run":
            j = i + 1
            while j < len(args) and args[j].text.startswith("-"):
                j += 1
            if j >= len(args):
                raise Denied(f"uv run with no command is not on the {self.role} allow-list; {ADR_HINT}")
            tool = os.path.basename(args[j].text)
            if tool not in UV_RUN_TOOLS:
                raise Denied(f"uv run {tool}: only {', '.join(sorted(UV_RUN_TOOLS))} are on the {self.role} allow-list; {ADR_HINT}")
            return
        raise Denied(f"uv {sub}: only 'uv run' and 'uv sync' are on the {self.role} allow-list; {ADR_HINT}")

    def _check_uvx(self, args: list[Word]) -> None:
        pkg: str | None = None
        i = 0
        while i < len(args):
            t = args[i].text
            if t == "--from" and i + 1 < len(args):
                pkg = args[i + 1].text
                break
            if t.startswith("--from="):
                pkg = t.split("=", 1)[1]
                break
            if t.startswith("-"):
                i += 1
                continue
            pkg = t
            break
        if pkg is None:
            raise Denied(f"uvx with no tool is not on the {self.role} allow-list; {ADR_HINT}")
        if os.path.basename(pkg) not in UVX_TOOLS:
            raise Denied(f"uvx {pkg}: only {', '.join(sorted(UVX_TOOLS))} are on the {self.role} allow-list; {ADR_HINT}")

    def _check_npm(self, args: list[Word]) -> None:
        sub = next((w.text for w in args if not w.text.startswith("-")), None)
        if sub not in NPM_SUBCOMMANDS:
            raise Denied(f"npm {sub or '(default)'}: only {', '.join(sorted(NPM_SUBCOMMANDS))} are on the {self.role} allow-list; {ADR_HINT}")

    def _check_npx(self, args: list[Word]) -> None:
        pkg: str | None = None
        i = 0
        while i < len(args):
            t = args[i].text
            if t in ("-p", "--package") and i + 1 < len(args):
                pkg = args[i + 1].text
                break
            if t.startswith("--package="):
                pkg = t.split("=", 1)[1]
                break
            if t.startswith("-"):
                i += 1
                continue
            pkg = t
            break
        if pkg is None or pkg not in NPX_PACKAGES:
            raise Denied(f"npx {pkg or '(none)'}: only {', '.join(sorted(NPX_PACKAGES))} are on the {self.role} allow-list; {ADR_HINT}")

    def _check_node(self, args: list[Word]) -> None:
        for w in args:
            t = w.text
            if t == "--":
                return
            if t in NODE_EVAL_OPTS or t.startswith(("--eval", "--print")):
                raise Denied(f"node {t}: evaluating inline code is not on the {self.role} allow-list; {ADR_HINT}")
            if not t.startswith("-"):
                return  # running a script file (residual risk, see ADR 0008)

    def _check_curl(self, args: list[Word]) -> None:
        urls: list[str] = []
        i = 0
        while i < len(args):
            t = args[i].text
            if t in CURL_DENY or t.split("=")[0] in CURL_DENY:
                raise Denied(f"curl {t}: writing files is not on the {self.role} allow-list; {ADR_HINT}")
            if t in ("--url",) and i + 1 < len(args):
                urls.append(args[i + 1].text)
                i += 2
                continue
            if t.startswith("--url="):
                urls.append(t.split("=", 1)[1])
                i += 1
                continue
            if t in CURL_VALUE:
                i += 2
                continue
            if t.startswith("-") and t != "-":
                i += 1
                continue
            urls.append(t)
            i += 1
        if not urls:
            raise Denied(f"curl without a target URL is not on the {self.role} allow-list; {ADR_HINT}")
        for u in urls:
            if not _is_local_url(u):
                raise Denied(f"curl {u}: only localhost/127.0.0.1 URLs are on the {self.role} allow-list; {ADR_HINT}")

    # -- git -----------------------------------------------------------------
    def _check_git(self, args: list[Word], unknown_args: bool) -> None:
        ctx = self.ctx
        cwd = self.cwd
        i = 0
        while i < len(args) and args[i].text.startswith("-"):
            opt = args[i].text
            if opt == "-C" and i + 1 < len(args):
                target = args[i + 1]
                cwd = None if target.dynamic else resolve(target.text, cwd)
                i += 2
            elif opt == "-c" and i + 1 < len(args):
                val = args[i + 1].text
                if val.startswith(("core.hooksPath", "alias.", "core.fsmonitor", "include.", "includeIf.")):
                    raise Denied(f"git -c {val.split('=')[0]}: configuring code execution is not on the {self.role} allow-list; {ADR_HINT}")
                i += 2
            elif opt.startswith("-c") and len(opt) > 2:
                val = opt[2:]
                if val.startswith(("core.hooksPath", "alias.", "core.fsmonitor", "include.", "includeIf.")):
                    raise Denied(f"git -c {val.split('=')[0]}: configuring code execution is not on the {self.role} allow-list; {ADR_HINT}")
                i += 1
            elif opt in ("--git-dir", "--work-tree", "--namespace"):
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
        if sub in GIT_READONLY or sub == "fetch":
            return
        if sub not in GIT_WRITE.get(self.role, set()):
            self._not_allowed(f"git {sub}")
        if sub in ("push", "switch", "worktree"):
            return  # publish commits / change branch / manage worktrees: no repo-file write to check
        if unknown_args and sub in ("add", "stage", "commit"):
            raise Denied(f"git {sub}: cannot verify the files it would change (arguments from xargs or an unexpandable expansion)")
        if sub in ("add", "stage"):
            self._git_add(rest, cwd)
        elif sub == "commit":
            self._git_commit(rest, cwd)
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


def _is_local_url(url: str) -> bool:
    host = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", url)
    host = host.split("/")[0].split("?")[0]
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if host.startswith("["):  # IPv6 literal, with optional :port after ]
        end = host.find("]")
        host = host[: end + 1] if end != -1 else host
    else:
        host = host.split(":")[0]
    return host in LOCAL_HOSTS


def _sed_scan(args: list[Word]) -> tuple[bool, list[str]]:
    """Return (in_place, list of sed script strings) for a sed argv."""
    in_place = False
    scripts: list[str] = []
    positionals: list[Word] = []
    expect: str | None = None
    for w in args:
        t = w.text
        if expect is not None:
            if expect == "script":
                scripts.append(t)
            expect = None
            continue
        if t.startswith("--"):
            if t.startswith("--in-place"):
                in_place = True
            elif t.startswith("--expression="):
                scripts.append(t.split("=", 1)[1])
            elif t == "--expression":
                expect = "script"
            elif t.startswith("--file="):
                scripts.append("")  # file script: treat as opaque, but it is a script source
            elif t in ("--file", "--line-length"):
                expect = "value"
        elif t.startswith("-") and t != "-":
            k = 1
            while k < len(t):
                ch = t[k]
                if ch == "i":
                    in_place = True
                    break
                if ch in "ef":
                    rest = t[k + 1 :]
                    if rest:
                        if ch == "e":
                            scripts.append(rest)
                    else:
                        expect = "script" if ch == "e" else "value"
                    break
                if ch == "l":
                    if k + 1 >= len(t):
                        expect = "value"
                    break
                k += 1
        else:
            positionals.append(w)
    if not scripts and positionals:
        scripts.append(positionals[0].text)
    return in_place, scripts


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
            raise Denied(f"PowerShell is not on the {agent} allow-list")
    except Denied as exc:
        return (
            f"FitWise scope guard blocked this {tool} call. The {agent} agent may only write under "
            f"{ctx.scope_text()} and run an allow-listed set of commands (docs/team.md, ADR 0008). "
            f"Reason: {exc}. {HINTS[agent]}"
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
