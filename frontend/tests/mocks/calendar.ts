import { http, HttpResponse } from "msw";

import type { components } from "../../src/api/schema";

type Schemas = components["schemas"];

// No import from ./handlers: handlers.ts imports this file for its defaults.
const url = (path: string) => `*/api/v1${path}`;

const ZERO_MACROS: Schemas["Macros"] = { kcal: 0, protein_g: 0, carbs_g: 0, fat_g: 0 };

export function energyFixture(date: string, overrides: Partial<Schemas["EnergyBalance"]> = {}): Schemas["EnergyBalance"] {
  return {
    date,
    estimated: true,
    eaten: ZERO_MACROS,
    planned: ZERO_MACROS,
    target: { kcal: 2400, protein_g: 150, carbs_g: 280, fat_g: 70 },
    burned: { total_kcal: 2200, baseline_kcal: 2000, training_kcal: 200, activities_kcal: 0 },
    balance_kcal: -2200,
    target_balance_kcal: -300,
    ...overrides,
  };
}

/** A rest day by default (no session, no meals). */
export function calendarDayFixture(date: string, overrides: Partial<Schemas["CalendarDay"]> = {}): Schemas["CalendarDay"] {
  return {
    date,
    weekday: "mon",
    is_today: false,
    training_status: "rest",
    session_id: null,
    training_day_name: null,
    moved: false,
    training_completion: null,
    nutrition_completion: null,
    planned_meal_count: 0,
    eaten_meal_count: 0,
    energy: energyFixture(date),
    ...overrides,
  };
}

export function dayViewFixture(date: string, overrides: Partial<Schemas["DayView"]> = {}): Schemas["DayView"] {
  return {
    date,
    weekday: "mon",
    is_today: true,
    training_status: "rest",
    session: null,
    meals: [],
    extra_meal_logs: [],
    activities: [],
    energy: energyFixture(date),
    training_completion: null,
    nutrition_completion: null,
    pending_suggestions: [],
    weigh_in_hint: null,
    notes: [],
    meal_warning: null,
    ...overrides,
  };
}

export function sessionFixture(date: string, overrides: Partial<Schemas["Session"]> = {}): Schemas["Session"] {
  return {
    id: "5a1c0a52-0d2e-4f43-8d3b-2f0e8d5a9a01",
    athlete_id: "3f0b6a1e-6a55-4f3c-9a43-1c2a3a4b5c6d",
    plan_id: "9d1f9e0a-2f4e-4a40-8a58-0f6b3d7a1b02",
    plan_version: 1,
    training_day_id: "c0a8f2de-7b3b-4d0e-9d5e-6a3f4c1b2e03",
    training_day_name: "Upper A",
    date,
    original_date: null,
    status: "planned",
    started_at: null,
    finished_at: null,
    editable_until: "2026-10-26T23:00:00Z",
    completion: null,
    kcal: null,
    estimated: true,
    exercises: [],
    ...overrides,
  };
}

/** Default: today is a rest day. Tests override with `server.use(...)`. */
export const defaultDay = () =>
  http.get(url("/athletes/:athleteId/days/:date"), ({ params }) =>
    HttpResponse.json(dayViewFixture(params.date === "today" ? "2026-10-24" : String(params.date))),
  );

export const defaultCalendar = () =>
  http.get(url("/athletes/:athleteId/calendar"), ({ request }) => {
    const q = new URL(request.url).searchParams;
    return HttpResponse.json({
      from: q.get("from") ?? "",
      to: q.get("to") ?? "",
      timezone: "Europe/Madrid",
      days: [],
    } satisfies Schemas["CalendarRange"]);
  });
