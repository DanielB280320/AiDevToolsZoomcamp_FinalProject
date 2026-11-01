import { expect, test } from "@playwright/test";

import { newContext, onboard, run, signIn, signUp } from "./helpers";

/**
 * Journey 4 (#52, spec §10, F16, F15): an athlete requests a coach by the coach's email, the coach
 * approves in the UI, opens the athlete's Progress page and the session chart (with data), and
 * leaves a note on the session; the athlete then gets the `coach_note` notification and reads the
 * note. Not part of the post-deploy smoke subset.
 *
 * Setup through the API: both accounts, the athlete's onboarding and one finished session. The
 * link, the approval, the chart and the note go through the UI.
 */
test("journey 4: link request, coach approves, reads the session chart, leaves a note; athlete reads it", async ({
  page,
  browser,
  baseURL,
}) => {
  const tag = run();
  const coachContext = await newContext(browser, baseURL);
  const coachPage = await coachContext.newPage();
  try {
    const athlete = await signUp(page.context().request, "athlete", `Lifter ${tag.slice(-6)}`, `a-${tag}`);
    const coach = await signUp(coachContext.request, "coach", `Coach ${tag.slice(-6)}`, `c-${tag}`);
    const api = page.context().request;
    await onboard(api, { trainToday: true });

    // One finished session today: every planned set logged as planned.
    const dayResponse = await api.get("/api/v1/athletes/me/days/today");
    expect(dayResponse.status()).toBe(200);
    const session = (await dayResponse.json()).session;
    expect(session, "the plan trains today").not.toBeNull();
    for (const exercise of session.exercises as { planned_exercise_id: string; exercise: { id: string }; sets: { set_no: number }[] }[]) {
      for (const set of exercise.sets) {
        const logged = await api.post(`/api/v1/sessions/${session.id}/sets`, {
          data: { exercise_id: exercise.exercise.id, planned_exercise_id: exercise.planned_exercise_id, set_no: set.set_no, as_planned: true },
        });
        expect(logged.status(), await logged.text()).toBe(201);
      }
    }
    const finished = await api.post(`/api/v1/sessions/${session.id}/finish`);
    expect(finished.status(), await finished.text()).toBe(200);

    await test.step("the athlete requests the coach by email", async () => {
      await signIn(page, athlete);
      await expect(page).toHaveURL(/\/today$/);
      await page.goto("/coach");
      await page.getByLabel("Coach name or exact email").fill(coach.email);
      await page.getByRole("button", { name: "Search" }).click();
      await page.getByRole("button", { name: `Request ${coach.name}` }).click();
      await expect(page.getByRole("heading", { level: 2, name: "Request sent" })).toBeVisible();
      await expect(page.getByText(`Waiting for ${coach.name} to answer.`)).toBeVisible();
    });

    await test.step("the coach approves the request", async () => {
      await signIn(coachPage, coach);
      await expect(coachPage).toHaveURL(/\/coach\/clients$/);
      await coachPage.goto("/coach");
      await expect(coachPage.getByText(`${athlete.name} wants you as their coach.`)).toBeVisible();
      await coachPage.getByRole("button", { name: "Approve" }).click();
      await expect(coachPage.getByRole("region", { name: "Your athletes" }).getByText(athlete.name)).toBeVisible();
    });

    await test.step("the coach opens the athlete's Progress page", async () => {
      await coachPage.goto("/coach/clients");
      await coachPage.getByRole("link", { name: athlete.name }).click();
      await expect(coachPage).toHaveURL(new RegExp(`/coach/clients/${athlete.id}$`));
      await coachPage.getByRole("link", { name: "Progress", exact: true }).click();
      await expect(coachPage.getByRole("heading", { level: 2, name: /adherence/i })).toBeVisible();
    });

    const note = `Solid session, add 2.5 kg next week (${tag.slice(-6)})`;
    await test.step("the coach opens the session chart (data, not the empty state) and leaves a note", async () => {
      await coachPage.getByRole("link", { name: "Today", exact: true }).click();
      await coachPage.getByRole("link", { name: "Session detail" }).click();
      await expect(coachPage).toHaveURL(new RegExp(`/coach/clients/${athlete.id}/progress/session/${session.id}$`));
      await expect(coachPage.getByTestId("session-exercise").first()).toBeVisible();
      await expect(coachPage.getByTestId("set-row").first()).toBeVisible();
      await expect(coachPage.getByText("No sets were logged in this session.")).toHaveCount(0);

      await coachPage.getByLabel("Add a note: this workout").fill(note);
      await coachPage.getByRole("button", { name: "Save note" }).first().click();
      await expect(coachPage.getByTestId("coach-note").filter({ hasText: note })).toBeVisible();
    });

    await test.step("the athlete sees the coach_note notification and the note", async () => {
      await page.goto("/notifications");
      await expect(page.getByText("1 unread")).toBeVisible();
      await page.getByRole("button", { name: /Your coach left you a note\./ }).click();
      await expect(page).toHaveURL(/\/today\?date=\d{4}-\d{2}-\d{2}$/);
      const shown = page.getByTestId("coach-note").filter({ hasText: note });
      await expect(shown).toBeVisible();
      await expect(shown).toContainText(`Coach ${coach.name}`);
    });
  } finally {
    await coachContext.close();
  }
});
