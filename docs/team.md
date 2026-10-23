# Agent team

FitWise is built by a small team of Claude Code agents coordinated by an orchestrator, with the repository owner as product owner. This document says who does what; [process.md](process.md) says how work flows between them.

```
                       ┌──────────────────────────┐
                       │  Owner (human)           │  scope, priorities, merges, prod approvals
                       └────────────┬─────────────┘
                                    │
                       ┌────────────▼─────────────┐
                       │  Orchestrator            │  main Claude Code session
                       │  (follows process.md)    │  picks Ready issues, dispatches agents
                       └─┬──────┬───────┬───────┬─┘
                         │      │       │       │
                    ┌────▼─┐ ┌──▼─────┐ ┌▼────┐ ┌▼───────┐
                    │  PM  │ │Engineer│ │ QA  │ │DevOps/ │
                    │      │ │ (×≤3)  │ │     │ │  SRE   │
                    └──────┘ └────────┘ └─────┘ └────────┘
                   grooms     builds    verifies  infra, CI/CD,
                   issues     features  AC        observability,
                                                  on-call
```

Agent definitions live in [`.claude/agents/`](../.claude/agents/). Each runs as a Claude Code subagent with its own context, so the orchestrator's session stays small and each agent sees only what its task needs.

The **QA and PM write scopes below are guarded**, not just documented (a guardrail against accidental out-of-scope writes, not a security boundary; ADR 0008): a `PreToolUse` hook in [`.claude/settings.json`](../.claude/settings.json) ([`scope_guard.py`](../.claude/hooks/scope_guard.py), [ADR 0008](adr/0008-enforce-agent-write-scopes-with-a-hook.md)) blocks their `Edit`/`Write`/`NotebookEdit` calls outside their directories, and checks every `Bash` command against a **per-role allow-list**: only a small, reviewed set of commands QA/PM actually need may run, writers must target their own directories, and anything else — an unknown program, a dynamic command name, an interpreter, a shell write out of scope — is denied (fail closed) with a message naming the command and the allowed directories. The hook is a guardrail, not a boundary: a determined agent can still write through tools that run repository code, so the real backstops are the git add/commit check, QA's self-check and the owner's PR review. Engineer, DevOps and the main session are not affected. Tests: `scripts/test-hooks.sh`.

## Roles

### Owner (human)
- Decides scope and priorities; answers questions agents escalate.
- Merges PRs after QA PASS; approves production promotions.
- Reviews incident reports and fix PRs from the on-call agent.

### Orchestrator (main session)
- Reads `CLAUDE.md`, the board and the milestone order; never implements features itself.
- Asks the **PM** to groom the next issues; starts **Engineer**/**DevOps** agents on Ready issues (in parallel only within the rules of [process.md §4](process.md#4-branches-worktrees-and-commits)); sends finished PRs to **QA**; reports results to the owner.
- Escalates to the owner instead of guessing when the spec doesn't answer a question.

### PM — [`pm.md`](../.claude/agents/pm.md)
- **Owns:** the backlog and the spec's consistency.
- **Does:** turns spec sections into issues with testable AC; applies the Definition of Ready; splits large issues; moves issues Backlog → Ready when dependencies close; proposes spec changes as `docs/` PRs; keeps the decisions log current.
- **Writes:** issues, issue comments, `docs/` and `.github/ISSUE_TEMPLATE/` only. Never production code or tests. *Guarded by the scope-guard hook.*

### Engineer — [`engineer.md`](../.claude/agents/engineer.md)
- **Owns:** implementation of `role:engineer` issues (backend, frontend, engines).
- **Does:** works one issue per branch/worktree; contract first (`openapi.yaml`), tests with every change; updates the spec when behaviour changes; opens the PR with a self-check against every AC; moves the issue to In QA.
- **Writes:** application code, tests, migrations, `openapi.yaml`, related docs.

### QA — [`qa.md`](../.claude/agents/qa.md)
- **Owns:** independent verification. Nothing is merged without a QA PASS.
- **Does:** starts from the issue and the spec, not the PR description; runs lint and tests; reproduces each AC with evidence; checks the project rules (privacy, migrations, spec updated); posts PASS/FAIL on the issue in the standard format.
- **Writes:** tests only (`backend/tests/`, `frontend/tests/`, `e2e/`; commits prefixed `test:`) and issue/PR comments. Never changes production code — it reports defects. *Guarded by the scope-guard hook.*

### DevOps / SRE — [`devops.md`](../.claude/agents/devops.md)
- **Owns:** `role:devops` issues: Docker/Compose, AWS, CI/CD, observability, alerts, the on-call responder and runbooks.
- **Does:** keeps `make up`/`make test` single-command; makes deployments reproducible and rollbackable; keeps telemetry free of sensitive data; writes runbooks the on-call agent follows.
- **Writes:** `deploy/`, `.github/workflows/`, `observability/`, `oncall/`, `compose*.yaml`, `Makefile`, Dockerfiles, `docs/runbooks/`.

### On-call responder (runtime agent, not a subagent)
A headless Claude Code process on the prod host, started by Grafana alerts ([spec §15.2](spec.md#152-on-call-responder)). It is restricted to allow-listed mitigations (feature flag, rollback, restart), then opens an `incident` issue and a fix PR that goes through the normal process. Its prompt and allow-list are owned by DevOps.

## Hand-offs

| From → To | Trigger | Artifact |
|---|---|---|
| Owner → PM | New idea or scope change | Spec edit request |
| PM → Orchestrator | Issue meets Definition of Ready | Issue in **Ready** |
| Orchestrator → Engineer/DevOps | Ready issue picked | Issue number + worktree path |
| Engineer/DevOps → QA | PR open, CI green, self-check posted | PR in **In QA** |
| QA → Engineer/DevOps | QA FAIL | FAIL comment listing failing AC |
| QA → Owner | QA PASS | PASS comment; PR ready to merge |
| Owner → PM | PR merged | PM moves newly unblocked issues to **Ready** |
| Alert → On-call → Owner | Production alert | Mitigation, `incident` issue, fix PR |

## Working agreements

- **The issue thread is the record.** Every agent comments when it starts, hands off or finishes, so the tracker shows which agent did what.
- **Separation of duties.** The agent that wrote the code never QA-passes it.
- **One issue at a time per agent**, each in its own worktree.
- **Escalate, don't guess.** Ambiguity goes to the orchestrator and then to the owner, and the answer goes into the spec.
- **Status changes use `scripts/issue-status.sh`**, so labels and the board stay in sync.

## Running the team

From the main session (the orchestrator):

```text
Use the pm agent to groom milestone M1 and move issues whose dependencies are closed to Ready.
Use the engineer agent on issue #6 in a worktree.
Use the qa agent to verify PR #<n> for issue #6.
```

Always start the PM and QA **as subagents** (as above, or with `claude --agent pm|qa`): the scope guard recognises them by the subagent's `agent_type`, so a PM or QA prompt pasted into a plain main session is not restricted.

For parallel work, start up to three engineer/devops agents on independent Ready issues, each with worktree isolation, then send each PR to QA as it finishes.

### Models and effort

Implementation runs on a cheaper model: the issues are already groomed with acceptance criteria, so the engineer and DevOps agents only have to implement them (owner decision, 2026-10-23).

| Agent | Model | Effort | Where it is set |
|---|---|---|---|
| engineer | Sonnet | medium | `model:` / `effort:` in [`engineer.md`](../.claude/agents/engineer.md) frontmatter |
| devops | Sonnet | medium | `model:` / `effort:` in [`devops.md`](../.claude/agents/devops.md) frontmatter |
| pm, qa | inherit the main session's model | default | not pinned |

The orchestrator does **not** pass a `model` or `effort` override when starting engineer or DevOps agents, so the frontmatter is what applies. Change the model only by editing the frontmatter in a PR and updating this table.
