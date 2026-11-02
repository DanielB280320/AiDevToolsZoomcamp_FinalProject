// QA (#57): an imported session has null plan_id, plan_version, training_day_id and
// training_day_name. The consumers (Today, workout/session detail, session chart) must render it.
import { screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../src/api/schema";
import en from "../src/i18n/en.json";
import { dayViewFixture, sessionFixture } from "./mocks/calendar";
import { meFixture, meOk } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

const SESSION_ID = "5a1c0a52-0d2e-4f43-8d3b-2f0e8d5a9a01";
const SQUAT = { id: "ex-squat", name: "Back squat", type: "strength", equipment: "barbell", muscle_group: "quads" } as const;

const importedSession = (): Schemas["Session"] =>
  sessionFixture("2026-10-24", {
    id: SESSION_ID,
    plan_id: null,
    plan_version: null,
    training_day_id: null,
    training_day_name: null,
    imported: true,
    status: "done",
    started_at: "2026-10-24T10:00:00Z",
    finished_at: "2026-10-24T10:00:00Z",
    completion: null,
    kcal: 120,
    exercises: [
      {
        planned_exercise_id: null,
        exercise: SQUAT,
        order: 1,
        is_extra: true,
        rule: null,
        sets: [
          {
            set_no: 1,
            is_extra: true,
            target_reps: null,
            target_weight_kg: null,
            target_seconds: null,
            log: {
              id: "log-1",
              session_id: SESSION_ID,
              planned_exercise_id: null,
              exercise_id: SQUAT.id,
              set_no: 1,
              skipped: false,
              target_reps: null,
              target_weight_kg: null,
              target_seconds: null,
              reps: 8,
              weight_kg: 60,
              seconds: null,
              distance_m: null,
              logged_at: "2026-10-24T10:00:00Z",
            },
          },
        ],
        reps_min: null,
        reps_max: null,
        rest_seconds: 90,
        calibration_hint: null,
        completion: null,
        pending_suggestion_id: null,
        is_pr: false,
      },
    ],
  });

describe("QA #57: imported sessions with null plan fields", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-24T12:00:00Z") });
  });
  afterEach(() => vi.useRealTimers());

  it("Today renders a day holding an imported session", async () => {
    server.use(
      meOk(),
      http.get(apiUrl("/athletes/:athleteId/days/:date"), () =>
        HttpResponse.json(dayViewFixture("2026-10-24", { training_status: "done", session: importedSession() })),
      ),
    );
    renderApp("/today");
    expect(await screen.findByRole("heading", { level: 1 })).toBeInTheDocument();
    expect(screen.queryByText(/Something went wrong/i)).not.toBeInTheDocument();
  });

  it("the workout screen labels an imported session and shows its sets", async () => {
    server.use(meOk(), http.get(apiUrl("/sessions/:id"), () => HttpResponse.json(importedSession())));
    renderApp(`/workout/${SESSION_ID}`);
    expect(await screen.findByRole("heading", { name: en.workout.imported }, { timeout: 20_000 })).toBeInTheDocument();
    expect(screen.getAllByText("Back squat").length).toBeGreaterThan(0);
  });

  it("the session chart labels an imported session", async () => {
    const me = meFixture();
    const chart: Schemas["SessionChart"] = {
      session_id: SESSION_ID,
      date: "2026-10-24",
      training_day_name: null,
      status: "done",
      completion: null,
      kcal: 120,
      exercises: [
        {
          exercise: SQUAT,
          is_extra: true,
          completion: null,
          sets: [
            {
              set_no: 1,
              status: "extra",
              completion: null,
              target_reps: null,
              target_weight_kg: null,
              target_seconds: null,
              reps: 8,
              weight_kg: 60,
              seconds: null,
            },
          ],
        },
      ],
    };
    server.use(meOk(me), http.get(apiUrl(`/athletes/${me.id}/charts/session/${SESSION_ID}`), () => HttpResponse.json(chart)));
    renderApp(`/progress/session/${SESSION_ID}`);
    expect(await screen.findByText(new RegExp(en.workout.imported))).toBeInTheDocument();
  });
});
