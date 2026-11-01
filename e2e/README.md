# FitWise end-to-end tests

Playwright journeys from [spec §10](../docs/spec.md#10-testing-strategy). The same tests run
against the local stack, dev and prod; only the base URL changes. CD runs the smoke test after
every deploy ([spec §13](../docs/spec.md#13-cicd-github-actions)).

| Spec file | Journey | Budget |
|---|---|---|
| `smoke.spec.ts` | Sign up a new athlete (unique `smoke+<timestamp>-<random>@example.test`), accept the disclaimer, see Today with the display name and today's date in the user's time zone, sign out, sign in again, see Today | < 60 s (the test timeout) |
| `coach-dashboard.spec.ts` | A coach signs in, sees the client list, opens a linked athlete (Today, Month, Progress), accepts one suggestion and rejects another, edits the plan; the athlete sees both decisions as made by the coach and "Edited by <coach>". A second test checks the coach context at 360 px (no horizontal scroll, 44 px targets) | < 60 s each |

## Run it locally

```bash
make up      # start the stack (returns when every service is healthy)
make e2e     # npm ci, install Chromium, run every spec against the stack
```

`make e2e` exits non-zero when any assertion fails. It needs Node.js 24 (`frontend/.nvmrc`) and
the Playwright system libraries for Chromium; on a fresh Linux machine run
`cd e2e && npx playwright install --with-deps chromium` once.

Without `make`:

```bash
cd e2e
npm ci
npx playwright install chromium
npx playwright test                 # every spec
npx playwright test smoke.spec.ts   # the smoke journey only (= npm run smoke)
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

On failure, Playwright keeps a trace and a screenshot in `test-results/` (git-ignored). Open a
trace with `npx playwright show-trace test-results/<test>/trace.zip`. Traces contain the fake
form input of that run only.
