import { expect, test } from "@playwright/test";

import { addDays, onboard, run, signIn, signUp, todayIso } from "./helpers";

/**
 * Journey 2 (#52, spec §10): an onboarded athlete opens today's workout, logs every set of one
 * exercise above its rep target, finishes the session, sees 100 % on Today, reads the progression
 * suggestion with its reason (F11.4), accepts it and finds the accepted value as the exercise's
 * next target on the Plan page.
 *
 * Setup through the API (onboarding with a training day today, the other exercises logged as
 * planned so the session can reach 100 %); everything the journey is about goes through the UI.
 * Not part of the post-deploy smoke subset.
 */

interface SessionExercise {
  planned_exercise_id: string;
  exercise: { id: string; name: string; type: string };
  sets: { set_no: number; target_reps: number | null; target_weight_kg?: number | null }[];
}

test("journey 2: log a workout above target, finish, accept the suggestion, see the new target", async ({ page }) => {
  const tag = run();
  const athlete = await signUp(page.context().request, "athlete", `Trainee ${tag.slice(-6)}`, tag);
  const api = page.context().request;
  await onboard(api, { trainToday: true });

  const dayResponse = await api.get("/api/v1/athletes/me/days/today");
  expect(dayResponse.status()).toBe(200);
  const session = (await dayResponse.json()).session;
  expect(session, "the plan trains today").not.toBeNull();
  const exercises = session.exercises as SessionExercise[];
  // The exercise logged in the UI: the first strength exercise (week-1 targets have no weight, so
  // the engine calibrates the starting weight from what the athlete lifted).
  const subject = exercises.find((e) => e.exercise.type === "strength");
  expect(subject, "the session has a strength exercise").toBeDefined();
  const repsTarget = subject!.sets[0].target_reps as number;

  // Every other exercise is logged as planned through the API, so finishing gives 100 %.
  for (const other of exercises.filter((e) => e !== subject)) {
    for (const set of other.sets) {
      const response = await api.post(`/api/v1/sessions/${session.id}/sets`, {
        data: { exercise_id: other.exercise.id, planned_exercise_id: other.planned_exercise_id, set_no: set.set_no, as_planned: true },
      });
      expect(response.status(), await response.text()).toBe(201);
    }
  }

  await signIn(page, athlete);
  await expect(page).toHaveURL(/\/today$/);

  await test.step("open today's workout", async () => {
    await page.getByRole("link", { name: /start workout|continue workout/i }).click();
    await expect(page).toHaveURL(/\/workout\//);
    await expect(page.getByRole("heading", { level: 2, name: subject!.exercise.name })).toBeVisible();
  });

  const aboveTarget = repsTarget + 2;
  await test.step("log every set of one exercise above its rep target", async () => {
    const card = page.getByRole("region", { name: subject!.exercise.name });
    for (const set of subject!.sets) {
      await card.getByRole("button", { name: new RegExp(`^Edit .*, set ${set.set_no}$`) }).click();
      await card.getByLabel("Reps", { exact: true }).fill(String(aboveTarget));
      await card.getByLabel(/^Weight/).fill("20");
      await card.getByRole("button", { name: "Save set", exact: true }).click();
      await expect(card.getByText(`Logged: ${aboveTarget} reps · 20 kg`)).toHaveCount(set.set_no);
    }
  });

  await test.step("finish the session and read the summary", async () => {
    await page.getByRole("button", { name: "Finish workout" }).click();
    await expect(page.getByRole("heading", { level: 2, name: "Workout finished" })).toBeVisible();
    await expect(page.getByText("100%").first()).toBeVisible();
    await page.getByRole("link", { name: "Back to Today" }).click();
  });

  await test.step("Today shows 100 % and a pending suggestion with its reason", async () => {
    await expect(page).toHaveURL(/\/today$/);
    await expect(page.getByRole("region", { name: "Training" }).locator("[data-status=done]")).toBeVisible();
    const card = page.getByTestId("suggestion").filter({ hasText: subject!.exercise.name });
    await expect(card).toHaveCount(1);
    await expect(card.getByLabel("Old targets to new targets")).toContainText("→");
    // F11.4: the stored reason is shown next to the proposal.
    const pending = await api.get(`/api/v1/athletes/${athlete.id}/suggestions?status=pending`);
    const reason = ((await pending.json()).items as { reason: string; payload: { exercise?: { name: string } } }[]).find(
      (s) => s.payload.exercise?.name === subject!.exercise.name,
    )?.reason;
    expect(reason, "the engine explains the suggestion").toBeTruthy();
    await expect(card.getByText(reason!, { exact: true })).toBeVisible();
  });

  await test.step("accept it: no longer pending, shown as accepted", async () => {
    const card = page.getByTestId("suggestion").filter({ hasText: subject!.exercise.name });
    const proposal = (await card.getByLabel("Old targets to new targets").textContent()) ?? "";
    await card.getByRole("button", { name: "Accept", exact: true }).click();
    await expect(page.getByTestId("suggestion").filter({ hasText: subject!.exercise.name })).toHaveCount(0);
    const decided = page.getByTestId("decided-suggestion").filter({ hasText: subject!.exercise.name });
    await expect(decided).toHaveCount(1);
    await expect(decided).toContainText("Accepted");
    expect(proposal, "calibration proposes the lifted weight").toContain("20 kg");
  });

  await test.step("the Plan shows the accepted value as the exercise's next target", async () => {
    await page.getByRole("link", { name: "Plan", exact: true }).click();
    await expect(page).toHaveURL(/\/plan$/);
    const day = page.getByRole("listitem").filter({ has: page.getByRole("heading", { level: 3, name: new RegExp(`: ${session.training_day_name}$`) }) }).first();
    const exercise = day.getByRole("listitem").filter({ has: page.getByRole("heading", { level: 4, name: subject!.exercise.name, exact: true }) });
    // Calibration: the weight lifted (20 kg) is now the target weight; it was empty before.
    await expect(exercise.getByLabel(/^Weight/)).toHaveValue("20");
  });

  await test.step("next week's session carries the new target", async () => {
    const next = await api.get(`/api/v1/athletes/me/days/${addDays(todayIso(), 7)}`);
    expect(next.status()).toBe(200);
    const nextSession = (await next.json()).session;
    expect(nextSession, "the plan trains again next week").not.toBeNull();
    const again = (nextSession.exercises as SessionExercise[]).find((e) => e.exercise.id === subject!.exercise.id);
    expect(again?.sets[0].target_weight_kg).toBe(20);
  });
});
