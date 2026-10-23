# ADR 0008: Guard the QA and PM write scopes with a project PreToolUse hook

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-10-21 (revised 2026-10-22: allow-list Bash check; re-scoped as a guardrail, not a security boundary) |
| **Deciders** | Owner, DevOps/SRE |
| **Spec** | [team.md — Roles](../team.md#roles), [process.md §6 QA verification](../process.md#6-qa-verification), [process.md §8 Changing the spec](../process.md#8-changing-the-spec), issue #60 |

## Context

[team.md](../team.md#roles) limits what two agents may write: **QA** only tests (`backend/tests/`, `frontend/tests/`, `e2e/`) and **PM** only `docs/` and `.github/ISSUE_TEMPLATE/`. Those limits started as instructions in the agent prompts. All agents get the same tools (`Read, Grep, Glob, Bash, Edit, Write`), because QA has to write test files and the PM has to edit docs, so nothing technical stopped either agent from editing application code. QA raised this on #2.

Both agents still need `gh`, `scripts/issue-status.sh`, read-only `git`/`grep`/`cat`; QA also needs `make`, the `uv`/`npm`/`docker` tool chain and `git commit` of test files. Taking `Edit`/`Write`/`Bash` away is not an option.

## What this guardrail is — and is not

This hook is a **guardrail against *accidental* out-of-scope writes** by the `qa`/`pm` agents: an `Edit`/`Write`/`NotebookEdit` to a file outside the agent's directories, or an ordinary shell write (`>`, `tee`, `cp`, `rm`, `sed -i`, `git commit` of out-of-scope files, …). It catches the mistakes an agent makes while doing its job, and it tells the agent what it may do instead.

It is **not a security boundary.** A determined or adversarial agent can still get around it, because QA legitimately runs tools that execute code, and those tools can be pointed at anything. We do **not** try to close every such path (three earlier rounds of deny-list whack-a-mole showed that is unwinnable). The families that remain open are named in "Known-not-covered" below. The protection that actually holds is the set of **backstops**: the `git add`/`git commit` check, QA's pre-verdict self-check, the **owner's review of every PR**, and (recommended) **branch protection on `main`**.

History: the Bash check began as a **deny-list** (#73, `a2e912b`/`84aaaf6`) and QA bypassed it twice by naming writers it didn't know. We inverted it to an **allow-list** (fail closed), which removed whole bypass families at once. A fourth QA round found more holes; the owner then re-scoped the issue to a guardrail and told us to close only the cheap, natural ones and stop chasing the rest. That is what this revision does.

## Decision

The hook is registered once in the committed [`.claude/settings.json`](../../.claude/settings.json) for `Write`, `Edit`, `MultiEdit`, `NotebookEdit`, `Bash` and `PowerShell`. It is split in two for latency:

- [`.claude/hooks/scope_guard.py`](../../.claude/hooks/scope_guard.py) — a tiny **entry shim** (only `json`/`sys`). It reads the event and, for any agent other than `qa`/`pm` (the main session, `engineer`, `devops`, built-ins), returns *allow* immediately without importing the checker.
- [`.claude/hooks/_guard_impl.py`](../../.claude/hooks/_guard_impl.py) — the checker, imported (and compiled once to a cached `.pyc`) only for `qa`/`pm`.

1. **Identify the agent** by `agent_type`. Only `qa`/`pm` are restricted.
2. **File tools.** The target (`file_path`/`notebook_path`) is made absolute and `realpath`-resolved (removing `..`, following existing symlinks), and allowed only if it lands in a work tree of the **same repository** (same git common dir as `$CLAUDE_PROJECT_DIR`, so every linked worktree counts) and its repo-relative path is inside the agent's scope. The scratchpad and `/dev/null`-type devices are allowed. A `/proc/<pid>/cwd`-or-`/root` path is denied (it would resolve against the hook's own process, not the shell's).
3. **Bash (allow-list, fail closed).** The command is parsed (quotes, `$(…)`/backticks, here-documents, `;`/`&&`/`||`/`|`/newlines, subshells, `cd`, redirections). Every simple command must pass:
   - The **command name must be a literal word** (no variable/substitution/quote/glob/brace), and must be on the per-role list; anything else is denied. Interpreters run directly (`bash x.sh`, `sh -c`, `eval`, `source`, `python -c`, `node -e`, `perl`, `ruby`, `awk`) are not on the list.
   - **Writers** (`mkdir`/`touch`/`rm`/`mv`/`cp`/`tee` and redirections `>`/`>>`/`&>`/`n>`) must write inside the scope (after brace/glob/`realpath`). **Links** (`ln`, `cp -s/-l`, `link`) are always denied. **Guarded readers** `sort`/`uniq`/`sed`/`find` are allowed only read-only. **Wrappers** are only `timeout` and `xargs` (xargs may run only a reader). `sudo`/`env VAR=…`/`nice`/… are not wrappers and are denied.
   - **Env-variable prefixes and `make`/`export` variable overrides** that redirect an allowed command to other code — `COMPOSE_FILE=`, `MAKEFILES=`, `MAKEFLAGS=`, `SHELL=`, `.SHELLFLAGS=`, `LD_PRELOAD=`, `NODE_OPTIONS=`, `GIT_SSH_COMMAND=`, … (a denylist, `DENY_ENV_NAMES`) — are denied both as `NAME=v cmd` prefixes and as `export`/`make FOO=bar` arguments.
   - **Unquoted here-document bodies** (`<<EOF`) that contain `$(…)`, backticks or `${…}` are denied (bash would expand them); a quoted delimiter (`<<'EOF'`) is literal and left alone.
   - **git** has its own allow-list: read-only subcommands pass; `add`/`commit`/`push`/`fetch`/`worktree`/`switch` (and for QA `checkout`/`restore` of in-scope paths, `merge`/`cherry-pick`/`stash`) are allowed with checks. `git -c <any key>` is denied (several keys run code). `git config` is allowed only as a `--get`/`--list` read. `git worktree add` into a path **inside the repo but out of scope** is denied (a new worktree outside the repo, QA's usual `../fitwise-wt/…`, is fine). `git push` is denied to `main`/`master`, with `--force`/`-f`, `--delete`, a `+` force refspec, `--receive-pack`/`--exec`, or an explicit URL. `git mv`/`rm`/`apply`/`am`/`reset`/`rebase`/`--git-dir`/`--work-tree` are denied.
   - **Tool output flags** (`--outDir`/`--outFile`/`--output`/`-o`/`-D`, attached or separate) on `npm`/`npx`/`gh`/`docker compose build|config` are checked as write targets. **curl** output flags (`-o`/`-O`/`-D`/`-c`/`-K`, attached clusters included, and `-w '%output{…}'`) are denied, and `curl` may only reach `localhost`/`127.0.0.1`/`::1`. **node** is allowed only to run a script file, not stdin/`-`/`-e`/`--print`.
   - A small set of **gh** holes is closed: `gh repo clone`, `gh run download`, `gh pr merge`, `gh pr checkout`. `gh` is otherwise left open (see Known-not-covered).
4. **Per-role allow-list** (full lists in `_guard_impl.py`: `READ_ONLY`, `QA_TOOLS`, `GIT_WRITE`, …).
   - **Both:** `gh`; `scripts/issue-status.sh`; read-only tools (`cat head tail … grep rg jq diff ls`, the process readers `ps pgrep ss lsof` and `kill`/`pkill`); `env` (no args), `command -v/-V`, `export` (literal, allow-listed names only); `sort uniq sed find` read-only; `cd pushd popd`; `timeout xargs`; writers `mkdir cp mv rm touch tee` in scope; `git` (as above).
   - **QA also:** `scripts/test-hooks.sh`; `make lint|test|e2e|up|down|clean|seed-demo` (no `-f`/`-C`, no `SHELL=`/`.SHELLFLAGS=`/`MAKEFILES=`); `uv run pytest|ruff|mypy|alembic|uvicorn`, `uv sync`; `uvx ruff|mypy|openapi-spec-validator`; `npm ci|test|run|exec` (`exec` holds its package to the npx list); `npx` with `@redocly/cli`/`playwright`/`tsc`/`vitest`/`openapi-typescript` (no version pins, no `-p <other>`); `node <script>`; `curl` localhost-only; `docker` (read-only + `compose ps|logs|exec|up|down|config|build`, no host mounts, no `-f`/`--project-directory`, no top-level `run`/`cp`/`build`/`exec`).
   - **PM** gets no build tool chain; its git writes are `add`/`commit`/`push`/`fetch`/`worktree`/`switch` of `docs/`/`.github/ISSUE_TEMPLATE/`.
5. **Non-Docker Postgres, non-system Node.** Integration tests use the Compose test database (`make test`, or `TEST_DATABASE_URL` at the running Compose `db-test` from #10) — a `venv`/`pip`/`pgserver` install is not available (`python`/`pip` are off the list). For a non-system Node, QA prefixes `PATH=<dir>:$PATH npm …` (assignment prefixes aren't commands); a binary by absolute/`~/` path is denied.
6. **Fail closed, with a clear message.** Anything unparseable or unrecognised is denied; the message names the command, says it isn't on the role's allow-list, and points here.

## Real backstops (what actually protects the repository)

1. **The `git add`/`git commit` check** in this hook: QA/PM cannot stage or commit an out-of-scope file through the normal git commands, whatever a tool wrote.
2. **QA's pre-verdict self-check** ([qa.md](../../.claude/agents/qa.md)): `git diff --name-only <verified-sha>..HEAD`, `git status --porcelain`, and `git log <verified-sha>..HEAD` must show only test-directory files and `test:` commits.
3. **Owner review of every PR** before merge — the decisive control.
4. **Branch protection on `main`** (recommended; owner decision pending): require a PR and a review, which closes the `gh pr merge` / push-to-`main` path for *every* agent regardless of this hook. `main` currently has no protection (`gh api …/branches/main/protection` → 404).
5. **OS-level sandboxing** (future work): running QA/PM in a container or with a read-only mount would make this a real boundary. It is heavy for the M0 tool chain and is deferred.

## Known-not-covered (accepted, by the guardrail re-scope)

These are **out of scope for the hook by design**; the backstops above are what cover them:

- **Tools that run repository code.** `make` (incl. `up`/`down`/`clean`/`seed-demo`), `uv run pytest|…|uvicorn`, `npm test`/`run`/`exec`, `npx playwright`/`vitest`, `node <script>`, `docker compose build`, `docker compose exec`, `scripts/*.sh`. A change to any of those files, or a script dropped in the writable scratchpad and then run, executes with QA's privileges. The git-commit check, QA's self-check and owner review are the backstop. (`docker compose exec` is also safe for the host tree only because `compose.yaml` declares no host bind mounts — checked 2026-10-22; re-assess if one is added.)
- **Tools configured to run code through options we don't model.** We deny `git -c`, the named code-running env vars, `make SHELL=`, curl's write flags, the common output flags and `node -e`/stdin — but not every possibility (e.g. an env var not in `DENY_ENV_NAMES`, a `playwright screenshot <positional-path>`, a tool-specific config file in scope).
- **`gh` beyond the four closed subcommands.** `gh` can call the GitHub API; `gh pr merge`/`checkout`, `repo clone`, `run download` are denied and `-o`/`-D`/`--output` are checked, but `gh api -X POST/PUT/DELETE`, `gh alias`/`extension`/`secret`, etc. are not. These don't write the local tree out of scope (the real concern here); merge-to-`main` is covered by branch protection.
- **Shell constructs the parser doesn't model:** process substitution `>(…)`, functions/aliases defined earlier in the same command, here-strings.
- **The guard needs `agent_type`.** A QA/PM prompt run as a plain main session (no subagent, no `--agent`) is unrestricted; the orchestrator always starts them as subagents.

## Corrections to earlier revisions of this ADR

- **`git config`** was listed as denied but was in the read-only set; it is now denied for any write form and allowed only for `--get`/`--list` reads, and `git -c <any key>` is denied (not just `hooksPath`/`alias`/`fsmonitor`/`include`).
- **`curl -o`** was only matched as a separate token; attached/clustered forms (`-oFILE`, `-sLo FILE`) and `-w '%output{…}'` are now denied too.
- **Here-documents** were skipped entirely; an unquoted body with `$(…)`/backticks/`${…}` is now denied.
- **Latency** was attributed to interpreter start-up only. The real split: the module import and compiling the ~1.4k-line checker on every call dominated. The **entry shim** (this revision) imports only `json`/`sys` and returns early for non-`qa`/`pm` sessions, and the checker is loaded (from a cached `.pyc`) only for `qa`/`pm`.

## Latency

Measured on the dev host (idle; bare `python3 -c pass` ≈ 12 ms):

| Path | Median |
|---|---|
| non-`qa`/`pm` session (shim early return) | ~20 ms |
| `qa` Bash `make test` | ~45 ms |
| `qa` `git add` + `commit` (spawns git) | ~55 ms |

Before the shim, every session paid ~70–90 ms (QA measured 91–101 ms under load) because the full checker was imported and recompiled on every call. The shim brings non-restricted sessions — the common case — down to roughly a bare interpreter start.

## Extending the allow-list

To add a command a restricted agent needs: add it to the relevant set in `_guard_impl.py` (plus a writer check if it writes), add allow **and** deny cases to `.claude/hooks/tests/test_scope_guard.py`, record it here, and get **owner approval** (every addition widens what an unsupervised agent can run).

## Consequences

- **Positive:** accidental out-of-scope writes by QA/PM are stopped before they happen, with a helpful message; the common bypasses QA found are closed; non-restricted sessions pay ~20 ms; the guard ships with the repo (fresh clone, worktrees, headless runs).
- **Negative:** it is not a boundary — see "Known-not-covered"; the honest protection is the backstops. `python3` (3.9+) and `git` must be on `PATH`; if `python3` is missing, `onFailure: "block"` blocks those tools for every agent (deliberate fail-closed). **Recovery:** install Python 3, or `claude --settings '{"disableAllHooks": true}'` (which also disables the guard, so don't run QA/PM in that session).
- **Follow-ups:** CI (#11) runs `scripts/test-hooks.sh`; the owner decides on branch protection for `main`; OS-level sandboxing remains available if the residual risk ever matters.

## Alternatives considered

| Option | Why not |
|---|---|
| Keep chasing every Bash bypass | Unwinnable; the owner re-scoped this to a guardrail. |
| A Bash **deny-list** | Must enumerate every writer; QA defeated it twice. |
| Frontmatter hooks on `qa`/`pm` | Don't run in `-p`/SDK sessions or before workspace trust. |
| Remove `Edit`/`Write`/`Bash` from the agents | They need them for in-scope work. |
| `permissions.deny` rules | Apply to every agent; can't express per-agent allow-dirs or shell writes. |
| OS sandbox / container | The real boundary; deferred as future work (heavy for M0). |
