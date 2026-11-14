import { expect, test } from "@playwright/test";

import { giveFirstStrengthExerciseAWeight, onboard, run, signIn, signUp } from "./helpers";

/**
 * #223 (F10.6-F10.10, D95, D96): the workout screen at 360 px. Every exercise starts collapsed;
 * its sets are cards next to each other that wrap instead of scrolling sideways, with 44 px
 * buttons; a strength set without a weight (week-1 plans) says "Weight not defined" and its check
 * opens the editor instead of logging; logging a set is three taps from Today; "Complete all as
 * planned" marks the sets that have everything it needs without finishing the workout. Not part of
 * the post-deploy smoke subset.
 */
test.use({ viewport: { width: 360, height: 740 } });

const noSideways = () => document.documentElement.scrollWidth - document.documentElement.clientWidth;

test("workout cards at 360 px: collapsed start, wrapping cards, check, complete all as planned", async ({ page }) => {
  const tag = run();
  const athlete = await signUp(page.context().request, "athlete", `Cards ${tag.slice(-6)}`, tag);
  await onboard(page.context().request, { trainToday: true });
  // The first strength exercise of each day gets a weight; the others stay week-1 weightless.
  await giveFirstStrengthExerciseAWeight(page.context().request);
  await signIn(page, athlete);
  await expect(page).toHaveURL(/\/today$/);

  await test.step("tap 1: open the workout from Today; every exercise is collapsed", async () => {
    await page.getByRole("link", { name: /start workout|continue workout/i }).click();
    await expect(page).toHaveURL(/\/workout\//);
    const headers = page.getByRole("button", { name: /sets logged/ });
    await expect(headers.first()).toBeVisible();
    const count = await headers.count();
    for (let i = 0; i < count; i++) await expect(headers.nth(i)).toHaveAttribute("aria-expanded", "false");
    // The panels are hidden, not removed: no card is visible.
    await expect(page.getByTestId("set-card").first()).toBeHidden();
    for (const card of await page.getByTestId("set-card").all()) await expect(card).toBeHidden();
  });

  const firstStrength = page.getByRole("region").filter({ has: page.getByText("Weight not defined") });

  await test.step("tap 2: open the first exercise; its sets are cards next to each other", async () => {
    await page.getByRole("button", { name: /sets logged/ }).first().click();
    const cards = page.getByTestId("set-card");
    await expect(cards.first()).toBeVisible();
    expect(await cards.count()).toBeGreaterThan(1);
    const a = (await cards.nth(0).boundingBox())!;
    const b = (await cards.nth(1).boundingBox())!;
    expect(Math.abs(a.y - b.y), "the first two sets share a line").toBeLessThan(2);
    expect(b.x).toBeGreaterThan(a.x);
    expect(await page.evaluate(noSideways)).toBeLessThanOrEqual(0);
    for (const button of await cards.first().getByRole("button").all()) {
      const box = (await button.boundingBox())!;
      expect(box.width).toBeGreaterThanOrEqual(44);
      expect(box.height).toBeGreaterThanOrEqual(44);
    }
  });

  await test.step("open everything: cards wrap, no sideways scroll, weightless strength sets say so", async () => {
    const headers = page.getByRole("button", { name: /sets logged/, expanded: false });
    while ((await headers.count()) > 0) await headers.first().click();
    await expect(page.getByText("Weight not defined").first()).toBeVisible();
    expect(await page.evaluate(noSideways)).toBeLessThanOrEqual(0);
    const cards = page.getByTestId("set-card");
    const n = await cards.count();
    for (let i = 0; i < n; i++) {
      const box = (await cards.nth(i).boundingBox())!;
      expect(box.x + box.width, "a card stays inside the 360 px screen").toBeLessThanOrEqual(360);
    }
  });

  await test.step("tap 3: the check on a set without a weight opens the editor; entering values logs it", async () => {
    const card = firstStrength.first();
    await card.getByRole("button", { name: /^Done as planned, /, pressed: false }).first().click();
    await expect(card.getByRole("button", { name: "Save set", exact: true })).toBeVisible();
    await card.getByLabel(/^Weight/).fill("20");
    await card.getByRole("button", { name: "Save set", exact: true }).click();
    await expect(page.getByRole("timer")).toBeVisible();
    await page.getByRole("button", { name: "Skip rest" }).click();
    await expect(page.getByTestId("set-card").filter({ hasText: "20 kg" })).toHaveCount(1);
  });

  await test.step("complete all as planned logs the sets that have a weight and leaves weightless strength sets", async () => {
    const cards = page.getByTestId("set-card");
    const total = await cards.count();
    const weightless = await cards.filter({ hasText: "Weight not defined" }).count();
    expect(weightless, "week-1 strength sets without a weight remain").toBeGreaterThan(0);
    expect(total - weightless, "there are sets it can log").toBeGreaterThan(1);

    const complete = page.getByRole("button", { name: "Complete all as planned" });
    await expect(complete).toBeVisible();
    await complete.click();
    await page.getByRole("button", { name: "Yes, complete them" }).click();
    await expect(complete).toHaveCount(0);
    await expect(page.getByRole("timer")).toHaveCount(0);

    // Pressed: every set except the weightless ones and the one entered by hand (not "as planned").
    const pressed = page.getByRole("button", { name: /^Done as planned, /, pressed: true });
    await expect(pressed).toHaveCount(total - weightless - 1);
    // The weightless strength sets are still unlogged.
    await expect(cards.filter({ hasText: "Weight not defined" })).toHaveCount(weightless);
    await expect(
      cards.filter({ hasText: "Weight not defined" }).getByRole("button", { name: /^Done as planned, /, pressed: false }),
    ).toHaveCount(weightless);
    await expect(page.getByRole("button", { name: "Finish workout" })).toBeVisible();
    expect(await page.evaluate(noSideways)).toBeLessThanOrEqual(0);
  });

  await test.step("Finish workout is its own tap", async () => {
    await page.getByRole("button", { name: "Finish workout" }).click();
    await expect(page.getByRole("heading", { level: 2, name: "Workout finished" })).toBeVisible();
  });
});
