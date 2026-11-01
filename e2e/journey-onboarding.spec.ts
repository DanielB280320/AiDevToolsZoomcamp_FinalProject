import { randomBytes } from "node:crypto";

import { expect, test } from "@playwright/test";

import { completeWizardInUi, expectToday, signUpInUi } from "./helpers";

/**
 * Journey 1 (#52, spec §10): a new athlete signs up and completes the onboarding wizard in the UI,
 * then lands on Today with a planned session or a rest day for today (in the user's time zone) and
 * the calorie target in force. Reloading Today keeps the user signed in.
 *
 * Tagged `@smoke`: it runs after every deploy against dev and prod, so it only uses fake data (a
 * unique `.test` address, a made-up name, a random throwaway password). The sign-up and wizard
 * steps are the same helpers as `smoke.spec.ts`; this journey adds the checks on the plan.
 */
test("journey 1: sign up, onboard, land on Today with today's plan and calorie target", { tag: "@smoke" }, async ({ page }) => {
  const startedAt = new Date();
  const tag = `${startedAt.getTime()}-${randomBytes(3).toString("hex")}`;
  const who = {
    email: `journey1+${tag}@example.test`,
    password: `journey-${randomBytes(12).toString("hex")}`, // throwaway, >= 10 characters
    displayName: `Journey Athlete ${tag.slice(-6)}`,
  };
  let calorieTarget = 0;

  await test.step("sign up in the UI", async () => {
    await signUpInUi(page, who);
  });

  await test.step("complete the onboarding wizard and read the calorie target", async () => {
    calorieTarget = await completeWizardInUi(page);
    expect(calorieTarget, "a plausible daily calorie target").toBeGreaterThan(1000);
    await page.getByRole("link", { name: "Go to Today" }).click();
  });

  await test.step("Today shows today's plan and the targets", async () => {
    await expectToday(page, who.displayName, startedAt);
    const training = page.getByRole("region", { name: "Training" });
    // A planned session (with its Start workout link) or a rest day, depending on the weekday.
    await expect(training.getByText("Rest day").or(training.getByRole("link", { name: "Start workout" }))).toBeVisible();
    // Planned meals carry kcal; the macro bars only render with a calorie target above zero.
    await expect(page.getByRole("region", { name: "Meals" }).getByText(/\d+ kcal \(estimated\)/).first()).toBeVisible();
    const energy = page.getByRole("region", { name: "Estimated energy today" });
    await expect(energy.getByRole("group", { name: "Macros eaten against target" })).toBeVisible();
    await expect(energy.getByText(/^0 of [1-9]\d* g$/).first()).toBeVisible();
  });

  await test.step("reloading Today keeps the user signed in", async () => {
    await page.reload();
    await expectToday(page, who.displayName, startedAt);
  });
});
