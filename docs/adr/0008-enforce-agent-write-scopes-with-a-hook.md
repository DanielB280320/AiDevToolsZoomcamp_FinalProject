# ADR 0008: Enforce the QA and PM write scopes with a project PreToolUse hook

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-21 |
| **Deciders** | Owner, DevOps/SRE |
| **Spec** | [team.md — Roles](../team.md#roles), [process.md §6 QA verification](../process.md#6-qa-verification), [process.md §8 Changing the spec](../process.md#8-changing-the-spec), issue #60 |

## Context

[team.md](../team.md#roles) limits what two agents may write: **QA** only tests (`backend/tests/`, `frontend/tests/`, `e2e/`) and **PM** only `docs/` and `.github/ISSUE_TEMPLATE/`. Until now those limits were instructions in the agent prompts. All agents get the same tools (`Read, Grep, Glob, Bash, Edit, Write`), because QA has to write test files and the PM has to edit docs. So nothing technical stopped either agent from editing application code. QA raised this on #2.

Both agents still need `gh` (comments, issue edits, PRs), `scripts/issue-status.sh`, read-only `git`/`grep`/`cat`. QA also needs `make lint`/`make test`/`make e2e` and `git commit` of test files on a PR branch. Taking `Edit`/`Write`/`Bash` away is therefore not an option.

What Claude Code offers (hooks reference, checked against v2.1.307):

- Hooks in settings files also fire **inside subagents**. When they do, the input JSON has `agent_id` and `agent_type`, the `name` from the subagent's frontmatter (`qa`, `pm`). In the main session `agent_type` is missing. It is also set when a session is started with `claude --agent <name>`.
- Hooks can also be declared in a subagent's frontmatter, but **project subagent frontmatter hooks only run after the workspace trust dialog has been accepted, and a `-p` session does not count as accepting it**. Hooks in `.claude/settings.json` do run in `-p`/SDK sessions.
- A `PreToolUse` hook can return `permissionDecision: "deny"` with a reason, which Claude sees. Hooks run before permission rules and the permission prompt, and deny wins over every other hook decision. We checked that a deny also holds in `bypassPermissions` mode; see the demonstration on #60.
- `"onFailure": "block"` (v2.1.295+) blocks the tool call if the hook can't start, crashes or times out.

## Decision

We will enforce the scopes with **one project `PreToolUse` hook** in the committed [`.claude/settings.json`](../../.claude/settings.json). It runs [`.claude/hooks/scope_guard.py`](../../.claude/hooks/scope_guard.py) (Python 3 standard library only) for `Write`, `Edit`, `MultiEdit`, `NotebookEdit`, `Bash` and `PowerShell`:

1. **Identify the agent** by `agent_type`. Only `qa` and `pm` are restricted. Every other value, and a missing value (main session/orchestrator, `engineer`, `devops`, built-in agents), passes without any further checks.
2. **File tools.** The target path (`file_path` / `notebook_path`) is made absolute and resolved with `realpath`, which removes `..` and follows symlinks for the parts that exist. It is allowed only if it falls in a work tree of the **same repository** (same git common dir as `$CLAUDE_PROJECT_DIR`, so every linked worktree counts) *and* its path relative to that work tree's root is inside the agent's scope. The session scratchpad (`scratchpad_dir`) and `/dev/null`-type devices are allowed too. Everything else is denied: other repositories, `$HOME`, `/etc`, and `.claude/` itself, so an agent can't edit the guard.
3. **Bash.** The command is parsed (quotes, `$(…)`/backticks, here-documents, `;`/`&&`/`||`/`|`, subshells, `cd`) and checked against a deny-list of write forms. The targets of each are checked like file paths:
   - redirections `>`, `>>`, `&>`, `n>`, `>|`, `<>` (also `exec 3>file`); `tee`; `sed -i`; `perl -i`; `dd of=`;
   - `cp`/`install`/`ln`/`rsync` (destination; every directory for `install -d`), `mv`/`rm`/`rmdir`/`touch`/`mkdir`/`truncate`/`shred`/`unlink`/`link` (every path), `chmod`/`chown`/`chgrp`;
   - **hard links:** `ln` without `-s`, `cp -l`/`--link` and `link` also check their *sources*, because writing the in-scope name of a hard link changes the original file;
   - `find`: `-delete` checks the start paths (denied with `-L`/`-follow`), `-fprint`/`-fprint0`/`-fprintf`/`-fls` check their output file, and the command of `-exec`/`-execdir`/`-ok`/`-okdir` is checked like an `xargs` command (below), so `find … -exec grep …` passes and `find … -exec sed -i …` is denied;
   - git: `git add` (the files `git add --dry-run` would stage), `git commit` (the staged files, the tracked changes for `-a`, and pathspecs), `git mv`/`rm`/`restore`/`checkout -- <paths>`; `git apply`/`am` and `--work-tree`/`--git-dir` are always denied;
   - **wrappers** are unwrapped after skipping their own options, from a per-wrapper option table: `sudo`, `doas`, `env` (assignments, `-u`, `-i`; `-C DIR` changes the directory; `-S` is denied), `nice` (`-n N`, `-N`), `nohup`, `setsid`, `timeout`, `stdbuf`, `ionice`, `command`, `builtin`, `exec -a`, `busybox`, `time -p` and GNU `time -o FILE` (FILE is checked). **A wrapper option that is not in the table denies the call** (fail closed). `sudo -e`/`sudoedit`, `su`, `runuser` and `parallel` are always denied;
   - `xargs`: only xargs' own options are skipped. The command it runs keeps its options, and because its file arguments come from stdin, **any writer it runs is denied** (`xargs sed -i`, `xargs perl -pi`, `xargs rm`, `xargs git add`), as is a shell or `eval`; read-only commands (`xargs grep`, `xargs wc -l`) pass;
   - nesting: `bash -c`/`sh -c`, `eval`, and a shell reading commands from stdin (denied);
   - **brace expansion** is modelled like bash: unquoted `{a,b}` groups (nested too) are expanded before arguments are classified, so `touch backend/tests/{k,../../backend/app/x}` checks `backend/app/x`; quoted braces stay literal. A sequence (`{1..3}`) or a group that expands to empty words is not modelled: it is denied as a write target and makes the command's arguments unknown, like `xargs` (writers denied, readers pass);
   - **globs** in write targets (`*`, `?`, `[…]`) are expanded against the file system as well, so a glob that matches a symlink pointing out of scope is denied;
   - always denied for these agents: `claude` (a nested session has no `agent_type`), `patch`, and the `PowerShell` tool;
   - a write target that contains a variable or command substitution is denied, because it can't be checked.
4. **Fail closed.** An internal error in the checks denies the call for `qa`/`pm`. Input that can't be parsed exits 2, and `onFailure: "block"` blocks the call if the hook can't run at all.
5. **The deny message** names the agent, the allowed directories, the reason and what to do instead, for example: *"FitWise scope guard blocked this Edit call. The pm agent may only write under docs/, .github/ISSUE_TEMPLATE/ (docs/team.md, ADR 0008). Reason: Edit: openapi.yaml is outside the allowed directories. The PM writes docs and issue templates only; describe the change on the issue for the Engineer/DevOps."*

The scopes live in one place, `SCOPES` in `scope_guard.py`. They must match [team.md](../team.md#roles), and changing them needs a PR that updates both. Tests: `scripts/test-hooks.sh`, a table-driven `unittest` suite run against a throw-away git repository with worktrees and symlinks. Once CI exists (#11) it runs there.

## Alternatives considered

| Option | Why not |
|---|---|
| Hooks in the `qa`/`pm` frontmatter | Project subagent frontmatter hooks don't run in `-p`/SDK sessions or before workspace trust, so the guard would silently switch off in headless runs. It would also mean two copies of the logic. |
| Remove `Edit`/`Write`/`Bash` from the agents' `tools` | Both agents need them for in-scope work: test files, docs, `gh`, `make test`. |
| `permissions.deny` rules such as `Edit(backend/app/**)` in settings | Permission rules apply to every agent, including the engineer. They can't express "allow only these directories for this agent", and they don't cover shell writes. |
| Run QA/PM in a sandbox or container with a read-only mount | Strong, but heavy for the M0 tool chain, and it breaks worktrees and `make test` against the Compose stack. It is still an option if the residual risk below becomes a problem. |
| Rely on review only | That is the gap QA reported on #2. |

## Consequences

- **Positive:** A QA or PM agent that tries to write outside its scope is stopped before the write, with a message that tells it what to do instead. Engineer, DevOps and the orchestrator are not affected. The guard ships with the repo, so it works in a fresh clone, in every git worktree and in headless runs.
- **Negative / accepted risks:** The Bash check is a **deny-list over a parsed command line, not a sandbox**. These forms are not caught:
  - programs that write files as a side effect: scripts run by path (`python3 tool.py`, `bash some.sh`, `node x.js`), inline interpreters (`python3 -c "open(...,'w')"`, `node -e`), formatters/fixers (`ruff --fix`, `ruff format`, `eslint --fix`, `prettier --write`), package managers, and any `make` target that writes, including `make lint` if it ever auto-fixes;
  - writers whose target is inside their own script or options and that the checker doesn't know: `sed` without `-i` but with a `w file` command or `s///w file` flag (`sed -n 'w backend/app/x' …`), `awk '{print > "f"}'`, `curl -o`/`wget -O`, `tar -x`/`-C DIR`, `unzip -d`, `git -c core.hooksPath=…`/`-c alias.…` (which make a later git command run arbitrary code), `git config`, and wrapper programs the table doesn't list (`flock`, `chroot`, `watch`, `script`, `strace -o`, …), which are treated as ordinary read-only commands;
  - shell constructs the parser doesn't model: process substitution `>(…)`, aliases, functions, `source`/`.` of a script, git aliases and git hooks;
  - git commands that move the working tree to existing commits (`checkout <branch>`, `reset --hard`, `stash pop`, `pull`, `merge`, `rebase`). These change files, but they don't create new content;
  - `git push`. It only publishes commits, and `git commit` has already been checked.

  Mitigation: the `git add`/`git commit` checks are the backstop, so out-of-scope changes made by such a program can't be committed by QA/PM in the same session through the normal git commands. **QA's review checks for it** too: before posting a verdict QA runs `git diff --name-only <verified-sha>..HEAD` (only the commits QA added on top of the PR head it verified) and `git status --porcelain` on its worktree and confirms that every file it changed is under `backend/tests/`, `frontend/tests/` or `e2e/` and every commit it made starts with `test:` ([qa.md](../../.claude/agents/qa.md)). The owner's PR review is the last line.
- **Negative:** The guard depends on Claude Code passing `agent_type`, which it does for subagents and `--agent` sessions. A PM or QA prompt run as a **plain main session** (no subagent, no `--agent`) is not restricted. The orchestrator must always start them as subagents (`team.md`, "Running the team").
- **Negative:** A Claude Code plugin *mod* that handles the `tool.check` event can, in some credential setups, approve a call that a hook blocked (permissions docs, "Extend permissions with hooks"). The project installs no mods; adding one needs owner approval.
- **Negative:** The hook runs `python3` on every write-capable tool call in every session, about 50 ms measured, plus a few `git` calls for QA/PM. `python3` (3.9+) and `git` must be on `PATH`. If `python3` is missing, `onFailure: "block"` blocks those tools for every agent, the orchestrator included: that is a deliberate fail-closed choice. **Recovery:** install Python 3 (`sudo apt-get install -y python3`), or, to get a working session first, start Claude Code with `claude --settings '{"disableAllHooks": true}'` (this also disables the guard, so don't run QA/PM agents in that session).
- **Follow-ups:** CI (#11) runs `scripts/test-hooks.sh`. Any change to the agents' scopes updates `SCOPES`, `team.md` and the agent files in the same PR.
