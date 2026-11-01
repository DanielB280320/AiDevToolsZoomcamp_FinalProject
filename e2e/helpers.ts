import { randomBytes } from "node:crypto";

import { type APIRequestContext, type Browser, expect, type Page } from "@playwright/test";

/**
 * Shared helpers of the journey specs (#52). Accounts are created through the API with fake data
 * on the reserved `.test` domain and throwaway passwords; the journey under test goes through the
 * UI. Nothing here logs addresses, names or passwords.
 */

/** The user's time zone in every spec (playwright.config.ts). */
export const TIME_ZONE = "Pacific/Auckland";

export interface Person {
  id: string;
  email: string;
  password: string;
  name: string;
}

/** Unique per call, so repeated runs never collide with old accounts. */
export const run = () => `${Date.now()}-${randomBytes(3).toString("hex")}`;

export async function signUp(request: APIRequestContext, role: "athlete" | "coach", name: string, tag: string): Promise<Person> {
  const email = `e2e-${role}+${tag}@example.test`;
  const password = `e2e-${randomBytes(12).toString("hex")}`;
  const response = await request.post("/api/v1/auth/signup", {
    data: {
      email,
      password,
      display_name: name,
      role,
      birth_date: "1990-01-01",
      units: "metric",
      timezone: TIME_ZONE,
      accept_disclaimer: true,
    },
  });
  expect(response.status(), await response.text()).toBe(201);
  return { id: (await response.json()).id as string, email, password, name };
}

const WEEKDAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"] as const;

/** `YYYY-MM-DD` of the current day in the user's time zone. */
export function todayIso(at = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TIME_ZONE, year: "numeric", month: "2-digit", day: "2-digit" }).format(at);
}

/** `YYYY-MM-DD` plus `days` calendar days. */
export function addDays(isoDay: string, days: number): string {
  const [y, m, d] = isoDay.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d + days)).toISOString().slice(0, 10);
}

/** Today's weekday in the user's time zone plus `offset` days. */
function weekdayFromToday(offset: number): (typeof WEEKDAYS)[number] {
  const [y, m, d] = todayIso().split("-").map(Number);
  return WEEKDAYS[new Date(Date.UTC(y, m - 1, d + offset)).getUTCDay()];
}

/**
 * Completes onboarding through the API. By default the plan trains Mon / Wed / Fri; with
 * `trainToday` the three training days start on today's weekday (in the user's time zone), so
 * today has a session whatever day the test runs.
 */
export async function onboard(request: APIRequestContext, options: { trainToday?: boolean } = {}) {
  const preferred_days = options.trainToday ? [0, 2, 4].map(weekdayFromToday) : ["mon", "wed", "fri"];
  const response = await request.post("/api/v1/athletes/me/onboarding", {
    data: {
      profile: {
        sex: "female",
        height_cm: 165,
        lifestyle: "lightly_active",
        goal: "maintenance",
        experience: "beginner",
        days_per_week: 3,
        preferred_days,
        session_minutes: 60,
        equipment: "full_gym",
        avoided_exercise_ids: [],
        diet: "omnivore",
        allergies: [],
        meals_per_day: 3,
      },
      body_metric: { weight_kg: 65, body_fat_method: "skip" },
    },
  });
  expect(response.status(), await response.text()).toBe(201);
}

export async function link(athlete: APIRequestContext, coach: APIRequestContext, coachId: string) {
  const requested = await athlete.post("/api/v1/coach-links", { data: { coach_id: coachId } });
  expect(requested.status(), await requested.text()).toBe(201);
  const approved = await coach.post(`/api/v1/coach-links/${(await requested.json()).id}/approve`);
  expect(approved.status(), await approved.text()).toBe(200);
}

export async function signIn(page: Page, person: Person) {
  await page.goto("/sign-in");
  await page.getByLabel("Email", { exact: true }).fill(person.email);
  await page.getByLabel("Password", { exact: true }).fill(person.password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}

/** A second, isolated browser session (its own cookies), e.g. for the coach next to the athlete. */
export async function newContext(browser: Browser, baseURL: string | undefined) {
  return browser.newContext({ baseURL, locale: "en-US", timezoneId: TIME_ZONE });
}

// Today page checks shared by the smoke test and journey 1.
const USER_TIME_ZONE = TIME_ZONE; // Sign-up pre-fills the browser's zone; Today must show the day *there*, not the UTC day.

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
export async function expectToday(page: Page, displayName: string, startedAt: Date) {
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

/** Fills the sign-up form in the UI as an athlete, accepts the disclaimer and submits. */
export async function signUpInUi(page: Page, who: { email: string; password: string; displayName: string }) {
  await page.goto("/sign-up");
  await expect(page.getByRole("heading", { level: 1, name: "Create your account" })).toBeVisible();

  await page.getByLabel("Email", { exact: true }).fill(who.email);
  await page.getByLabel("Password", { exact: true }).fill(who.password);
  await page.getByLabel("Display name", { exact: true }).fill(who.displayName);
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
}

/**
 * Walks the onboarding wizard in the UI (same answers as the API helper: beginner, 3 days
 * Mon/Wed/Fri) up to the "Your plan is ready" screen, and returns the daily calorie target shown there.
 */
export async function completeWizardInUi(page: Page): Promise<number> {
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
  const calories = page.locator("section[aria-labelledby=result-targets]").getByText(/^[\d,.]+ kcal$/).first();
  await expect(calories).toBeVisible();
  return Number(((await calories.textContent()) ?? "").replace(/\D/g, ""));
}
