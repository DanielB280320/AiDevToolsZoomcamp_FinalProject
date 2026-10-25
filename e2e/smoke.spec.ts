import { randomBytes } from "node:crypto";

import { expect, type Page, test } from "@playwright/test";

/**
 * Smoke journey (#65, spec §10 journey 1 in its M1 form, §13 post-deploy smoke):
 * sign up a fresh athlete -> onboarding wizard -> Today -> sign out -> sign in -> Today.
 *
 * Runs unchanged against `make up`, dev and prod (base URL: playwright.config.ts), so it only uses
 * fake data: a unique address on the reserved `.test` domain (RFC 2606, never deliverable), a
 * made-up display name and a random throwaway password. Every run creates a new account, so it
 * never depends on, or collides with, data from earlier runs.
 */

// The browser's time zone (playwright.config.ts). Sign-up pre-fills it, so it becomes the user's
// time zone and Today must show the calendar day *there*, not the UTC day.
const USER_TIME_ZONE = "Pacific/Auckland";

/** `YYYY-MM-DD` of instant `at` in `timeZone`. */
function isoDayIn(timeZone: string, at: Date): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(at);
}

/** English weekday name of a `YYYY-MM-DD` calendar day. */
function weekdayOf(isoDay: string): string {
  return new Intl.DateTimeFormat("en", { timeZone: "UTC", weekday: "long" }).format(new Date(`${isoDay}T12:00:00Z`));
}

/** English long date of a `YYYY-MM-DD` calendar day, e.g. "October 23, 2026". */
function longDateOf(isoDay: string): string {
  return new Intl.DateTimeFormat("en", { timeZone: "UTC", day: "numeric", month: "long", year: "numeric" }).format(
    new Date(`${isoDay}T12:00:00Z`),
  );
}

/**
 * Asserts the Today page for `displayName`: greeting, today's date in the user's time zone and
 * the signed-in header. "Today" may legitimately be either of two days if the test straddles
 * midnight in that zone, so both candidates are accepted; no clock is faked.
 */
async function expectToday(page: Page, displayName: string, startedAt: Date) {
  await expect(page).toHaveURL(/\/today$/);
  await expect(page.getByText(`Hi, ${displayName}`, { exact: true })).toBeVisible();

  const candidates = [isoDayIn(USER_TIME_ZONE, startedAt), isoDayIn(USER_TIME_ZONE, new Date())];
  const day = page.getByRole("heading", { level: 1 }).locator("time");
  await expect(day).toHaveAttribute("datetime", new RegExp(`^(${candidates.join("|")})$`));
  const shown = (await day.getAttribute("datetime")) as string;
  await expect(day).toContainText(weekdayOf(shown));
  await expect(day).toContainText(longDateOf(shown));

  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

test("smoke: sign up a new athlete, see Today, sign out, sign in again", async ({ page }) => {
  const startedAt = new Date();
  const run = `${startedAt.getTime()}-${randomBytes(3).toString("hex")}`;
  const email = `smoke+${run}@example.test`;
  const password = `smoke-${randomBytes(12).toString("hex")}`; // throwaway, >= 10 characters
  const displayName = `Smoke Athlete ${run.slice(-6)}`;

  await test.step("sign up as an athlete and accept the disclaimer", async () => {
    await page.goto("/sign-up");
    await expect(page.getByRole("heading", { level: 1, name: "Create your account" })).toBeVisible();

    await page.getByLabel("Email", { exact: true }).fill(email);
    await page.getByLabel("Password", { exact: true }).fill(password);
    await page.getByLabel("Display name", { exact: true }).fill(displayName);
    // The radios are visually hidden inside segmented-control labels: click the label, as a user would.
    await page.getByText("Athlete", { exact: true }).click();
    await expect(page.getByRole("radio", { name: /^Athlete/ })).toBeChecked();
    await page.getByLabel("Date of birth", { exact: true }).fill("1990-01-01");
    await expect(page.getByRole("radio", { name: /^Metric/ })).toBeChecked();
    await expect(page.getByLabel("Time zone", { exact: true })).toHaveValue(USER_TIME_ZONE);

    // The same text is also in the page footer; check the one inside the form the user must accept.
    await expect(page.getByRole("form", { name: "Create your account" }).getByText(/not medical advice/)).toBeVisible();
    const disclaimer = page.getByRole("checkbox", { name: "I've read this and accept it" });
    await disclaimer.check();
    await expect(disclaimer).toBeChecked();

    await page.getByRole("button", { name: "Create account" }).click();
  });

  await test.step("completes the onboarding wizard and reads the targets before leaving", async () => {
    await expect(page).toHaveURL(/\/onboarding$/);
    // Radios and checkboxes are visually hidden inside labels: click the label, as a user would.
    const choose = (label: RegExp) => page.locator("label").filter({ hasText: label }).first().click();
    const next = () => page.getByRole("button", { name: "Next", exact: true }).click();

    await expect(page.getByRole("heading", { level: 1, name: "Your body" })).toBeVisible();
    await choose(/^Female/);
    await page.getByLabel(/^Height/).fill("170");
    await page.getByLabel(/^Weight/).fill("65");
    await next();
    await choose(/^Skip/);
    await next();
    await choose(/^Lightly active/);
    await next();
    await choose(/^Maintenance/);
    await next();
    await choose(/^Beginner/);
    await choose(/^3 days/);
    for (const day of ["Mon", "Wed", "Fri"]) await choose(new RegExp(`^${day}$`));
    await choose(/^60 min/);
    await choose(/^Full gym/);
    await next();
    await choose(/^Omnivore/);
    await choose(/^3 meals/);
    await next();
    await expect(page.getByRole("heading", { level: 1, name: "Check your answers" })).toBeVisible();
    await page.getByRole("button", { name: "Create my plan" }).click();

    await expect(page.getByRole("heading", { level: 1, name: "Your plan is ready" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "How we calculated this" })).toBeVisible();
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
