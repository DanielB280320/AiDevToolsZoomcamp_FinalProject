import { type APIRequestContext, type BrowserContext, expect, type Page, test } from "@playwright/test";

import { link, newContext, onboard, run, signIn, signUp } from "./helpers";

/**
 * Coach dashboard journey (#48, spec F16, F16.5, F11, F8.3):
 * a coach signs in, sees the client list, opens a linked athlete, reads Today / Month / Progress,
 * accepts one suggestion and rejects another, edits the plan; the athlete then sees both
 * decisions as made by the coach and "Edited by <coach>" on the plan.
 *
 * Accounts are created through the API (fake data on the reserved `.test` domain, throwaway
 * passwords); everything the coach does goes through the UI. A second test checks the coach
 * context at a 360 px viewport.
 */

/** The `weeksAhead`-th Monday after the next one (the plan trains on Mondays), as `YYYY-MM-DD`. */
function upcomingMonday(weeksAhead = 0): string {
  const day = new Date();
  for (let i = 1; i <= 14; i++) {
    const candidate = new Date(Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate() + i + 1 + 7 * weeksAhead));
    if (candidate.getUTCDay() === 1) return candidate.toISOString().slice(0, 10);
  }
  throw new Error("no Monday in 14 days");
}

/** Logs one set per exercise of a session and finishes it: every performed exercise gets a suggestion. */
async function finishSessionWithSuggestions(request: APIRequestContext) {
  const dayResponse = await request.get(`/api/v1/athletes/me/days/${upcomingMonday()}`);
  expect(dayResponse.status()).toBe(200);
  const session = (await dayResponse.json()).session;
  expect(session, "the plan trains on Mondays").not.toBeNull();
  let setNo = 0;
  for (const exercise of session.exercises as { exercise: { id: string; type: string }; planned_exercise_id: string }[]) {
    setNo += 1;
    const kind = exercise.exercise.type;
    const values = kind === "timed" ? { seconds: 30 } : kind === "strength" ? { reps: 8, weight_kg: 20 } : { reps: 8 };
    const set = await request.post(`/api/v1/sessions/${session.id}/sets`, {
      data: { exercise_id: exercise.exercise.id, planned_exercise_id: exercise.planned_exercise_id, set_no: 1, ...values },
    });
    expect(set.status(), `set ${setNo}: ${await set.text()}`).toBe(201);
  }
  const finish = await request.post(`/api/v1/sessions/${session.id}/finish`);
  expect(finish.status(), await finish.text()).toBe(200);
  expect((await finish.json()).suggestions.length).toBeGreaterThanOrEqual(2);
}

/**
 * Makes a deload suggestion pending (F11, so the coach list flags the athlete: "needs attention").
 * Session 1 calibrates the first strength exercise (accepted); sessions 2 to 4 log one rep per set
 * at that weight, three failures in a row, so the fourth finish proposes a deload.
 */
async function makeDeloadPending(request: APIRequestContext) {
  let weight = 20;
  for (let week = 0; week < 4; week++) {
    const dayResponse = await request.get(`/api/v1/athletes/me/days/${upcomingMonday(week)}`);
    expect(dayResponse.status()).toBe(200);
    const session = (await dayResponse.json()).session;
    const exercise = (session.exercises as { exercise: { id: string; type: string }; planned_exercise_id: string; rule: string; sets: unknown[] }[]).find(
      (e) => e.exercise.type === "strength" && e.rule !== "manual",
    );
    expect(exercise, "the Monday session has a strength exercise").toBeDefined();
    for (let setNo = 1; setNo <= exercise!.sets.length; setNo++) {
      const set = await request.post(`/api/v1/sessions/${session.id}/sets`, {
        data: { exercise_id: exercise!.exercise.id, planned_exercise_id: exercise!.planned_exercise_id, set_no: setNo, reps: 1, weight_kg: weight },
      });
      expect(set.status(), await set.text()).toBe(201);
    }
    const finish = await request.post(`/api/v1/sessions/${session.id}/finish`);
    expect(finish.status(), await finish.text()).toBe(200);
    const mine = ((await finish.json()).suggestions as { id: string; inputs: { action?: string }; payload: { exercise: { id: string }; proposed: { target_weight_kg: number } } }[]).filter(
      (s) => s.payload.exercise.id === exercise!.exercise.id,
    );
    if (week === 0) {
      const calibrate = mine.find((s) => s.inputs.action === "calibrate");
      expect(calibrate, "the first session calibrates").toBeDefined();
      weight = calibrate!.payload.proposed.target_weight_kg;
      const accepted = await request.post(`/api/v1/suggestions/${calibrate!.id}/accept`);
      expect(accepted.status(), await accepted.text()).toBe(200);
    }
  }
}

test("coach reviews a client, decides suggestions, edits the plan; the athlete sees who did what", async ({ page, browser, baseURL }) => {
  const tag = run();
  const athleteContext = await newContext(browser, baseURL);
  const athletePage = await athleteContext.newPage();
  const coachApi = page.context().request;
  let zedContext: BrowserContext | undefined;
  try {
    const coach = await signUp(coachApi, "coach", `Coach ${tag.slice(-6)}`, tag);
    const alice = await signUp(athleteContext.request, "athlete", `Alice ${tag.slice(-6)}`, `a-${tag}`);
    // Zed sorts after Alice by name but has a deload pending, so the list must put him first.
    zedContext = await newContext(browser, baseURL);
    const zed = await signUp(zedContext.request, "athlete", `Zed ${tag.slice(-6)}`, `z-${tag}`);
    await onboard(athleteContext.request);
    await finishSessionWithSuggestions(athleteContext.request);
    await onboard(zedContext.request);
    await makeDeloadPending(zedContext.request);
    await link(athleteContext.request, coachApi, coach.id);
    await link(zedContext.request, coachApi, coach.id);

    await test.step("the coach signs in and sees the client list", async () => {
      // The sign-up above signed the coach in; start from a clean sign-in like a returning user.
      await page.context().clearCookies();
      await signIn(page, coach);
      await expect(page).toHaveURL(/\/coach\/clients$/);
      await expect(page.getByRole("heading", { level: 1, name: "Clients" })).toBeVisible();
      const rows = page.getByTestId("client-row");
      await expect(rows).toHaveCount(2);
      // Needs-attention clients come first, ahead of Alice who sorts earlier by name.
      await expect(rows.first()).toContainText(zed.name);
      await expect(rows.first()).toContainText("Needs attention");
      await expect(rows.first().getByTestId("attention-reason")).toHaveText("Deload");
      await expect(rows.nth(1)).toContainText(alice.name);
      await expect(rows.nth(1)).not.toContainText("Needs attention");
    });

    await test.step("opens a client and reads Today, Month and Progress", async () => {
      await page.getByRole("link", { name: alice.name }).click();
      await expect(page).toHaveURL(new RegExp(`/coach/clients/${alice.id}$`));
      await expect(page.getByRole("region", { name: "Athlete you are viewing" })).toContainText(`Viewing ${alice.name}`);
      await expect(page.getByRole("link", { name: /start workout|continue workout/i })).toHaveCount(0);
      await page.getByRole("link", { name: "Month", exact: true }).click();
      await expect(page.getByRole("list", { name: /./ }).first()).toBeVisible();
      await page.getByRole("link", { name: "Progress", exact: true }).click();
      await expect(page.getByRole("heading", { level: 2, name: /adherence/i })).toBeVisible();
      await page.getByRole("link", { name: "Today", exact: true }).click();
    });

    await test.step("accepts one suggestion and rejects another", async () => {
      const cards = page.getByTestId("suggestion");
      await expect(cards).not.toHaveCount(0);
      const before = await cards.count();
      expect(before).toBeGreaterThanOrEqual(2);
      await cards.first().getByRole("button", { name: "Accept", exact: true }).click();
      await expect(cards).toHaveCount(before - 1);
      await cards.first().getByRole("button", { name: "Reject", exact: true }).click();
      await expect(cards).toHaveCount(before - 2);
      const decided = page.getByTestId("decided-suggestion");
      await expect(decided).toHaveCount(2);
      await expect(decided.filter({ hasText: `Accepted by ${coach.name}` })).toHaveCount(1);
      await expect(decided.filter({ hasText: `Rejected by ${coach.name}` })).toHaveCount(1);
    });

    await test.step("edits the plan", async () => {
      await page.getByRole("link", { name: "Plan", exact: true }).click();
      const sets = page.getByLabel("Sets").first();
      await sets.fill("4");
      await page.getByRole("button", { name: "Save changes" }).click();
      await expect(page.getByText(/Plan saved/)).toBeVisible();
    });

    await test.step("the athlete sees both decisions as made by the coach, and the plan edit", async () => {
      await athletePage.goto("/today");
      const decided = athletePage.getByTestId("decided-suggestion");
      await expect(decided.filter({ hasText: `Accepted by ${coach.name}` })).toHaveCount(1);
      await expect(decided.filter({ hasText: `Rejected by ${coach.name}` })).toHaveCount(1);
      await athletePage.goto("/plan");
      await expect(athletePage.getByText(`Edited by ${coach.name}`).first()).toBeVisible();
    });
  } finally {
    await athleteContext.close();
    await zedContext?.close();
  }
});

test("coach context fits a 360 px screen with 44 px tap targets", async ({ page, browser, baseURL }) => {
  const tag = run();
  await page.setViewportSize({ width: 360, height: 740 });
  const athleteContext = await newContext(browser, baseURL);
  try {
    const coach = await signUp(page.context().request, "coach", `Coach ${tag.slice(-6)}`, tag);
    const alice = await signUp(athleteContext.request, "athlete", `Alice ${tag.slice(-6)}`, `a-${tag}`);
    await onboard(athleteContext.request);
    await link(athleteContext.request, page.context().request, coach.id);

    const noPageScroll = () =>
      page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth);
    const tallEnough = async (locators: ReturnType<Page["getByRole"]>[]) => {
      for (const locator of locators) {
        const box = await locator.boundingBox();
        expect(box, "tap target is rendered").not.toBeNull();
        expect(box!.height).toBeGreaterThanOrEqual(44);
      }
    };

    await page.goto("/coach/clients");
    await expect(page.getByTestId("client-row")).toHaveCount(1);
    expect(await noPageScroll()).toBe(true);
    await tallEnough([page.getByRole("link", { name: alice.name })]);
    // QA (#48): cards below 1024 px (no column headers), a table from 1024 px.
    await expect(page.getByRole("columnheader", { name: "Client", exact: true })).toBeHidden();
    await page.setViewportSize({ width: 1024, height: 768 });
    await expect(page.getByRole("columnheader", { name: "Client", exact: true })).toBeVisible();
    expect(await page.getByTestId("client-row").first().evaluate((row) => getComputedStyle(row).display)).toBe("table-row");
    await page.setViewportSize({ width: 360, height: 740 });

    for (const tail of ["", "/week", "/month", "/body", "/plan", "/progress", "/profile"]) {
      await page.goto(`/coach/clients/${alice.id}${tail}`);
      await expect(page.getByRole("region", { name: "Athlete you are viewing" })).toBeVisible();
      await expect(page.getByRole("main")).toBeVisible();
      await page.waitForLoadState("networkidle");
      expect(await noPageScroll(), `no horizontal scroll at ${tail || "/"}`).toBe(true);
    }
    await tallEnough([
      page.getByRole("link", { name: "Back to clients" }),
      page.getByRole("navigation", { name: "Client views" }).getByRole("link", { name: "Today", exact: true }),
      page.getByRole("navigation", { name: "Client views" }).getByRole("link", { name: "Plan", exact: true }),
    ]);
  } finally {
    await athleteContext.close();
  }
});
