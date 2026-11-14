import { http, HttpResponse } from "msw";

import type { components } from "../../src/api/schema";
import { defaultCalendar, defaultDay } from "./calendar";

type Schemas = components["schemas"];

/** MSW pattern for an API path on any origin, e.g. apiUrl("/healthz") matches http://localhost:3000/api/v1/healthz. */
export const apiUrl = (path: string) => `*/api/v1${path}`;

export function athleteProfileFixture(overrides: Partial<Schemas["AthleteProfile"]> = {}): Schemas["AthleteProfile"] {
  return {
    athlete_id: "3f0b6a1e-6a55-4f3c-9a43-1c2a3a4b5c6d",
    sex: "male",
    height_cm: 180,
    lifestyle: "sedentary",
    goal: "cutting",
    experience: "beginner",
    days_per_week: 3,
    preferred_days: ["mon", "wed", "fri"],
    session_minutes: 60,
    equipment: "full_gym",
    avoided_exercise_ids: [],
    diet: "omnivore",
    allergies: [],
    meals_per_day: 3,
    updated_at: "2026-10-20T08:00:00Z",
    ...overrides,
  };
}

export function weeklySummaryFixture(overrides: Partial<Schemas["WeeklySummary"]> = {}): Schemas["WeeklySummary"] {
  return {
    week_start: "2026-10-26",
    week_end: "2026-11-01",
    estimated: true,
    sessions_planned: 0,
    sessions_done: 0,
    sessions_missed: 0,
    avg_completion: null,
    avg_daily_balance_kcal: null,
    target_daily_balance_kcal: null,
    weight_avg_start_kg: null,
    weight_avg_end_kg: null,
    weight_change_kg: null,
    sparklines: { daily_balance_kcal: [], training_completion: [], weight_avg_kg: [] },
    ...overrides,
  };
}

/** Default handlers: the happy path for every endpoint the shell calls. Responses follow openapi.yaml. */
export const handlers = [
  http.get(apiUrl("/healthz"), () => HttpResponse.json({ status: "ok", version: "test" } satisfies Schemas["Health"])),
  defaultDay(),
  defaultCalendar(),
  http.get(apiUrl("/notifications"), () =>
    HttpResponse.json({ items: [], unread_count: 0, next_cursor: null } satisfies Schemas["NotificationPage"]),
  ),
  http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({ items: [] } satisfies Schemas["CoachAthleteList"])),
  // An empty plan: Today only reads it for the "edited by <coach>" labels (F8.3).
  http.get(apiUrl("/athletes/:athleteId/plan"), ({ params }) =>
    HttpResponse.json({
      id: "plan-default",
      athlete_id: String(params.athleteId),
      version: 1,
      source: "generated",
      active: true,
      revision: 0,
      created_by: { id: String(params.athleteId), display_name: "Ana", role: "athlete" },
      created_at: "2026-10-20T08:00:00Z",
      updated_at: "2026-10-20T08:00:00Z",
      warnings: [],
      training_days: [],
      meal_days: [],
    } satisfies Schemas["Plan"]),
  ),
  http.get(apiUrl("/athletes/:athleteId/charts/weekly-summary"), () => HttpResponse.json(weeklySummaryFixture())),
  http.get(apiUrl("/athletes/:athleteId/charts/totals"), () =>
    HttpResponse.json({ sessions_done: 0, personal_records: 0, first_session_date: null } satisfies Schemas["ProgressTotals"]),
  ),
  http.get(apiUrl("/athletes/:athleteId/charts/body"), () =>
    HttpResponse.json({ weeks: 52, estimated: true, points: [] } satisfies Schemas["BodyChart"]),
  ),
  http.get(apiUrl("/athletes/:athleteId/profile"), () => HttpResponse.json(athleteProfileFixture())),
  http.get(apiUrl("/athletes/:athleteId/suggestions"), () =>
    HttpResponse.json({ items: [], weigh_in_hint: null } satisfies Schemas["SuggestionList"]),
  ),
];
