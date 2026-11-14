import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { components } from "../src/api/schema";
import { dayViewFixture, sessionFixture } from "./mocks/calendar";
import { meFixture, meOk } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

const block = (name: string, order: number, completion: number | null): Schemas["SessionExercise"] => ({
  planned_exercise_id: `pe-${order}`,
  exercise: { id: `ex-${order}`, name, type: "strength", equipment: "barbell", muscle_group: "chest" },
  order,
  is_extra: false,
  rule: null,
  sets: [{ set_no: 1, is_extra: false, target_reps: 8, target_weight_kg: 60, target_seconds: null, log: null }],
  reps_min: 8,
  reps_max: 8,
  rest_seconds: 90,
  calibration_hint: null,
  completion,
  pending_suggestion_id: null,
  is_pr: false,
});

const dayWith = (sessionCompletion: number | null, exercises: Schemas["SessionExercise"][]) =>
  http.get(apiUrl("/athletes/:athleteId/days/:date"), () =>
    HttpResponse.json(
      dayViewFixture("2026-10-26", {
        training_status: "done",
        training_completion: sessionCompletion,
        session: sessionFixture("2026-10-26", { id: "s-1", athlete_id: "a-1", status: "done", completion: sessionCompletion, exercises }),
      }),
    ),
  );

const row = async (name: string) => (await screen.findByText(name)).closest("li") as HTMLElement;

describe("QA #230: charts edge values", () => {
  it("draws 100 % and 0 % exercise bars and a 100 % ring", async () => {
    server.use(meOk(meFixture({ id: "a-1", role: "athlete" })), dayWith(1, [block("Back squat", 1, 1), block("Barbell row", 2, 0)]));
    renderApp("/today");
    const ring = within(await screen.findByTestId("session-completion")).getByRole("progressbar", { name: "Session completion" });
    expect(ring).toHaveAttribute("aria-valuenow", "100");
    expect(ring).toHaveTextContent("100%");
    const full = within(await row("Back squat")).getByRole("progressbar");
    expect(full).toHaveAttribute("aria-valuenow", "100");
    expect(full.firstElementChild).toHaveStyle({ width: "100%" });
    const none = within(await row("Barbell row")).getByRole("progressbar");
    expect(none).toHaveAttribute("aria-valuenow", "0");
    expect(none.firstElementChild).toHaveStyle({ width: "0%" });
  });

  it("shows a 0 % ring and no ring or bar for a null completion", async () => {
    server.use(meOk(meFixture({ id: "a-1", role: "athlete" })), dayWith(0, [block("Back squat", 1, null)]));
    renderApp("/today");
    expect(within(await screen.findByTestId("session-completion")).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
    expect(within(await row("Back squat")).queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("shows no ring when the session completion is null", async () => {
    server.use(meOk(meFixture({ id: "a-1", role: "athlete" })), dayWith(null, [block("Back squat", 1, 0.5)]));
    renderApp("/today");
    await row("Back squat");
    expect(screen.queryByTestId("session-completion")).not.toBeInTheDocument();
  });

  it("dates a decision in the athlete's time zone across the day boundary", async () => {
    const sg = (decided_at: string) =>
      ({
        id: "sg-1", athlete_id: "a-1", kind: "calories", status: "accepted", rule: "adaptive_calories", reason: "r", inputs: {},
        created_at: "2026-10-24T08:00:00Z", decided_by: { id: "a-1", display_name: "Ana", role: "athlete" }, decided_at,
        payload: { current_kcal: 2400, proposed_kcal: 2250, delta_kcal: -150, floor_applied: false, applied_kcal: null },
      }) as unknown as Schemas["Suggestion"];
    server.use(
      meOk(meFixture({ id: "a-1", role: "athlete", timezone: "Pacific/Auckland" })),
      http.get(apiUrl("/athletes/:athleteId/suggestions"), ({ request }) => {
        const accepted = new URL(request.url).searchParams.get("status") === "accepted";
        return HttpResponse.json({ items: accepted ? [sg("2026-10-24T23:30:00Z")] : [], weigh_in_hint: null });
      }),
    );
    renderApp("/today");
    // 23:30Z on the 24th is the 25th in Auckland (UTC+13 in late October).
    expect(await screen.findByTestId("decided-suggestion")).toHaveTextContent("Oct 25, 2026");
  });
});
