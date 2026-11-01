import { randomBytes } from "node:crypto";

import { expect, test } from "@playwright/test";

import { completeWizardInUi, expectToday, signUpInUi } from "./helpers";

/**
 * Smoke journey (#65, spec §10 journey 1 in its M1 form, §13 post-deploy smoke):
 * sign up a fresh athlete -> onboarding wizard -> Today -> sign out -> sign in -> Today.
 *
 * Runs unchanged against `make up`, dev and prod (base URL: playwright.config.ts), so it only uses
 * fake data: a unique address on the reserved `.test` domain (RFC 2606, never deliverable), a
 * made-up display name and a random throwaway password. Every run creates a new account, so it
 * never depends on, or collides with, data from earlier runs.
 */

test("smoke: sign up a new athlete, see Today, sign out, sign in again", { tag: "@smoke" }, async ({ page }) => {
  const startedAt = new Date();
  const run = `${startedAt.getTime()}-${randomBytes(3).toString("hex")}`;
  const email = `smoke+${run}@example.test`;
  const password = `smoke-${randomBytes(12).toString("hex")}`; // throwaway, >= 10 characters
  const displayName = `Smoke Athlete ${run.slice(-6)}`;

  await test.step("sign up as an athlete and accept the disclaimer", async () => {
    await signUpInUi(page, { email, password, displayName });
  });

  await test.step("completes the onboarding wizard and reads the targets before leaving", async () => {
    await completeWizardInUi(page);
    await page.getByRole("link", { name: "Go to Today" }).click();
  });

  await test.step("lands on Today with the display name and today's date", async () => {
    await expectToday(page, displayName, startedAt);
  });

  await test.step("sign out", async () => {
    await page.getByRole("button", { name: "Sign out" }).click();
    await expect(page).toHaveURL(/\/sign-in$/);
    await expect(page.getByRole("heading", { level: 1, name: "Sign in" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);

    // The session is really gone: Today now sends the visitor to sign-in.
    await page.goto("/today");
    await expect(page).toHaveURL(/\/sign-in$/);
  });

  await test.step("sign in again and see Today", async () => {
    await page.getByLabel("Email", { exact: true }).fill(email);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByRole("button", { name: "Sign in", exact: true }).click();

    await expectToday(page, displayName, startedAt);
  });
});
