"""Table-driven tests for .claude/hooks/scope_guard.py (ADR 0008).

Run with: scripts/test-hooks.sh

Each case feeds a PreToolUse JSON event to the hook as a subprocess, exactly
as Claude Code does, and checks the decision. The fixture is a throw-away git
repository with the FitWise layout, a linked worktree, symlinks that point
out of scope and a second, unrelated repository.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

HOOK = Path(__file__).resolve().parents[1] / "scope_guard.py"
SETTINGS = Path(__file__).resolve().parents[2] / "settings.json"

ALLOW, DENY = "allow", "deny"


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class Fixture:
    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name).resolve()
        self.base = root
        self.repo = root / "repo"
        self.wt = root / "wt-qa"
        self.other = root / "other"
        self.pad = root / "scratchpad"
        self.outside = root / "outside"
        for d in ("backend/app", "backend/tests", "frontend/src", "frontend/tests", "e2e", "docs/adr",
                  ".github/ISSUE_TEMPLATE", ".github/workflows", "scripts", ".claude/hooks"):
            (self.repo / d).mkdir(parents=True)
        for f in ("backend/app/main.py", "backend/tests/test_a.py", "docs/spec.md", "README.md",
                  "frontend/src/App.tsx", "e2e/journey.spec.ts", ".github/ISSUE_TEMPLATE/feature.md"):
            (self.repo / f).write_text("x\n")
        # Symlinks: one inside tests pointing at app code, one in docs pointing outside the repo.
        (self.repo / "backend/tests/app_link").symlink_to("../app")
        (self.repo / "backend/tests/main_link.py").symlink_to("../app/main.py")
        self.outside.mkdir()
        (self.repo / "docs/out_link").symlink_to(self.outside)
        (self.repo / "frontend/tests/real").mkdir()
        # A symlink outside the scope that points into it (must be allowed by its target).
        (self.repo / "tests_shortcut").symlink_to("frontend/tests")
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "add", "-A")
        git(self.repo, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "init")
        git(self.repo, "worktree", "add", "-q", str(self.wt), "-b", "qa-branch")
        self.other.mkdir()
        (self.other / "docs").mkdir()
        git(self.other, "init", "-q")
        self.pad.mkdir()
        # A repo whose path goes through a symlink.
        (root / "repo_via_link").symlink_to(self.repo)

    def cleanup(self) -> None:
        self.tmp.cleanup()

    def sub(self, text: str) -> str:
        return (text.replace("{repo}", str(self.repo)).replace("{wt}", str(self.wt))
                .replace("{other}", str(self.other)).replace("{pad}", str(self.pad))
                .replace("{base}", str(self.base)))


def run_hook(event: dict[str, Any], project_dir: Path, raw: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    return subprocess.run(
        [sys.executable, "-B", str(HOOK)],
        input=raw if raw is not None else json.dumps(event),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )


def decision(proc: subprocess.CompletedProcess[str]) -> tuple[str, str]:
    if proc.returncode == 2:
        return DENY, proc.stderr
    assert proc.returncode == 0, proc.stderr
    if not proc.stdout.strip():
        return ALLOW, ""
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse"
    return out["permissionDecision"], out["permissionDecisionReason"]


# (id, agent, tool, target, expected). For file tools the target is a path; for Bash it is the command.
# Placeholders: {repo} main checkout, {wt} linked worktree, {other} unrelated repo, {pad} scratchpad.
FILE_CASES = [
    # allowed paths
    ("qa-backend-tests", "qa", "Write", "{repo}/backend/tests/test_new.py", ALLOW),
    ("qa-frontend-tests", "qa", "Edit", "{repo}/frontend/tests/App.test.tsx", ALLOW),
    ("qa-e2e", "qa", "Write", "{repo}/e2e/journeys/login.spec.ts", ALLOW),
    ("qa-new-nested-dir", "qa", "Write", "{repo}/backend/tests/engines/new/test_x.py", ALLOW),
    ("qa-notebook-in-scope", "qa", "NotebookEdit", "{repo}/backend/tests/explore.ipynb", ALLOW),
    ("pm-docs", "pm", "Edit", "{repo}/docs/spec.md", ALLOW),
    ("pm-adr", "pm", "Write", "{repo}/docs/adr/0009-x.md", ALLOW),
    ("pm-issue-template", "pm", "Write", "{repo}/.github/ISSUE_TEMPLATE/bug.md", ALLOW),
    ("qa-scratchpad", "qa", "Write", "{pad}/notes.txt", ALLOW),
    ("pm-scratchpad", "pm", "Write", "{pad}/body.md", ALLOW),
    # blocked paths
    ("qa-app-code", "qa", "Edit", "{repo}/backend/app/main.py", DENY),
    ("qa-frontend-src", "qa", "Write", "{repo}/frontend/src/App.tsx", DENY),
    ("qa-docs", "qa", "Edit", "{repo}/docs/spec.md", DENY),
    ("qa-settings-tamper", "qa", "Edit", "{repo}/.claude/settings.json", DENY),
    ("qa-hook-tamper", "qa", "Write", "{repo}/.claude/hooks/scope_guard.py", DENY),
    ("qa-notebook-out", "qa", "NotebookEdit", "{repo}/backend/app/x.ipynb", DENY),
    ("qa-multiedit-out", "qa", "MultiEdit", "{repo}/backend/app/main.py", DENY),
    ("qa-prefix-trick", "qa", "Write", "{repo}/backend/tests_evil/x.py", DENY),
    ("qa-e2e-prefix-trick", "qa", "Write", "{repo}/e2e-old/x.ts", DENY),
    ("qa-repo-root", "qa", "Write", "{repo}/README.md", DENY),
    ("pm-backend", "pm", "Edit", "{repo}/backend/app/main.py", DENY),
    ("pm-tests", "pm", "Write", "{repo}/backend/tests/test_a.py", DENY),
    ("pm-workflows", "pm", "Write", "{repo}/.github/workflows/ci.yml", DENY),
    ("pm-openapi", "pm", "Edit", "{repo}/openapi.yaml", DENY),
    ("pm-claude-md", "pm", "Edit", "{repo}/CLAUDE.md", DENY),
    # path traversal
    ("qa-traversal-out", "qa", "Write", "{repo}/backend/tests/../app/x.py", DENY),
    ("qa-traversal-deep", "qa", "Write", "{repo}/e2e/../../repo/backend/app/x.py", DENY),
    ("qa-traversal-back-in", "qa", "Write", "{repo}/backend/app/../tests/test_b.py", ALLOW),
    ("pm-traversal-out", "pm", "Write", "{repo}/docs/../openapi.yaml", DENY),
    ("pm-dot-segments", "pm", "Edit", "{repo}/./docs/./spec.md", ALLOW),
    # absolute paths into and outside the repo
    ("qa-abs-outside", "qa", "Write", "{base}/outside/evil.py", DENY),
    ("qa-abs-etc", "qa", "Write", "/etc/fitwise-test", DENY),
    ("pm-abs-home", "pm", "Write", "~/fitwise-notes.md", DENY),
    ("pm-other-repo-docs", "pm", "Write", "{other}/docs/x.md", DENY),
    ("qa-worktree-tests", "qa", "Write", "{wt}/backend/tests/test_wt.py", ALLOW),
    ("qa-worktree-app", "qa", "Edit", "{wt}/backend/app/main.py", DENY),
    ("pm-worktree-docs", "pm", "Edit", "{wt}/docs/spec.md", ALLOW),
    ("qa-repo-via-symlink", "qa", "Write", "{base}/repo_via_link/backend/tests/test_c.py", ALLOW),
    ("qa-repo-via-symlink-out", "qa", "Write", "{base}/repo_via_link/backend/app/x.py", DENY),
    # symlinks
    ("qa-symlink-dir-out", "qa", "Write", "{repo}/backend/tests/app_link/x.py", DENY),
    ("qa-symlink-file-out", "qa", "Edit", "{repo}/backend/tests/main_link.py", DENY),
    ("pm-symlink-out-of-repo", "pm", "Write", "{repo}/docs/out_link/x.md", DENY),
    ("qa-symlink-into-scope", "qa", "Write", "{repo}/tests_shortcut/real/x.test.ts", ALLOW),
    # unaffected agents (any path)
    ("engineer-app", "engineer", "Edit", "{repo}/backend/app/main.py", ALLOW),
    ("devops-settings", "devops", "Edit", "{repo}/.claude/settings.json", ALLOW),
    ("main-session", None, "Write", "{repo}/backend/app/main.py", ALLOW),
    ("unknown-agent", "Explore", "Write", "{repo}/backend/app/main.py", ALLOW),
    ("general-purpose", "general-purpose", "Edit", "/etc/hosts", ALLOW),
    ("agent-name-case", "QA", "Edit", "{repo}/backend/app/main.py", DENY),
]

BASH_CASES = [
    # commands both agents need
    ("qa-gh-comment", "qa", "gh issue comment 6 --body 'QA: PASS'", ALLOW),
    ("pm-gh-edit", "pm", "gh issue edit 6 --add-label status:ready && gh pr comment 7 --body x", ALLOW),
    ("pm-gh-heredoc", "pm", "gh issue comment 6 --body \"$(cat <<'EOF'\nPM: it's groomed > ready; see (docs)\nEOF\n)\"", ALLOW),
    ("pm-heredoc-stdin", "pm", "gh issue comment 6 --body-file - <<'EOF'\nPM: don't > break\nEOF", ALLOW),
    ("qa-issue-status", "qa", "scripts/issue-status.sh 6 in-progress", ALLOW),
    ("pm-issue-status-bash", "pm", "bash scripts/issue-status.sh 6 ready", ALLOW),
    ("qa-read-only-git", "qa", "git status && git log --oneline -5 && git diff main...HEAD", ALLOW),
    ("qa-git-worktree", "qa", "git fetch origin && git worktree add ../fitwise-wt/qa-12 feat/6-x", ALLOW),
    ("qa-grep-cat", "qa", "grep -rn TODO backend | head -5; cat docs/spec.md | wc -l", ALLOW),
    ("qa-make", "qa", "make lint && make test && make e2e", ALLOW),
    ("qa-stderr-redirect", "qa", "make test 2>&1 | tail -20", ALLOW),
    ("qa-dev-null", "qa", "ls backend >/dev/null 2>/dev/null", ALLOW),
    ("qa-commit-message-gt", "qa", "git commit -m 'test: assert BMR > 0'", ALLOW),
    ("pm-gh-pr-create", "pm", "gh pr create --title 'docs: x' --body 'a > b'", ALLOW),
    # shell writes inside scope
    ("qa-redirect-in", "qa", "echo x > backend/tests/fixture.json", ALLOW),
    ("qa-tee-in", "qa", "echo x | tee -a e2e/notes.txt", ALLOW),
    ("qa-sed-in", "qa", "sed -i 's/a/b/' backend/tests/test_a.py", ALLOW),
    ("qa-cd-then-write", "qa", "cd backend/tests && echo x > test_z.py", ALLOW),
    ("pm-mkdir-docs", "pm", "mkdir -p docs/runbooks && touch docs/runbooks/x.md", ALLOW),
    ("qa-cp-into-tests", "qa", "cp backend/app/main.py backend/tests/copy_of_main.py", ALLOW),
    ("qa-scratchpad-redirect", "qa", "gh pr diff 7 > {pad}/pr.diff", ALLOW),
    ("qa-worktree-write", "qa", "echo x > {wt}/backend/tests/t.py", ALLOW),
    # shell writes out of scope
    ("qa-redirect-out", "qa", "echo x > backend/app/main.py", DENY),
    ("qa-append-out", "qa", "echo x >> README.md", DENY),
    ("qa-fd-redirect-out", "qa", "make test 2> backend/app/log.txt", DENY),
    ("qa-amp-redirect-out", "qa", "make test &> frontend/src/out.txt", DENY),
    ("qa-tee-out", "qa", "echo x | tee backend/app/x.py", DENY),
    ("qa-sed-out", "qa", "sed -i 's/a/b/' backend/app/main.py", DENY),
    ("qa-sed-suffix-out", "qa", "sed -i.bak -e 's/a/b/' backend/app/main.py", DENY),
    ("qa-sed-bundle-out", "qa", "sed -Ei 's/a/b/' frontend/src/App.tsx", DENY),
    ("qa-perl-out", "qa", "perl -pi -e 's/a/b/' backend/app/main.py", DENY),
    ("qa-cp-out", "qa", "cp backend/tests/test_a.py backend/app/main.py", DENY),
    ("qa-mv-out-source", "qa", "mv backend/app/main.py backend/tests/", DENY),
    ("qa-rm-out", "qa", "rm -rf backend/app", DENY),
    ("qa-touch-out", "qa", "touch backend/app/new.py", DENY),
    ("qa-dd-out", "qa", "dd if=/dev/zero of=backend/app/main.py count=1", DENY),
    ("qa-cd-then-write-out", "qa", "cd backend/app && echo x > y.py", DENY),
    ("qa-cd-traversal", "qa", "cd backend/tests/../app; touch x.py", DENY),
    ("qa-subshell-cd-scoped", "qa", "(cd backend/tests && touch ok.py); touch README.md", DENY),
    ("qa-heredoc-out", "qa", "cat > backend/app/x.py <<'EOF'\nprint(1)\nEOF", DENY),
    ("qa-bash-c-out", "qa", "bash -c 'echo x > backend/app/x.py'", DENY),
    ("qa-sh-stdin", "qa", "echo 'rm -rf backend' | sh", DENY),
    ("qa-eval-out", "qa", "eval 'echo x > backend/app/x.py'", DENY),
    ("qa-subst-out", "qa", "echo $(echo x > backend/app/x.py)", DENY),
    ("qa-variable-target", "qa", "echo x > \"$TARGET\"", DENY),
    ("qa-xargs-rm", "qa", "git ls-files backend/app | xargs rm", DENY),
    ("qa-env-wrapper", "qa", "env FOO=1 tee backend/app/x.py < /dev/null", DENY),
    ("qa-sudo-wrapper", "qa", "sudo touch /etc/x", DENY),
    ("qa-symlink-redirect", "qa", "echo x > backend/tests/app_link/x.py", DENY),
    ("qa-abs-out", "qa", "echo x > /etc/fitwise-test", DENY),
    ("qa-settings-tamper", "qa", "sed -i 's/qa/xx/' .claude/hooks/scope_guard.py", DENY),
    ("qa-claude-nested", "qa", "claude -p 'edit backend/app/main.py'", DENY),
    ("qa-patch", "qa", "patch -p1 < {pad}/fix.diff", DENY),
    ("qa-git-apply", "qa", "git apply {pad}/fix.diff", DENY),
    ("qa-git-restore-out", "qa", "git restore backend/app/main.py", DENY),
    ("qa-git-checkout-file-out", "qa", "git checkout -- backend/app/main.py", DENY),
    ("qa-git-rm-out", "qa", "git rm backend/app/main.py", DENY),
    ("qa-git-C-out", "qa", "git -C backend/app rm main.py", DENY),
    ("qa-git-workdir", "qa", "git --work-tree=/tmp/x add .", DENY),
    ("pm-redirect-backend", "pm", "echo x > backend/app/main.py", DENY),
    ("pm-redirect-tests", "pm", "printf x > backend/tests/test_x.py", DENY),
    ("pm-workflow", "pm", "cp {pad}/ci.yml .github/workflows/ci.yml", DENY),
    # QA FAIL on #60, bypass 1: xargs keeps the wrapped command's options
    ("qa-xargs-sed-i", "qa", "grep -rl aaa backend/app | xargs sed -i s/aaa/XXX/", DENY),
    ("qa-xargs-perl-pi", "qa", "grep -rl a backend | xargs perl -pi -e s/a/b/", DENY),
    ("qa-xargs-opts-sed", "qa", "git ls-files -z | xargs -0 -n 1 -I{} sed -i s/a/b/ {}", DENY),
    ("qa-xargs-bundled-opts", "qa", "ls | xargs -0rt -P4 sed -i.bak s/a/b/", DENY),
    ("qa-xargs-sh-c", "qa", "ls | xargs -I{} sh -c 'echo x > {}'", DENY),
    ("qa-xargs-git-add", "qa", "git ls-files -m | xargs git add", DENY),
    ("qa-xargs-unknown-opt", "qa", "ls | xargs --bogus sed -i s/a/b/", DENY),
    ("qa-xargs-read-only", "qa", "grep -rl x backend | xargs grep -n y | xargs -r wc -l", ALLOW),
    # bypass 2: wrappers with options
    ("qa-nice-n", "qa", "nice -n 1 touch backend/app/qa_live_probe.txt", DENY),
    ("qa-nice-numeric", "qa", "nice -5 touch backend/app/x.py", DENY),
    ("qa-sudo-u", "qa", "sudo -u root tee backend/app/x.py", DENY),
    ("qa-sudo-flags-dashdash", "qa", "sudo -E -n -- touch backend/app/x.py", DENY),
    ("qa-sudo-unknown-opt", "qa", "sudo --bogus touch backend/tests/x.py", DENY),
    ("qa-sudo-edit", "qa", "sudo -e backend/app/main.py", DENY),
    ("qa-stdbuf-attached", "qa", "stdbuf -oL tee backend/app/x.py", DENY),
    ("qa-stdbuf-separate", "qa", "stdbuf -o L -e 0 tee backend/app/x.py", DENY),
    ("qa-env-u", "qa", "env -u X tee backend/app/x.py", DENY),
    ("qa-env-i-assign", "qa", "env -i PATH=/bin tee backend/app/x.py", DENY),
    ("qa-env-chdir", "qa", "env -C backend/tests touch ../app/x.py", DENY),
    ("qa-env-split-string", "qa", "env -S 'tee backend/tests/x'", DENY),
    ("qa-command-p", "qa", "command -p touch backend/app/x.py", DENY),
    ("qa-exec-a", "qa", "exec -a x tee backend/app/x.py", DENY),
    ("qa-time-p", "qa", "time -p touch backend/app/x.py", DENY),
    ("qa-gnu-time-output", "qa", "/usr/bin/time -o backend/app/t.txt ls", DENY),
    ("qa-timeout-opts", "qa", "timeout -s KILL 5 touch backend/app/x.py", DENY),
    ("qa-stacked-wrappers", "qa", "nohup nice ionice -c3 setsid -f touch backend/app/x.py", DENY),
    ("qa-parallel", "qa", "ls | parallel sed -i s/a/b/", DENY),
    ("qa-wrappers-in-scope", "qa", "sudo -u root touch backend/tests/x.py && env -u X tee e2e/n.txt < /dev/null", ALLOW),
    ("qa-wrappers-read-only", "qa", "nice -n 10 make test && timeout 600 make e2e && time -p make lint", ALLOW),
    ("qa-stdbuf-tee-pad", "qa", "stdbuf -oL make test 2>&1 | tee {pad}/out.log", ALLOW),
    # bypass 3: brace expansion in write targets
    ("qa-brace-touch", "qa", "touch backend/tests/{k,../../backend/app/brace.txt}", DENY),
    ("qa-brace-mkdir", "qa", "mkdir -p backend/tests/{a,../app/b}", DENY),
    ("qa-brace-rm", "qa", "rm -rf backend/tests/{x,../app}", DENY),
    ("qa-brace-sed", "qa", "sed -i s/a/b/ backend/tests/{test_a.py,../app/main.py}", DENY),
    ("qa-brace-tee", "qa", "echo x | tee backend/tests/{a,../app/b}", DENY),
    ("qa-brace-redirect", "qa", "echo x > backend/tests/{a,../app/b}", DENY),
    ("qa-brace-nested", "qa", "touch backend/tests/{a,{b,../../backend/app/c}}", DENY),
    ("qa-brace-cp-dest", "qa", "cp README.md backend/tests/{x,../app/y}", DENY),
    ("qa-brace-empty-shift", "qa", "cd backend/tests && cp ../app/main.py ../app/x {,}", DENY),
    ("qa-brace-sequence", "qa", "touch backend/tests/{a..z}pp_link/x.py", DENY),
    ("qa-brace-sequence-rm", "qa", "cd backend/tests && rm ../app/x{1..3}.py", DENY),
    ("qa-brace-sequence-read-only", "qa", "for i in {1..3}; do make test; done && echo {,}", ALLOW),
    ("qa-brace-in-scope", "qa", "mkdir -p backend/tests/{unit,integration} && touch e2e/{a,b}.spec.ts", ALLOW),
    ("qa-brace-quoted-literal", "qa", "touch backend/tests/'{x,../../app/y}' \"e2e/{a,b}\"", ALLOW),
    # globs that match a symlink pointing out of scope
    ("qa-glob-symlink-file", "qa", "echo x > backend/tests/main_lin*", DENY),
    ("qa-glob-symlink-dir", "qa", "cp README.md backend/tests/app_lin?/", DENY),
    ("qa-glob-in-scope", "qa", "rm -f backend/tests/*.pyc e2e/*.tmp", ALLOW),
    # bypass 4: find actions
    ("qa-find-exec-sed", "qa", "find backend/app -name '*.py' -exec sed -i s/a/b/ {} +", DENY),
    ("qa-find-execdir-rm", "qa", "find backend -name x -execdir rm {} \\;", DENY),
    ("qa-find-ok", "qa", "find . -name x -ok rm {} \\;", DENY),
    ("qa-find-exec-sh", "qa", "find backend/tests -exec sh -c 'echo > ../app/x' \\;", DENY),
    ("qa-find-delete-out", "qa", "find backend/app -name '*.py' -delete", DENY),
    ("qa-find-delete-root", "qa", "find . -name '*.tmp' -delete", DENY),
    ("qa-find-delete-follow", "qa", "find -L backend/tests -delete", DENY),
    ("qa-find-fprint", "qa", "find backend/tests -fprint backend/app/list.txt", DENY),
    ("qa-find-fprintf", "qa", "find backend/tests -fprintf backend/app/l.txt '%p'", DENY),
    ("qa-find-fls", "qa", "find backend/tests -fls backend/app/l", DENY),
    ("qa-find-read-only", "qa", "find backend -name '*.py' -exec grep -l TODO {} + && find . -type f -print | head", ALLOW),
    ("qa-find-delete-in-scope", "qa", "find e2e backend/tests -name '*.tmp' -delete", ALLOW),
    ("qa-find-fprint-pad", "qa", "find backend -name '*.py' -fprint {pad}/files.txt", ALLOW),
    # hard links from outside the scope
    ("qa-hardlink", "qa", "ln backend/app/main.py backend/tests/h.py", DENY),
    ("qa-hardlink-force-dir", "qa", "ln -f backend/app/main.py backend/tests/", DENY),
    ("qa-hardlink-target-dir", "qa", "ln -t backend/tests backend/app/main.py", DENY),
    ("qa-cp-link", "qa", "cp -l backend/app/main.py backend/tests/h.py", DENY),
    ("qa-cp-link-long", "qa", "cp --link backend/app/main.py backend/tests/h.py", DENY),
    ("qa-link-cmd", "qa", "link backend/app/main.py backend/tests/h.py", DENY),
    ("qa-ln-single-arg", "qa", "ln -s backend/tests/test_a.py", DENY),
    ("qa-install-d", "qa", "install -d backend/app/x backend/tests/y", DENY),
    ("qa-hardlink-in-scope", "qa", "ln backend/tests/test_a.py backend/tests/h.py", ALLOW),
    ("qa-symlink-create", "qa", "ln -sf ../app/main.py backend/tests/l.py", ALLOW),
    ("pm-brace-out", "pm", "touch docs/{a,../openapi.yaml}", DENY),
    ("pm-xargs-sed", "pm", "ls docs | xargs sed -i s/a/b/", DENY),
    # unaffected agents
    ("engineer-redirect", "engineer", "echo x > backend/app/main.py", ALLOW),
    ("devops-sed", "devops", "sed -i 's/a/b/' .claude/settings.json", ALLOW),
    ("main-session-claude", None, "claude -p hi", ALLOW),
    ("unknown-agent-rm", "Plan", "rm -rf backend/app", ALLOW),
]

# (id, agent, setup commands run in the repo, Bash command, expected) — git staging state matters here.
GIT_CASES = [
    ("qa-commit-staged-test", "qa", ["echo y > backend/tests/test_a.py", "git add backend/tests/test_a.py"],
     "git commit -m 'test: cover x'", ALLOW),
    ("qa-commit-staged-app", "qa", ["echo y > backend/app/main.py", "git add backend/app/main.py"],
     "git commit -m 'test: sneaky'", DENY),
    ("qa-commit-all-app", "qa", ["echo y > backend/app/main.py"], "git commit -am 'test: x'", DENY),
    ("qa-commit-all-tests-only", "qa", ["echo y > backend/tests/test_a.py"], "git commit -a -m 'test: x'", ALLOW),
    ("qa-commit-pathspec-out", "qa", ["echo y > backend/app/main.py"], "git commit -m x backend/app/main.py", DENY),
    ("qa-add-then-commit-out", "qa", ["echo y > backend/app/main.py"],
     "git add backend/app/main.py && git commit -m 'test: x'", DENY),
    ("qa-add-all-out", "qa", ["echo y > frontend/src/App.tsx", "echo y > backend/tests/test_a.py"], "git add -A", DENY),
    ("qa-add-all-tests-only", "qa", ["echo y > backend/tests/test_a.py", "echo y > e2e/journey.spec.ts"],
     "git add -A && git commit -m 'test: x'", ALLOW),
    ("qa-add-dot-in-tests", "qa", ["echo y > backend/tests/test_a.py", "echo y > backend/app/main.py"],
     "cd backend/tests && git add .", ALLOW),
    ("pm-commit-docs", "pm", ["echo y > docs/spec.md", "git add docs/spec.md"], "git commit -m 'docs: x'", ALLOW),
    ("pm-commit-readme", "pm", ["echo y > README.md"], "git add README.md && git commit -m 'docs: x'", DENY),
    ("pm-push", "pm", [], "git push -u origin HEAD", ALLOW),
    ("engineer-commit-app", "engineer", ["echo y > backend/app/main.py", "git add -A"], "git commit -m x", ALLOW),
]


class ScopeGuardTest(unittest.TestCase):
    fx: Fixture

    @classmethod
    def setUpClass(cls) -> None:
        cls.fx = Fixture()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fx.cleanup()

    def event(self, agent: str | None, tool: str, tool_input: dict[str, Any], cwd: Path) -> dict[str, Any]:
        ev = {
            "session_id": "test",
            "transcript_path": "/dev/null",
            "cwd": str(cwd),
            "permission_mode": "bypassPermissions",
            "hook_event_name": "PreToolUse",
            "tool_name": tool,
            "tool_input": tool_input,
            "tool_use_id": "toolu_test",
            "scratchpad_dir": str(self.fx.pad),
        }
        if agent is not None:
            ev["agent_id"] = "a123"
            ev["agent_type"] = agent
        return ev

    def assertDecision(self, case_id: str, proc: subprocess.CompletedProcess[str], expected: str, agent: str | None) -> None:
        got, reason = decision(proc)
        self.assertEqual(got, expected, f"{case_id}: expected {expected}, got {got}: {reason}")
        if expected == DENY and agent:
            self.assertIn("FitWise scope guard", reason, case_id)
            if agent.lower() == "qa":
                self.assertIn("backend/tests/, frontend/tests/, e2e/", reason, case_id)
            elif agent.lower() == "pm":
                self.assertIn("docs/, .github/ISSUE_TEMPLATE/", reason, case_id)

    def test_file_tools(self) -> None:
        for case_id, agent, tool, target, expected in FILE_CASES:
            with self.subTest(case_id):
                key = "notebook_path" if tool == "NotebookEdit" else "file_path"
                path = self.fx.sub(target)
                if path.startswith("~"):
                    path = os.path.expanduser(path)
                proc = run_hook(self.event(agent, tool, {key: path, "content": "x"}, self.fx.repo), self.fx.repo)
                self.assertDecision(case_id, proc, expected, agent)

    def test_bash(self) -> None:
        for case_id, agent, command, expected in BASH_CASES:
            with self.subTest(case_id):
                ev = self.event(agent, "Bash", {"command": self.fx.sub(command)}, self.fx.repo)
                self.assertDecision(case_id, run_hook(ev, self.fx.repo), expected, agent)

    def test_git_staging(self) -> None:
        for case_id, agent, setup, command, expected in GIT_CASES:
            with self.subTest(case_id):
                # Each case runs in a fresh worktree so staging state does not leak between cases.
                wt = self.fx.base / f"wt-{case_id}"
                git(self.fx.repo, "worktree", "add", "-q", "--detach", str(wt))
                try:
                    for step in setup:
                        subprocess.run(step, shell=True, cwd=wt, check=True, capture_output=True)
                    ev = self.event(agent, "Bash", {"command": command}, wt)
                    # Project dir is the main checkout: worktrees of the same repo are in scope.
                    self.assertDecision(case_id, run_hook(ev, self.fx.repo), expected, agent)
                finally:
                    git(self.fx.repo, "worktree", "remove", "--force", str(wt))

    def test_project_dir_is_a_worktree(self) -> None:
        """A session started inside a worktree (CLAUDE_PROJECT_DIR = worktree) is enforced the same way."""
        for agent, path, expected in [
            ("qa", "{wt}/backend/tests/test_y.py", ALLOW),
            ("qa", "{wt}/backend/app/main.py", DENY),
            ("qa", "{repo}/backend/tests/test_y.py", ALLOW),
            ("pm", "{repo}/backend/app/main.py", DENY),
        ]:
            with self.subTest(f"{agent}:{path}"):
                ev = self.event(agent, "Write", {"file_path": self.fx.sub(path), "content": "x"}, self.fx.wt)
                self.assertDecision(path, run_hook(ev, self.fx.wt), expected, agent)

    def test_unknown_or_irrelevant_tools_pass(self) -> None:
        for tool, tool_input in [("Read", {"file_path": "/etc/hosts"}), ("Grep", {"pattern": "x"}), ("Glob", {"pattern": "*"})]:
            with self.subTest(tool):
                self.assertDecision(tool, run_hook(self.event("qa", tool, tool_input, self.fx.repo), self.fx.repo), ALLOW, "qa")

    def test_powershell_denied_for_restricted_agents(self) -> None:
        ev = self.event("pm", "PowerShell", {"command": "Set-Content docs/x.md hi"}, self.fx.repo)
        self.assertDecision("pm-powershell", run_hook(ev, self.fx.repo), DENY, "pm")
        ev = self.event("engineer", "PowerShell", {"command": "Set-Content x hi"}, self.fx.repo)
        self.assertDecision("engineer-powershell", run_hook(ev, self.fx.repo), ALLOW, "engineer")

    def test_missing_path_is_denied(self) -> None:
        ev = self.event("qa", "Write", {"content": "x"}, self.fx.repo)
        self.assertDecision("qa-no-path", run_hook(ev, self.fx.repo), DENY, "qa")

    def test_invalid_input_blocks(self) -> None:
        proc = run_hook({}, self.fx.repo, raw="not json")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unreadable hook input", proc.stderr)

    def test_deny_message_names_allowed_directories(self) -> None:
        ev = self.event("qa", "Edit", {"file_path": str(self.fx.repo / "backend/app/main.py")}, self.fx.repo)
        _, reason = decision(run_hook(ev, self.fx.repo))
        self.assertIn("The qa agent may only write under backend/tests/, frontend/tests/, e2e/", reason)
        self.assertIn("backend/app/main.py is outside the allowed directories", reason)

    def test_brace_expansion_matches_bash(self) -> None:
        """The hook expands unquoted {a,b} groups the way bash does (and leaves quoted ones alone)."""
        spec = importlib.util.spec_from_file_location("scope_guard", HOOK)
        assert spec and spec.loader
        guard = importlib.util.module_from_spec(spec)
        sys.modules["scope_guard"] = guard  # dataclasses need the module registered
        spec.loader.exec_module(guard)
        for word in ["a{b,c}d", "{a,b}{c,d}", "x{,}y", "a{b,c{d,e}}f", '"{a,b}"', "{a}", "\\{a,b\\}",
                     '{a,"b,c"}', "pre/{x,../y}/z", "'{'a,b}", "{a,b'}'}", "plain", "{}"]:
            with self.subTest(word):
                bash = subprocess.run(["bash", "-c", f"printf '%s\\n' {word}"], capture_output=True, text=True, check=True)
                parsed = guard.parse_shell(f"echo {word}")[0].words[1]
                self.assertEqual([w.text for w in guard.brace_expand(parsed)], bash.stdout.splitlines(), word)

    def test_settings_register_the_hook(self) -> None:
        """The committed settings run this script for every write-capable tool and fail closed."""
        settings = json.loads(SETTINGS.read_text())
        entries = settings["hooks"]["PreToolUse"]
        hook = next(h for e in entries for h in e["hooks"] if any("scope_guard.py" in a for a in h.get("args", [])))
        matcher = next(e["matcher"] for e in entries if hook in e["hooks"])
        for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "PowerShell"):
            self.assertRegex(tool, matcher)
        for tool in ("Read", "Grep", "Glob"):
            self.assertIsNone(re.search(matcher, tool))
        self.assertEqual(hook["args"], ["${CLAUDE_PROJECT_DIR}/.claude/hooks/scope_guard.py"])
        self.assertEqual(hook.get("onFailure"), "block")


if __name__ == "__main__":
    unittest.main()
