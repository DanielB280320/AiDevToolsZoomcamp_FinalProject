import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { components } from "../src/api/schema";
import { dayViewFixture, sessionFixture } from "./mocks/calendar";
import { meFixture, meOk } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

const SQUAT = { id: "ex-squat", name: "Back squat", type: "strength", equipment: "barbell", muscle_group: "quads" } as const;
const BENCH = { id: "ex-bench", name: "Bench press", type: "strength", equipment: "barbell", muscle_group: "chest" } as const;

const block = (exercise: Schemas["ExerciseSummary"], order: number, isPr: boolean): Schemas["SessionExercise"] => ({
  planned_exercise_id: `pe-${order}`,
  exercise,
  order,
  is_extra: false,
  rule: null,
  sets: [{ set_no: 1, is_extra: false, target_reps: 8, target_weight_kg: 60, target_seconds: null, log: null }],
  reps_min: 8,
  reps_max: 8,
  rest_seconds: 90,
  calibration_hint: null,
  completion: null,
  pending_suggestion_id: null,
  is_pr: isPr,
});

const exercises = [block(SQUAT, 1, true), block(BENCH, 2, false)];
const session = (overrides: Partial<Schemas["Session"]> = {}) =>
  sessionFixture("2026-10-26", { id: "s-1", athlete_id: "a-1", exercises, editable_until: "2099-01-01T00:00:00Z", ...overrides });

const dayOk = () =>
  http.get(apiUrl("/athletes/:athleteId/days/:date"), () =>
    HttpResponse.json(dayViewFixture("2026-10-26", { training_status: "planned", session: session() })),
  );

describe("personal record badge (F15, D88)", () => {
  it("shows on Today's session card only for the exercise with a record", async () => {
    server.use(meOk(meFixture({ id: "a-1", role: "athlete" })), dayOk());
    renderApp("/today");
    const squat = (await screen.findByText("Back squat")).closest("li") as HTMLElement;
    expect(within(squat).getByTestId("pr-badge")).toHaveTextContent("New PR");
    const bench = screen.getByText("Bench press").closest("li") as HTMLElement;
    expect(within(bench).queryByTestId("pr-badge")).not.toBeInTheDocument();
  });

  it("shows on the session detail", async () => {
    server.use(meOk(meFixture({ id: "a-1", role: "athlete" })), http.get(apiUrl("/sessions/:id"), () => HttpResponse.json(session())));
    renderApp("/workout/s-1");
    const card = (await screen.findByRole("heading", { name: /Back squat/ })).closest("section") as HTMLElement;
    expect(within(card).getByTestId("pr-badge")).toBeInTheDocument();
    const other = screen.getByRole("heading", { name: /Bench press/ }).closest("section") as HTMLElement;
    expect(within(other).queryByTestId("pr-badge")).not.toBeInTheDocument();
  });

  it("is listed in the workout summary", async () => {
    const user = userEvent.setup();
    server.use(
      meOk(meFixture({ id: "a-1", role: "athlete" })),
      http.get(apiUrl("/sessions/:id"), () => HttpResponse.json(session())),
      http.post(apiUrl("/sessions/:id/finish"), () =>
        HttpResponse.json({ session: session({ status: "done", completion: 1, kcal: 200 }), suggestions: [] } satisfies Schemas["FinishSessionResult"]),
      ),
      http.get(apiUrl("/athletes/:id/suggestions"), () => HttpResponse.json({ items: [], weigh_in_hint: null })),
    );
    renderApp("/workout/s-1");
    await user.click(await screen.findByRole("button", { name: "Finish workout" }));
    const summary = await screen.findByRole("region", { name: "Workout finished" });
    const list = within(summary).getByRole("list", { name: "Personal records in this workout" });
    expect(within(list).getByText("Back squat")).toBeInTheDocument();
    expect(within(list).queryByText("Bench press")).not.toBeInTheDocument();
  });

  it("is visible to the linked coach on the client's day", async () => {
    const alice: Schemas["CoachAthleteSummary"] = {
      athlete: { id: "a-1", display_name: "Alice", role: "athlete" },
      units: "metric",
      timezone: "Europe/Madrid",
      link_id: "l-1",
      linked_since: "2026-10-01T10:00:00Z",
      needs_attention: false,
      attention_reasons: [],
      training_adherence_7d: 0.85,
      last_log_date: "2026-10-24",
      pending_suggestion_count: 0,
    };
    server.use(
      meOk(meFixture({ id: "c-1", role: "coach" })),
      http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({ items: [alice] })),
      dayOk(),
    );
    renderApp("/coach/clients/a-1");
    const squat = (await screen.findByText("Back squat", {}, { timeout: 8000 })).closest("li") as HTMLElement;
    expect(within(squat).getByTestId("pr-badge")).toBeInTheDocument();
  });
});
