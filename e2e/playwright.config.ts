import { defineConfig, devices } from "@playwright/test";

/**
 * FitWise end-to-end tests (spec §10, §13). The same project runs against the local `make up`
 * stack, dev and prod; only the base URL changes.
 *
 * Base URL, first one set wins:
 *   1. E2E_BASE_URL  - set by you or by CD (e.g. http://<dev-host>)
 *   2. BASE_URL      - set by `make e2e` from the running compose stack's published port
 *   3. http://localhost:8088 - the `make up` default (HTTP_PORT in .env.example)
 */
const baseURL = (process.env.E2E_BASE_URL || process.env.BASE_URL || "http://localhost:8088").replace(/\/+$/, "");

const isCI = Boolean(process.env.CI);

// Only for an overloaded machine (a shared laptop or WSL): E2E_SLOW=5 multiplies every timeout.
// Never set in CI, dev or prod, where the budgets below are the acceptance criteria.
const slow = Math.max(1, Number(process.env.E2E_SLOW) || 1);

export default defineConfig({
  testDir: ".",
  testMatch: "**/*.spec.ts",
  outputDir: "test-results",
  // Every test creates its own account, so tests are independent of each other and of old data.
  fullyParallel: true,
  forbidOnly: isCI,
  // No retries: a smoke test that only passes on the second try is a failed deploy.
  retries: 0,
  workers: isCI ? 1 : undefined,
  // Whole-test budget. The smoke journey must finish in < 60 s against a local stack (#65).
  timeout: 60_000 * slow,
  expect: { timeout: 10_000 * slow },
  reporter: isCI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL,
    // FitWise is mobile-first: test at a phone viewport. A fixed, non-UTC time zone makes
    // "today in the user's time zone" a real check (the sign-up form defaults to this zone).
    ...devices["Pixel 7"],
    locale: "en-US",
    timezoneId: "Pacific/Auckland",
    navigationTimeout: 15_000 * slow,
    actionTimeout: 10_000 * slow,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "mobile-chromium" }],
});
