import { expect, test } from "@playwright/test";

import { onboard, run, signIn, signUp } from "./helpers";

/**
 * #223 (F10.6-F10.10, D95): the workout screen at 360 px. Every set is one non-wrapping row with
 * a check and an edit button, the page does not scroll sideways, logging a set as planned is two
 * taps from Today, and "Complete all as planned" marks the rest after one confirmation without
 * finishing the workout. Not part of the post-deploy smoke subset.
 */
test.use({ viewport: { width: 360, height: 740 } });

test("workout rows at 360 px: check, complete all as planned", async ({ page }) => {
  const tag = run();
  const athlete = await signUp(page.context().request, "athlete", `Rows ${tag.slice(-6)}`, tag);
  await onboard(page.context().request, { trainToday: true });
  await signIn(page, athlete);
  await expect(page).toHaveURL(/\/today$/);

  await test.step("tap 1: open the workout from Today", async () => {
    await page.getByRole("link", { name: /start workout|continue workout/i }).click();
    await expect(page).toHaveURL(/\/workout\//);
  });

  const checks = page.getByRole("button", { name: /^Done as planned, /, pressed: false });
  await expect(checks.first()).toBeVisible();
  const total = await checks.count();
  expect(total).toBeGreaterThan(2);

  await test.step("every set is one row and the page does not scroll sideways", async () => {
    const rows = page.getByRole("listitem").filter({ has: page.getByRole("button", { name: /^Edit / }) });
    expect(await rows.count()).toBe(total);
    for (let i = 0; i < total; i++) {
      const row = rows.nth(i);
      // 48 px controls + 8 px padding top and bottom: a second line would add at least 20 px.
      const box = await row.boundingBox();
      expect(box!.height, "a row is one line").toBeLessThanOrEqual(68);
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  await test.step("tap 2: the check logs set 1 as planned, shows it pressed and starts the rest timer", async () => {
    await checks.first().click();
    await expect(page.getByRole("button", { name: /^Done as planned, /, pressed: true })).toHaveCount(1);
    await expect(page.getByRole("timer")).toBeVisible();
    await page.getByRole("button", { name: "Skip rest" }).click();
  });

  await test.step("complete all as planned: one confirmation, no rest timer, workout stays open", async () => {
    await page.getByRole("button", { name: "Complete all as planned" }).click();
    await page.getByRole("button", { name: "Yes, complete them" }).click();
    await expect(page.getByRole("button", { name: /^Done as planned, /, pressed: true })).toHaveCount(total);
    await expect(page.getByRole("button", { name: "Complete all as planned" })).toHaveCount(0);
    await expect(page.getByRole("timer")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Finish workout" })).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });

  await test.step("Finish workout is its own tap", async () => {
    await page.getByRole("button", { name: "Finish workout" }).click();
    await expect(page.getByRole("heading", { level: 2, name: "Workout finished" })).toBeVisible();
    await expect(page.getByText("100%").first()).toBeVisible();
  });
});
