# Development process

How work moves from an idea to production in FitWise. Who does each step is defined in [team.md](team.md); what to build is defined in [spec.md](spec.md).

```
 spec.md ──► PM grooms issue ──► Ready ──► Engineer implements ──► PR ──► QA verifies ──► owner merges ──► dev ──► prod
   ▲                                          (branch + worktree)        (CI green)                    (auto)   (manual)
   └──────────── spec/ADR updated in the same PR whenever behaviour changes ◄───────────────────────────────┘
```

## 1. Where work is tracked

- **GitHub Issues** — one issue per deliverable, with acceptance criteria (AC), spec references and dependencies.
- **[FitWise Backlog board](https://github.com/users/DanielB280320/projects/1)** — public view of the same issues by status.
- **Milestones `M0`–`M6`** — the delivery order from [spec §16.2](spec.md#162-delivery-order-walking-skeleton-first). Work on a later milestone only starts when the issues it depends on are done.

### Labels

| Group | Labels | Meaning |
|---|---|---|
| Status | `status:backlog`, `status:ready`, `status:in-progress`, `status:in-qa`, `status:blocked` | Where the issue is in the workflow (see §2). Exactly one at a time; none once closed. |
| Role | `role:pm`, `role:engineer`, `role:qa`, `role:devops` | Which agent owns the implementation. QA always verifies, whatever the role. |
| Area | `area:backend`, `area:frontend`, `area:engine`, `area:infra`, `area:observability`, `area:oncall`, `area:docs`, `area:testing` | Part of the system touched. |
| Priority | `priority:must`, `priority:should` | MVP scope vs. if-time-allows ([spec §16.1](spec.md#161-priorities)). |

### Status labels ↔ board columns

| Status label | Board column | Entered when | Moved by |
|---|---|---|---|
| `status:backlog` | Backlog | Issue created but not yet groomed, or dependencies still open | PM |
| `status:ready` | Ready | Groomed (§3) and every dependency is closed | PM |
| `status:in-progress` | In progress | An implementer starts work, or QA reports FAIL | Engineer / DevOps; QA on FAIL |
| `status:in-qa` | In QA | PR open, CI green, implementer's self-check done | Engineer / DevOps |
| `status:blocked` | *(card stays in its column)* | Waiting on another issue or a decision; the reason is commented | Anyone |
| *(no label, issue closed)* | Done | PR merged after QA pass | Closed automatically by `Closes #N` |

Always change status with the helper so the label and the board never disagree:

```bash
scripts/issue-status.sh <issue> <backlog|ready|in-progress|in-qa|blocked|done>
```

## 2. Issue lifecycle

1. **Backlog** — the PM writes or refines the issue from the spec.
2. **Ready** — the PM confirms the Definition of Ready (§3) and moves it.
3. **In progress** — an implementer comments "Started on branch `<branch>`", moves it, and works in a dedicated branch/worktree (§4).
4. **In QA** — the implementer opens a PR, posts a self-check against every AC, and moves it.
5. **QA verdict** — QA verifies independently (§6) and comments **PASS** or **FAIL** on the issue.
   - FAIL → back to **In progress** with the failing AC listed.
   - PASS → the repository owner merges.
6. **Done** — merging the PR closes the issue (`Closes #N`); the PM moves newly unblocked issues to **Ready**.

Every transition leaves a comment on the issue. The issue thread is the audit trail showing which agent did what.

## 3. Definition of Ready (PM)

An issue can move to **Ready** only when:

- [ ] It references the spec sections it implements.
- [ ] Every AC is observable and testable (no "works well", "is fast" without numbers).
- [ ] Dependencies are listed and all of them are closed.
- [ ] It fits in one PR (roughly ≤ 1 day of work). Otherwise the PM splits it.
- [ ] Open questions are answered in the spec, the decisions log (spec §19) or an ADR.

## 4. Branches, worktrees and commits

- **One issue → one branch → one PR.** Branch name: `<type>/<issue>-<short-slug>`, where type is `feat`, `fix`, `docs`, `test`, `infra` or `chore`. Example: `feat/21-targets-engine`.
- **Parallel work uses git worktrees** so agents never share a working directory:
  ```bash
  git worktree add ../fitwise-wt/21 -b feat/21-targets-engine origin/main
  # ... work, commit, push, open PR ...
  git worktree remove ../fitwise-wt/21
  ```
- **Parallelism rules** (the orchestrator checks these before starting issues side by side):
  - Only issues in **Ready** with no dependency on each other.
  - At most **3** implementation worktrees at once.
  - Two issues that both add **Alembic migrations** or both edit `openapi.yaml` run one after the other, never in parallel. A PR that conflicts on these files rebases onto `main` and regenerates.
- **Commits**: imperative subject ≤ 72 characters (e.g. "Add Navy body-fat estimate to targets engine"), body explains why. Agent-authored commits end with the `Co-Authored-By` trailer.
- **Never push to `main`.** `main` is protected: PR + green CI required.

## 5. Pull requests

- Opened by the implementer with the [PR template](../.github/pull_request_template.md): summary, `Closes #N`, AC checklist with evidence, how it was tested, spec/doc changes, screenshots for UI.
- **Must be green in CI** before QA starts.
- **Behaviour changes update `docs/spec.md` in the same PR** (and the decisions log or an ADR for design choices). A PR that changes behaviour without a spec change fails QA.
- **API changes start in `openapi.yaml`**; the generated frontend client is regenerated in the same PR.
- **Merging** is done by the repository owner (the human) with **squash merge**, after QA PASS. The squash commit keeps `Closes #N`.

## 6. QA verification

QA is independent of the implementer: it starts from the issue and the spec, not from the PR description.

For each PR, QA:

1. Checks out the branch in its own worktree. For lint and tests it cites CI when CI is green **for the exact head SHA** and the required jobs ran; otherwise it runs `make lint` and `make test` itself. It runs `make e2e` when the issue touches a user journey and CI does not, and locally runs the tests that exercise the AC.
2. Verifies **every acceptance criterion** one by one: reproduces it (test, API call or UI step) and records the evidence. Each AC is judged as written; problems outside the AC are reported (new issue or `Notes:`) without failing the PR.
3. Checks the rules in [CLAUDE.md](../CLAUDE.md#rules-for-every-agent): spec updated, tests added, no sensitive data in telemetry, migrations backward compatible, no secrets. These always block, whether or not an AC mentions them.
4. May add or strengthen **tests** in the PR branch (commit prefix `test:`). QA never changes production code; it reports defects instead.
5. Comments on the issue:

```markdown
## QA: PASS | FAIL
PR: #<pr>   Commit: <sha>
| AC | Result | Evidence |
|---|---|---|
| F1.1 … | ✅ / ❌ | test name, command output or screenshot |
Notes: …
```

**Re-verification after a FAIL** covers the failing AC, every AC whose code the fix touched (diff since the last verified SHA) and the CLAUDE.md rules on that diff, with CI cited for the new SHA; unchanged passing AC keep their earlier evidence. **After 3 FAILs** on the same issue, QA moves it to `blocked` and escalates to the owner instead of starting another round.

QA reads only the spec sections the issue references, the sections they link to, and the decisions log (§19).

## 7. Definition of Done

Same as [CLAUDE.md — Definition of done](../CLAUDE.md#definition-of-done): all AC met and checked off, lint and tests green locally and in CI, tests cover the new behaviour, docs/spec updated, QA PASS commented, PR merged with `Closes #N`.

## 8. Changing the spec

- Small clarifications discovered during implementation: update `docs/spec.md` in the implementing PR and mention it in the PR description.
- Scope changes (new feature, dropped feature, priority change): the PM opens a `docs/` PR that edits the spec and creates, edits or closes the affected issues. The owner approves it.
- Design decisions with trade-offs: an ADR in `docs/adr/` linked from the spec.

## 9. Releases

| Step | Trigger | Who |
|---|---|---|
| Deploy to **dev** | Every merge to `main` (CI builds images tagged with the commit SHA, deploys, runs smoke tests) | Automatic |
| Promote to **prod** | `Promote to production` workflow with a SHA already running on dev; requires approval in the `production` environment | Owner approves; DevOps prepares |
| **Rollback** | Automatic when the prod smoke test fails; manual `Rollback production` workflow; or the on-call agent's `rollback.sh` | Automatic / owner / on-call agent |

Details: [spec §12–13](spec.md#12-deployment-aws).

## 10. Incidents

1. A user-impact alert fires in Grafana ([spec §15.1](spec.md#151-alerts-grafana-managed-provisioned-as-code-envprod)).
2. The **on-call agent** investigates, applies one allow-listed mitigation (feature flag, rollback or restart) and verifies recovery.
3. It opens an issue labelled `incident` with the timeline, evidence and mitigation, and a PR with the root-cause fix.
4. The fix PR goes through this same process (QA, merge, dev, prod). Nothing reaches prod outside the pipeline.
5. The DevOps agent updates the relevant runbook in `docs/runbooks/` if the incident revealed a gap.

## 11. The human's role

The repository owner is the product owner. They decide scope and priorities, answer open questions, merge PRs after QA PASS, approve production promotions, and review the on-call agent's incident reports and fix PRs.
