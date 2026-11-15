import { expect, test } from "@playwright/test";

import { onboard, plannedOrEntered, run, signIn, signUp } from "./helpers";

/**
 * F15.6-F15.10, D109: the Progress page follows one period selector. An athlete finishes today's
 * session through the API, opens Progress (30 days by default) and sees one active day; stepping to
 * the previous period changes the KPIs (no active day), the URL keeps the range and survives a
 * reload; a preset brings today's session back. Checked at 360 px: no horizontal scroll. Not part
 * of the post-deploy smoke subset.
 */
test.use({ viewport: { width: 360, height: 740 } });

test("progress: changing the period changes the KPIs; the range survives a reload", async ({ page }) => {
  const tag = run();
  const athlete = await signUp(page.context().request, "athlete", `Period ${tag.slice(-6)}`, tag);
  const api = page.context().request;
  await onboard(api, { trainToday: true });

  const dayResponse = await api.get("/api/v1/athletes/me/days/today");
  expect(dayResponse.status()).toBe(200);
  const session = (await dayResponse.json()).session;
  expect(session, "the plan trains today").not.toBeNull();
  for (const exercise of session.exercises as { planned_exercise_id: string; exercise: { id: string; type: string }; sets: { set_no: number; target_reps: number | null; target_weight_kg: number | null }[] }[]) {
    for (const set of exercise.sets) {
      const logged = await api.post(`/api/v1/sessions/${session.id}/sets`, {
        data: { exercise_id: exercise.exercise.id, planned_exercise_id: exercise.planned_exercise_id, set_no: set.set_no, ...plannedOrEntered(exercise.exercise.type, set) },
      });
      expect(logged.status(), await logged.text()).toBe(201);
    }
  }
  const finished = await api.post(`/api/v1/sessions/${session.id}/finish`);
  expect(finished.status(), await finished.text()).toBe(200);

  await signIn(page, athlete);
  await expect(page).toHaveURL(/\/today$/);
  await page.goto("/progress");

  const activeDays = page.getByTestId("kpi-active-days-value");
  await test.step("30 days by default: today's finished session counts", async () => {
    await expect(page.getByLabel("30 days")).toBeChecked();
    await expect(page.getByTestId("progress-description")).toBeVisible();
    await expect(activeDays).toHaveText("1");
    await expect(page.getByTestId("ring-sessions")).toContainText(" planned");
    await expect(page.getByRole("img", { name: /Training volume in kg and sessions done per day/ })).toBeVisible();
  });

  await test.step("the previous period has no finished session: the KPIs change", async () => {
    const before = await page.getByTestId("period-range").innerText();
    await page.getByRole("button", { name: "Previous period" }).click();
    await expect(page.getByTestId("period-range")).not.toHaveText(before);
    await expect(page.getByLabel("Custom")).toBeChecked();
    await expect(activeDays).toHaveText("0");
    await expect(page.getByTestId("ring-sessions")).toContainText("No data in this period.");
    await expect(page).toHaveURL(/[?&]from=\d{4}-\d{2}-\d{2}&to=\d{4}-\d{2}-\d{2}/);
  });

  await test.step("a reload keeps the selected range", async () => {
    const range = await page.getByTestId("period-range").innerText();
    await page.reload();
    await expect(page.getByTestId("period-range")).toHaveText(range);
    await expect(activeDays).toHaveText("0");
  });

  await test.step("next brings the 30 days ending today back, with the session", async () => {
    await page.getByRole("button", { name: "Next period" }).click();
    await expect(page.getByLabel("30 days")).toBeChecked();
    await expect(activeDays).toHaveText("1");
    await expect(page.getByRole("button", { name: "Next period" })).toBeDisabled();
  });

  await test.step("360 px: no horizontal scroll", async () => {
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
