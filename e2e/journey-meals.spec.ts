import { expect, type Page, test } from "@playwright/test";

import { onboard, run, signIn, signUp } from "./helpers";

/**
 * Journey 3 (#52, spec §10, F12): an onboarded athlete checks off a planned meal on Today and the
 * estimated energy balance moves from its initial value by exactly that meal's kcal; undoing the
 * check-off restores the previous values. Concrete numbers are asserted, not just DOM changes.
 * Not part of the post-deploy smoke subset.
 */

/** The number in the Estimated-energy tile with this label ("Eaten (kcal)", "Balance (kcal)"). */
async function tile(page: Page, label: string): Promise<number> {
  const value = page.getByText(label, { exact: true }).locator("xpath=following-sibling::dd");
  return Number(((await value.textContent()) ?? "").trim());
}

test("journey 3: check off a planned meal, the energy balance moves by its kcal, undo restores it", async ({ page }) => {
  const tag = run();
  const athlete = await signUp(page.context().request, "athlete", `Eater ${tag.slice(-6)}`, tag);
  await onboard(page.context().request);
  await signIn(page, athlete);
  await expect(page).toHaveURL(/\/today$/);

  const meals = page.getByRole("region", { name: "Meals" });
  const first = meals.getByRole("listitem").first();
  // The planned meal's kcal as the athlete reads it on the row ("512 kcal (estimated)").
  await expect(first.getByText(/^\d+ kcal \(estimated\)$/)).toBeVisible();
  const plannedKcal = Number(((await first.getByText(/^\d+ kcal \(estimated\)$/).textContent()) ?? "").match(/\d+/)![0]);
  expect(plannedKcal).toBeGreaterThan(0);

  const initialEaten = await tile(page, "Eaten (kcal)");
  const initialBalance = await tile(page, "Balance (kcal)");
  expect(initialEaten, "nothing eaten yet").toBe(0);

  await test.step("check off the meal as planned", async () => {
    await first.getByRole("button", { name: /^Eaten as planned: / }).click();
    await expect(first.getByText("Eaten as planned", { exact: true })).toBeVisible();
    await expect(first.getByText(`${plannedKcal} kcal eaten (estimated)`)).toBeVisible();
    // Eaten goes from 0 to the meal's kcal; the balance rises by the same amount.
    await expect(page.getByText("Eaten (kcal)", { exact: true }).locator("xpath=following-sibling::dd")).toHaveText(String(plannedKcal));
    await expect.poll(() => tile(page, "Balance (kcal)")).toBe(initialBalance + plannedKcal);
  });

  await test.step("undo restores the previous values", async () => {
    await first.getByRole("button", { name: /^Undo: / }).click();
    await expect(first.getByText(`${plannedKcal} kcal (estimated)`)).toBeVisible();
    await expect(page.getByText("Eaten (kcal)", { exact: true }).locator("xpath=following-sibling::dd")).toHaveText("0");
    await expect.poll(() => tile(page, "Balance (kcal)")).toBe(initialBalance);
  });
});
