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

// QA (#228 follow-up, D99): the coach view of Today and the session-state descriptions.
const ANA = "a-1";
const alice: Schemas["CoachAthleteSummary"] = {
  athlete: { id: ANA, display_name: "Alice", role: "athlete" },
  units: "metric",
  timezone: "Europe/Madrid",
  link_id: "l-a-1",
  linked_since: "2026-10-01T10:00:00Z",
  needs_attention: false,
  attention_reasons: [],
  training_adherence_7d: 0.85,
  last_log_date: "2026-10-24",
  pending_suggestion_count: 0,
};
const ex: Schemas["SessionExercise"] = {
  planned_exercise_id: "pe-1",
  exercise: { id: "ex-1", name: "Back squat", type: "strength", equipment: "barbell", muscle_group: "quads" },
  order: 1,
  is_extra: false,
  rule: null,
  sets: [{ set_no: 1, is_extra: false, target_reps: 8, target_weight_kg: 60, target_seconds: null, log: null }],
  reps_min: 8,
  reps_max: 8,
  rest_seconds: 90,
  calibration_hint: null,
  completion: 1,
  pending_suggestion_id: null,
  is_pr: false,
};
const day = (status: Schemas["SessionStatus"] | null) =>
  http.get(apiUrl("/athletes/:athleteId/days/:date"), () =>
    HttpResponse.json(
      dayViewFixture("2026-10-26", {
        session: status ? sessionFixture("2026-10-26", { id: "s-1", athlete_id: ANA, status, exercises: [ex] }) : null,
      }),
    ),
  );
const base = () => server.use(meOk(meFixture({ id: "c-1", role: "coach" })), http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({ items: [alice] })));
const trainingText = () =>
  within(screen.getByRole("heading", { level: 2, name: "Training" }).closest("section") as HTMLElement).getByTestId("section-description");

describe("QA D99: coach view of Today", () => {
  it("opens the exercise chart in place and uses the coach wording", async () => {
    base();
    server.use(
      day("done"),
      http.get(apiUrl("/athletes/a-1/charts/session/s-1"), () =>
        HttpResponse.json({
          session_id: "s-1",
          date: "2026-10-26",
          training_day_name: "Legs",
          completion: 1,
          kcal: 100,
          exercises: [
            {
              exercise: ex.exercise,
              is_extra: false,
              completion: 1,
              sets: [{ set_no: 1, is_extra: false, target_reps: 8, target_weight_kg: 60, target_seconds: null, actual_reps: 8, actual_weight_kg: 60, actual_seconds: null, status: "met" }],
            },
          ],
        }),
      ),
    );
    renderApp(`/coach/clients/${ANA}`);
    const li = (await screen.findByText("Back squat")).closest("li") as HTMLElement;
    expect(trainingText()).toHaveTextContent(/Your client finished this workout/);
    const toggle = within(li).getByRole("button", { name: "Back squat" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(await within(li).findByRole("img", { name: "Target versus actual per set for Back squat" })).toBeInTheDocument();
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("rest day: coach and athlete wording", async () => {
    base();
    server.use(day(null));
    renderApp(`/coach/clients/${ANA}`);
    await screen.findByRole("heading", { level: 2, name: "Training" });
    expect(trainingText()).toHaveTextContent(/No workout is planned for your client/);
  });
});

describe("QA D99: athlete training description follows the session state", () => {
  it.each([
    [null, /No workout is planned for today/],
    ["planned", /Start the workout and log each set/],
    ["in_progress", /workout is under way\. Continue/],
    ["done", /workout is finished/],
  ] as const)("%s", async (status, re) => {
    server.use(meOk(meFixture({ id: ANA, role: "athlete" })), day(status));
    renderApp("/today");
    await screen.findByRole("heading", { level: 2, name: "Training" });
    expect(trainingText()).toHaveTextContent(re);
  });
});
