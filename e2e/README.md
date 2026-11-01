# FitWise end-to-end tests

Playwright journeys from [spec §10](../docs/spec.md#10-testing-strategy). The same tests run
against the local stack, dev and prod; only the base URL changes. CD runs the smoke test after
every deploy ([spec §13](../docs/spec.md#13-cicd-github-actions)).

| Spec file | Journey | Budget | Smoke |
|---|---|---|---|
| `smoke.spec.ts` | Sign up a new athlete in the UI (unique `smoke+<timestamp>-<random>@example.test`), accept the disclaimer, onboarding wizard, see Today with the display name and today's date in the user's time zone, sign out, sign in again, see Today | < 60 s | yes |
| `journey-onboarding.spec.ts` | Journey 1: sign up and the onboarding wizard in the UI, land on Today with today's session (or rest day), meals and macro targets, calorie target read on the "plan is ready" screen; reload keeps the user signed in | < 60 s | yes |
| `journey-training.spec.ts` | Journey 2: open today's workout, log every set of one exercise above its rep target, finish (100 %), read the suggestion and its reason on Today, accept it, see it as accepted and as the exercise's next target (Plan and next session) | < 60 s | no |
| `journey-meals.spec.ts` | Journey 3: check off a planned meal, eaten kcal and balance change by exactly the meal's kcal, undo restores both | < 60 s | no |
| `journey-coach.spec.ts` | Journey 4: athlete requests a coach by email, coach approves, opens the athlete's Progress page and a session chart with data, leaves a note; athlete sees the `coach_note` notification and the note | < 60 s | no |
| `coach-dashboard.spec.ts` | A coach signs in, sees the client list, opens a linked athlete (Today, Month, Progress), accepts one suggestion and rejects another, edits the plan; the athlete sees both decisions as made by the coach and "Edited by <coach>". A second test checks the coach context at 360 px (no horizontal scroll, 44 px targets) | < 60 s each | no |

Shared setup (API sign-up, onboarding with a training day today, coach link, the UI sign-up and
wizard steps) is in `helpers.ts`.

**Smoke subset** = the tests tagged `@smoke` (`smoke.spec.ts` and journey 1). `npm run smoke`
(`playwright test --grep @smoke`) runs only these; the post-deploy jobs against dev and prod and the
production rollback verification use it, and its total budget is 2 minutes. `make e2e` and the CI
`e2e` job run every spec.

## Run it locally

```bash
make up      # start the stack (returns when every service is healthy)
make e2e     # npm ci, install Chromium, run every spec against the stack
```

`make e2e` runs every spec, exits non-zero when any assertion fails, and exits non-zero with
"run 'make up' first" when the stack is not running. It needs Node.js 24 (`frontend/.nvmrc`) and
the Playwright system libraries for Chromium; on a fresh Linux machine run
`cd e2e && npx playwright install --with-deps chromium` once.

Without `make`:

```bash
cd e2e
npm ci
npx playwright install chromium
npx playwright test                 # every spec
npm run smoke                       # the @smoke subset only (what runs after a deploy)
```

## Base URL

The target is the first of these that is set (`playwright.config.ts`):

| Variable | Set by | Example |
|---|---|---|
| `E2E_BASE_URL` | You, or the CD workflow | `E2E_BASE_URL=http://<dev-public-dns> npx playwright test` |
| `BASE_URL` | `make e2e`, from the published port of the running compose stack | `http://localhost:8088` |
| *(default)* | — | `http://localhost:8088`, the `make up` URL with the default `HTTP_PORT` |

Use `E2E_BASE_URL` to point the tests at a deployed environment. A worktree stack on another
port (see the root README, "Several stacks side by side") is picked up by `make e2e`
automatically, or set `E2E_BASE_URL=http://localhost:<HTTP_PORT>`.

## Rules for these tests

- **Fake data only.** Addresses on the reserved `.test` domain (RFC 2606, never deliverable),
  made-up display names, random throwaway passwords. Never a real person's name or email: the
  smoke test also runs against prod.
- **Independent and repeatable.** Each test creates its own account; nothing depends on data from
  an earlier run or another test, and no test cleans up after another.
- **No fixed sleeps.** Wait on what the user would see (web-first `expect` assertions, URL
  changes), never `waitForTimeout`.
- **No retries.** A smoke test that only passes on the second attempt is a failed deploy.
- **Only the stack under test.** No calls to third-party services.
- **Mobile first.** Tests run at a phone viewport (Pixel 7, Chromium) in a fixed non-UTC time zone
  (`Pacific/Auckland`), so "today in the user's time zone" is a real check.

## Headless CI

The CI `e2e` job runs every spec in the official Playwright container with `CI=true`: headless
Chromium, 1 worker, 0 retries, `forbidOnly`, against the compose stack. It uploads
`playwright-report/` and the traces when it fails. Set `E2E_SLOW=<factor>` to multiply every timeout
on a machine that is overloaded; never in CI, dev or prod.

On failure, Playwright keeps a trace and a screenshot in `test-results/` (git-ignored). Open a
trace with `npx playwright show-trace test-results/<test>/trace.zip`. Traces contain the fake
form input of that run only.
