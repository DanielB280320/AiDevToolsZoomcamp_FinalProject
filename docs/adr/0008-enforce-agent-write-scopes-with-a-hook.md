# ADR 0008: Enforce the QA and PM write scopes with a project PreToolUse hook

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-21 (revised 2026-10-22: Bash check is now an allow-list) |
| **Deciders** | Owner, DevOps/SRE |
| **Spec** | [team.md — Roles](../team.md#roles), [process.md §6 QA verification](../process.md#6-qa-verification), [process.md §8 Changing the spec](../process.md#8-changing-the-spec), issue #60 |

## Context

[team.md](../team.md#roles) limits what two agents may write: **QA** only tests (`backend/tests/`, `frontend/tests/`, `e2e/`) and **PM** only `docs/` and `.github/ISSUE_TEMPLATE/`. Until now those limits were instructions in the agent prompts. All agents get the same tools (`Read, Grep, Glob, Bash, Edit, Write`), because QA has to write test files and the PM has to edit docs. So nothing technical stopped either agent from editing application code. QA raised this on #2.

Both agents still need `gh` (comments, issue edits, PRs), `scripts/issue-status.sh`, read-only `git`/`grep`/`cat`. QA also needs `make lint`/`make test`/`make e2e`, the `uv`/`npm` test tool chain, and `git commit` of test files on a PR branch. Taking `Edit`/`Write`/`Bash` away is therefore not an option.

What Claude Code offers (hooks reference, checked against v2.1.308):

- Hooks in settings files also fire **inside subagents**. When they do, the input JSON has `agent_id` and `agent_type`, the `name` from the subagent's frontmatter (`qa`, `pm`). In the main session `agent_type` is missing. It is also set when a session is started with `claude --agent <name>`.
- Hooks can also be declared in a subagent's frontmatter, but **project subagent frontmatter hooks only run after the workspace trust dialog has been accepted, and a `-p` session does not count as accepting it**. Hooks in `.claude/settings.json` do run in `-p`/SDK sessions.
- A `PreToolUse` hook can return `permissionDecision: "deny"` with a reason, which Claude sees. Hooks run before permission rules and the permission prompt, and deny wins over every other hook decision. We checked that a deny also holds in `bypassPermissions` mode; see the demonstration on #60.
- `"onFailure": "block"` (v2.1.295+) blocks the tool call if the hook can't start, crashes or times out.

### Why the Bash check is an allow-list (revision)

The first two implementations (#73, commits `a2e912b` and `84aaaf6`) checked `Bash` with a **deny-list**: parse the command, find known write forms (`>`, `tee`, `sed -i`, `cp`, `rm`, `git add`/`commit`, wrappers, `find -exec`, brace expansion, …) and deny those. QA broke it twice ([round 1](https://github.com/DanielB280320/AiDevToolsZoomcamp_FinalProject/issues/60#issuecomment-6330735703), [round 2](https://github.com/DanielB280320/AiDevToolsZoomcamp_FinalProject/issues/60#issuecomment-6333527227)) with short, natural commands the deny-list didn't know: `xargs sed -i`, wrapper options, brace/glob tricks, `find -exec`, then symlink-then-write in one command, dynamic command names (`T=touch; $T …`), and a long tail of writers that were simply missing (`gzip`, `sort -o`, `split`, `mktemp`, `awk -i`, `tar`, `rsync`, …). A deny-list of "every program that can write a file" is unbounded; each round added rules and the next round found more.

The owner decided to **invert the Bash check to an allow-list**: only a known, small set of commands QA/PM actually need may run; everything the parser can't confidently classify as one of those is denied (fail closed). The universe of "things that write files" no longer has to be enumerated — a new writer is denied by default because it is not on the list.

## Decision

We enforce the scopes with **one project `PreToolUse` hook** in the committed [`.claude/settings.json`](../../.claude/settings.json). It runs [`.claude/hooks/scope_guard.py`](../../.claude/hooks/scope_guard.py) (Python 3 standard library only) for `Write`, `Edit`, `MultiEdit`, `NotebookEdit`, `Bash` and `PowerShell`:

1. **Identify the agent** by `agent_type`. Only `qa` and `pm` are restricted. Every other value, and a missing value (main session/orchestrator, `engineer`, `devops`, built-in agents), passes without any further checks. The `Edit`/`Write`/`MultiEdit`/`NotebookEdit` path checks are unchanged for everyone.
2. **File tools.** The target path (`file_path` / `notebook_path`) is made absolute and resolved with `realpath`, which removes `..` and follows symlinks for the parts that exist. It is allowed only if it falls in a work tree of the **same repository** (same git common dir as `$CLAUDE_PROJECT_DIR`, so every linked worktree counts) *and* its path relative to that work tree's root is inside the agent's scope. The session scratchpad (`scratchpad_dir`) and `/dev/null`-type devices are allowed too. Everything else is denied: other repositories, `$HOME`, `/etc`, and `.claude/` itself, so an agent can't edit the guard.
3. **Bash (allow-list).** The command is parsed (quotes, `$(…)`/backticks, here-documents, `;`/`&&`/`||`/`|`/newlines, subshells, `cd`, redirections). Every **simple command** on the line must pass, or the whole call is denied:
   - **The command name must be a literal word.** A name that is built from a variable or a substitution (`$T`, `"$T"`, `${T:-touch}`, `` `echo touch` ``, `$'touch'`, `$'\x74ouch'`, `"$(echo sed)"`), that is quoted/escaped, or that contains a glob or brace character, is denied — the parser can't know what runs. This closes the dynamic-command-name bypass.
   - **The command name must be on the per-role allow-list** (below). Anything else is denied with a message naming the command, the role, and how to request an addition. Running a script or interpreter directly (`bash x.sh`, `sh -c`, `eval`, `source`, `python3 -c`/`python3 x.py`, `node -e`, `perl`, `ruby`, `awk`) is **not** on the list and is therefore denied.
   - **Writers are checked against the scope.** For the writers that are on the list (`mkdir`, `touch`, `rm`, `mv`, `cp`, `tee`, shell redirections `>`/`>>`/`&>`/`n>`), every path they write — after brace expansion, glob expansion against the file system, and `realpath` — must be inside the agent's scope; `cp -t DIR`/the last argument is the destination.
   - **Guarded readers.** `sort` (denied with `-o`), `uniq` (denied with a second file argument), `sed` (denied with `-i` or a `w`/`W`/`e` script command), and `find` (denied with `-exec`/`-execdir`/`-ok`/`-okdir`/`-delete`/`-fprint*`/`-fls`) are allowed only in their read-only form.
   - **Links are always denied** for qa/pm: `ln`, `cp -s`, `cp -l`, `link`. A link created earlier in a command can't be trusted as a path component later in the same command (the "symlink race"), and tests don't need to create links, so the simplest safe rule is to forbid creating them at all.
   - **Wrappers.** Only `timeout` (bounds an allowed command) and `xargs` are unwrapped, after their own options are parsed from a table; an **unknown wrapper option denies the call**. Because `xargs`' arguments come from stdin, any **writer** it runs is denied, while a **reader** (`xargs grep`, `xargs wc -l`) passes. `sudo`, `env`, `nice`, `stdbuf`, `command`, `nohup`, … are no longer wrappers; they are just names that are not on the list, so they are denied.
   - **git** has its own allow-list: read-only subcommands pass; `add`/`commit`/`push`/`fetch`/`worktree`/`switch` (and for QA `checkout`/`restore` of in-scope paths) are allowed with the staging/path checks — `git add` uses `git add --dry-run`, `git commit` checks the staged files, the `-a` tracked changes and pathspecs; every other subcommand (`git mv`/`rm`/`apply`/`am`/`reset`/`rebase`/`config …`) is denied. `--git-dir`/`--work-tree` and `-c core.hooksPath=`/`-c alias.`/`-c include.` are denied.
   - **Brace sequences (`{1..3}`), empty-producing brace groups, and `xargs`/`find -exec` arguments** make a writer's targets "unknown"; a writer with unknown targets is denied, a reader passes, so `for i in {1..3}; do make test; done` still works.
4. **Per-role allow-list.**
   - **Both roles:** `gh`; `scripts/issue-status.sh` (resolved under `scripts/`); read-only tools `cat head tail less more wc grep egrep fgrep rg jq diff ls cut tr comm column nl printf echo test [ true false pwd basename dirname realpath stat date which sleep`, `env` (no arguments), `command -v`/`-V`; guarded readers `sort uniq sed find`; navigation `cd pushd popd`; wrappers `timeout xargs`; writers `mkdir cp mv rm touch tee` (in-scope targets only); `git` (as above).
   - **QA also:** `scripts/test-hooks.sh`; `make` (`lint`/`test`/`e2e` targets only, no `-f`/`-C`); `uv run` with `pytest`/`ruff`/`mypy`/`alembic` and `uv sync`; `uvx` with `ruff`/`mypy`/`openapi-spec-validator`; `npm ci`/`test`/`run <script>`/`exec`; `npx` with `@redocly/cli`/`playwright`/`tsc`/`vitest`/`openapi-typescript`; `node` to run a script file (not `-e`/`--print`); `curl` to `localhost`/`127.0.0.1` only, without `-o`/`-O`/`--output`/`-c`.
   - **PM** does not get the build tool chain (`make`/`uv`/`npm`/`npx`/`node`/`curl`/`test-hooks.sh`); its git write subcommands are `add`/`commit`/`push`/`fetch`/`worktree`/`switch` of `docs/`/`.github/ISSUE_TEMPLATE/` paths.
5. **Fail closed.** Anything the parser can't confidently understand, any internal error, and any name not on the list is denied for `qa`/`pm`. Input that can't be parsed exits 2, and `onFailure: "block"` blocks the call if the hook can't run at all.
6. **The deny message** names the command, says it isn't on the agent's allow-list, and points to this ADR and to "request adding it (ADR + owner approval)", for example: *"FitWise scope guard blocked this Bash call. The qa agent may only write under backend/tests/, frontend/tests/, e2e/ and run an allow-listed set of commands (docs/team.md, ADR 0008). Reason: gzip is not on the qa allow-list; see ADR 0008 to request adding it (ADR + owner approval). QA writes tests only; …"*

The scopes and the allow-lists live in one place, in `scope_guard.py` (`SCOPES`, `READ_ONLY`, `QA_TOOLS`, `GIT_WRITE`, …). They must match [team.md](../team.md#roles); changing them needs a PR that updates both. Tests: `scripts/test-hooks.sh`, a table-driven `unittest` suite run against a throw-away git repository with worktrees and symlinks, with a deny case for every bypass from both QA rounds. Once CI exists (#11) it runs there.

## Extending the allow-list

To add a command a restricted agent needs (or to widen git/`make`/`uvx`/`npx`), open a PR that:
1. adds the name (or option) to the relevant set in `scope_guard.py` and, if it writes, a writer handler that checks its targets against the scope;
2. adds allow **and** deny cases to `.claude/hooks/tests/test_scope_guard.py`;
3. records the addition in this ADR's Decision §4 with a one-line justification;
4. gets **owner approval**, because every addition widens what an unsupervised QA/PM agent can run.

## Alternatives considered

| Option | Why not |
|---|---|
| Keep the Bash **deny-list** | It has to enumerate every program that can write a file. QA defeated it twice with short, ordinary commands; the universe is unbounded. |
| Hooks in the `qa`/`pm` frontmatter | Project subagent frontmatter hooks don't run in `-p`/SDK sessions or before workspace trust, so the guard would silently switch off in headless runs. It would also mean two copies of the logic. |
| Remove `Edit`/`Write`/`Bash` from the agents' `tools` | Both agents need them for in-scope work: test files, docs, `gh`, `make test`. |
| `permissions.deny` rules such as `Edit(backend/app/**)` in settings | Permission rules apply to every agent, including the engineer. They can't express "allow only these directories for this agent", and they don't cover shell writes. |
| Run QA/PM in a sandbox or container with a read-only mount | Strong, but heavy for the M0 tool chain, and it breaks worktrees and `make test` against the Compose stack. It is still the fallback if the residual risk below becomes a problem. |
| Rely on review only | That is the gap QA reported on #2. |

## Consequences

- **Positive:** A QA or PM agent that tries to write outside its scope, or to run anything but a small, reviewed set of commands, is stopped before the write, with a message that tells it what to do instead. The allow-list fails closed, so a writer the hook has never heard of (`gzip`, `sort -o`, a new formatter, a one-off script) is denied by default rather than slipping through. Engineer, DevOps and the orchestrator are not affected. The guard ships with the repo, so it works in a fresh clone, in every git worktree and in headless runs.
- **Negative / accepted risks:** The hook is still a check over a parsed command line, not a sandbox.
  - **Allow-listed tools can run arbitrary repository code.** `make test`/`make lint`/`make e2e`, `uv run pytest`/`ruff`/`mypy`/`alembic`, `npm test`/`run`/`exec`, `npx playwright`/`vitest`, `node <script>`, `scripts/test-hooks.sh` and `scripts/issue-status.sh` all execute project code (Makefile targets, test suites, npm scripts, project scripts). A malicious change to any of those files could write outside the scope when QA runs it. These tools are on the list because QA genuinely needs them; the backstop is that **such a change would itself be an out-of-scope edit** (blocked by this hook), the **`git add`/`git commit` check** stops QA committing whatever a tool wrote, QA's own self-check scans its diff, and **owner review** is the last line.
  - **Shell constructs the parser doesn't model** are denied when they affect a command (good) but a few are simply out of reach: process substitution `>(…)`, shell functions and aliases defined earlier in the same command, and here-strings. Because the command that would use them still has to be an allow-listed name, the exposure is small.
  - **`node <script.js>`** runs arbitrary JavaScript, like `make`; it is allowed for QA because the frontend tooling (`generate-api.mjs`, Playwright helpers) needs it. Same backstops as `make`.
  - **The guard depends on Claude Code passing `agent_type`**, which it does for subagents and `--agent` sessions. A PM or QA prompt run as a **plain main session** (no subagent, no `--agent`) is not restricted. The orchestrator must always start them as subagents (`team.md`, "Running the team").
  - **A Claude Code plugin *mod*** that handles the `tool.check` event can, in some credential setups, approve a call a hook blocked. The project installs no mods; adding one needs owner approval.
- **Mitigation / backstop:** Before posting a verdict QA runs `git diff --name-only <verified-sha>..HEAD` (only the commits QA added on top of the PR head it verified), `git status --porcelain`, and `git log <verified-sha>..HEAD` (every commit must start with `test:`) on its worktree, and confirms that every file it changed is under `backend/tests/`, `frontend/tests/` or `e2e/` ([qa.md](../../.claude/agents/qa.md)). The owner's PR review is the last line.
- **Negative:** The hook runs `python3` on every write-capable tool call in every session, about 50 ms measured, plus a few `git` calls for QA/PM. `python3` (3.9+) and `git` must be on `PATH`. If `python3` is missing, `onFailure: "block"` blocks those tools for every agent, the orchestrator included: that is a deliberate fail-closed choice. **Recovery:** install Python 3 (`sudo apt-get install -y python3`), or, to get a working session first, start Claude Code with `claude --settings '{"disableAllHooks": true}'` (this also disables the guard, so don't run QA/PM agents in that session).
- **Follow-ups:** CI (#11) runs `scripts/test-hooks.sh`. Any change to the agents' scopes or allow-lists updates `scope_guard.py`, `team.md` and the agent files in the same PR, with owner approval.
