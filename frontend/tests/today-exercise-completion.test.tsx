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

const block = (name: string, order: number, completion: number | null, isExtra = false): Schemas["SessionExercise"] => ({
  planned_exercise_id: isExtra ? null : `pe-${order}`,
  exercise: { id: `ex-${order}`, name, type: "strength", equipment: "barbell", muscle_group: "chest" },
  order,
  is_extra: isExtra,
  rule: null,
  sets: [{ set_no: 1, is_extra: isExtra, target_reps: 8, target_weight_kg: 60, target_seconds: null, log: null }],
  reps_min: 8,
  reps_max: 8,
  rest_seconds: 90,
  calibration_hint: null,
  completion,
  pending_suggestion_id: null,
  is_pr: false,
});

const exercises = [block("Back squat", 1, 1), block("Bench press", 2, 0.8333), block("Barbell row", 3, 0), block("Cable curl", 4, null, true)];

const dayWith = (status: Schemas["SessionStatus"]) =>
  http.get(apiUrl("/athletes/:athleteId/days/:date"), () =>
    HttpResponse.json(
      dayViewFixture("2026-10-26", {
        training_status: status,
        training_completion: 0.6111,
        session: sessionFixture("2026-10-26", { id: "s-1", athlete_id: "a-1", status, completion: 0.6111, exercises }),
      }),
    ),
  );

const row = async (name: string) => (await screen.findByText(name)).closest("li") as HTMLElement;

describe("Today: completion of the session and per exercise after the session is finished (D97)", () => {
  it("shows each exercise's completion once the session is done", async () => {
    server.use(meOk(meFixture({ id: "a-1", role: "athlete" })), dayWith("done"));
    renderApp("/today");
    const session = await screen.findByTestId("session-completion");
    expect(session).toHaveTextContent("61%");
    // The ring and the bars are progress bars with a name, so the value is not conveyed by the drawing alone.
    expect(within(session).getByRole("progressbar", { name: "Session completion" })).toHaveAttribute("aria-valuenow", "61");
    expect(within(await row("Bench press")).getByRole("progressbar", { name: "Bench press completion" })).toHaveAttribute("aria-valuenow", "83");
    expect(within(await row("Back squat")).getByTestId("exercise-completion")).toHaveTextContent("100% completed");
    expect(within(await row("Bench press")).getByTestId("exercise-completion")).toHaveTextContent("83% completed");
    expect(within(await row("Barbell row")).getByTestId("exercise-completion")).toHaveTextContent("0% completed");
    // An exercise without a completion (added on the spot) shows none.
    expect(within(await row("Cable curl")).queryByTestId("exercise-completion")).not.toBeInTheDocument();
  });

  it("orders the sections: energy, meals, then training (D98)", async () => {
    server.use(meOk(meFixture({ id: "a-1", role: "athlete" })), dayWith("done"));
    renderApp("/today");
    await row("Back squat");
    const titles = screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
    const at = (title: string) => titles.indexOf(title);
    expect(at("Estimated energy today")).toBeGreaterThanOrEqual(0);
    expect(at("Estimated energy today")).toBeLessThan(at("Meals"));
    expect(at("Meals")).toBeLessThan(at("Training"));
  });

  it("shows no completion while the session is still in progress", async () => {
    server.use(meOk(meFixture({ id: "a-1", role: "athlete" })), dayWith("in_progress"));
    renderApp("/today");
    await row("Back squat");
    expect(screen.queryByTestId("exercise-completion")).not.toBeInTheDocument();
    expect(screen.queryByTestId("session-completion")).not.toBeInTheDocument();
  });
});
