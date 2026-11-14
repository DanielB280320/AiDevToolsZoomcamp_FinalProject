import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../src/api/schema";
import { monthKpis } from "../src/features/calendar/monthKpis";
import { calendarDayFixture, dayViewFixture, energyFixture, sessionFixture } from "./mocks/calendar";
import { meFixture, meOk } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];
type CalendarDay = Schemas["CalendarDay"];

// D103: the Month view's description, figures, hover summary and the detail of the selected day.

const ATHLETE = meFixture({ id: "a-1", role: "athlete", timezone: "Europe/Madrid" });
const SESSION_ID = "s-1";
const MACROS = { protein_g: 0, carbs_g: 0, fat_g: 0 };
const eaten = (date: string, kcal: number) => energyFixture(date, { eaten: { kcal, ...MACROS } });

/** October 2026 on its grid (28 Sep to 1 Nov); today is Monday 26 October. */
const OVERRIDES: Record<string, Partial<CalendarDay>> = {
  // 30 Sep is on the grid but not in October: it must not count.
  "2026-09-30": { training_status: "missed", training_day_name: "Upper A", planned_meal_count: 4 },
  "2026-10-05": {
    training_status: "done",
    training_day_name: "Upper A",
    session_id: SESSION_ID,
    training_completion: 1,
    nutrition_completion: 0.75,
    planned_meal_count: 4,
    eaten_meal_count: 3,
    energy: eaten("2026-10-05", 2000),
  },
  "2026-10-07": { training_status: "missed", training_day_name: "Lower A", planned_meal_count: 4, eaten_meal_count: 1, energy: eaten("2026-10-07", 1000) },
  "2026-10-09": { training_status: "done", training_day_name: "Upper B", training_completion: 0.5 },
  "2026-10-26": { is_today: true, training_status: "planned", training_day_name: "Upper A" },
  "2026-10-28": { training_status: "planned", training_day_name: "Lower A", planned_meal_count: 4 },
};
const DAYS = Array.from({ length: 35 }, (_, i) => {
  const date = new Date(Date.UTC(2026, 8, 28 + i)).toISOString().slice(0, 10);
  return calendarDayFixture(date, OVERRIDES[date]);
});

const calendarOk = () =>
  http.get(apiUrl("/athletes/:athleteId/calendar"), ({ request }) => {
    const q = new URL(request.url).searchParams;
    return HttpResponse.json({ from: q.get("from")!, to: q.get("to")!, timezone: ATHLETE.timezone, days: DAYS });
  });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-26T11:00:00Z") });
  server.use(meOk(ATHLETE), calendarOk());
});
afterEach(() => {
  vi.useRealTimers();
});

describe("monthKpis", () => {
  const october = DAYS.filter((d) => d.date.startsWith("2026-10"));

  it("counts only the days up to today", () => {
    expect(monthKpis(october, "2026-10-26")).toEqual({
      sessionsDone: 2,
      sessionsPlanned: 4, // two done, one missed, today's planned one
      sessionsUpcoming: 1,
      sessionsMissed: 1,
      avgCompletion: 0.75,
      mealsEaten: 4,
      mealsPlanned: 8,
      mealsRatio: 0.5,
      avgEatenKcal: 1500,
      daysWithMeals: 2,
    });
  });

  it("has nothing to average for a month that has not started", () => {
    const kpis = monthKpis(october, "2026-09-30");
    expect(kpis).toMatchObject({ sessionsDone: 0, sessionsPlanned: 0, avgCompletion: null, mealsRatio: null, avgEatenKcal: null });
    expect(kpis.sessionsUpcoming).toBe(5);
  });
});

describe("Month: description, figures and hover summary (D103)", () => {
  it("says what the view is for and shows the month's figures up to today", async () => {
    renderApp("/month");
    await screen.findByRole("list", { name: "Days of the month" });
    expect(screen.getByTestId("month-description")).toHaveTextContent(/Your month at a glance.*Select a day.*logged on Today/);

    const kpis = screen.getByRole("region", { name: "October 2026 in figures" });
    expect(kpis).toHaveTextContent("Days up to today.");
    expect(within(kpis).getByTestId("kpi-month-workouts")).toHaveTextContent(/2 of 4.*1 still planned/);
    expect(within(kpis).getByTestId("kpi-month-completion")).toHaveTextContent("75%");
    expect(within(kpis).getByTestId("kpi-month-missed")).toHaveTextContent("1");
    expect(within(kpis).getByTestId("kpi-month-meals")).toHaveTextContent(/50%.*4 of 8/);
    expect(within(kpis).getByTestId("kpi-month-kcal")).toHaveTextContent(/1500 kcal.*2 days with meals logged/);
  });

  it("shows dashes for a month that has not started", async () => {
    renderApp("/month?month=2026-12");
    const kpis = await screen.findByRole("region", { name: "December 2026 in figures" });
    expect(kpis).toHaveTextContent("This month has not started yet.");
    for (const id of ["workouts", "completion", "missed", "meals", "kcal"]) {
      expect(within(kpis).getByTestId(`kpi-month-${id}`)).toHaveTextContent("—");
    }
  });

  it("describes each day with a summary tooltip: workout and status, meals and calories", async () => {
    renderApp("/month");
    const list = await screen.findByRole("list", { name: "Days of the month" });
    const cell = within(list).getAllByRole("listitem")[7]!; // 5 Oct
    const tip = within(cell).getByRole("tooltip", { hidden: true });
    expect(tip).toHaveTextContent("Upper A · Done");
    expect(tip).toHaveTextContent("3 of 4 meals eaten");
    expect(tip).toHaveTextContent("Eaten 2000 kcal · burned 2200 kcal (estimated)");
    expect(within(cell).getByRole("link")).toHaveAttribute("aria-describedby", tip.id);
    // Shown on hover and keyboard focus only.
    expect(tip.className).toMatch(/hidden.*group-hover:block.*focus-visible/);
  });
});

describe("Month: the selected day (D103)", () => {
  const SQUAT = { id: "ex-squat", name: "Back squat", type: "strength", equipment: "barbell", muscle_group: "quads" } as const;
  const macros = (kcal: number) => ({ kcal, protein_g: 10, carbs_g: 50, fat_g: 6 });
  const planned = (id: string, slot: Schemas["MealSlot"], name: string): Schemas["PlannedMeal"] => ({
    id,
    meal_key: `key-${id}`,
    slot,
    order: 1,
    meal: { id: `m-${id}`, name, slots: [slot] },
    portion_factor: 1,
    items: [],
    totals: macros(300),
  });
  const log = (id: string, plannedId: string | null, status: Schemas["MealLogStatus"], kcal: number, extra: Partial<Schemas["MealLog"]> = {}) =>
    ({
      id,
      date: "2026-10-05",
      planned_meal_id: plannedId,
      status,
      slot: null,
      items: [],
      totals: macros(kcal),
      logged_at: "2026-10-05T09:00:00Z",
      ...extra,
    }) as Schemas["MealLog"];
  const decided = (id: string, status: "accepted" | "rejected", decidedAt: string, name: string) =>
    ({
      id,
      athlete_id: ATHLETE.id,
      kind: "progression",
      status,
      rule: "double",
      reason: "r",
      inputs: {},
      created_at: "2026-10-05T08:00:00Z",
      decided_by: null,
      decided_at: decidedAt,
      payload: {
        exercise: { ...SQUAT, id: `ex-${id}`, name },
        planned_exercise_id: "pe-1",
        source_session_id: SESSION_ID,
        current: { target_weight_kg: 40, reps_min: 8, reps_max: 12, target_seconds: null },
        proposed: { target_weight_kg: 42.5, reps_min: 8, reps_max: 12, target_seconds: null },
        hint: null,
        applied: null,
      },
    }) as unknown as Schemas["Suggestion"];
  const chart: Schemas["SessionChart"] = {
    session_id: SESSION_ID,
    date: "2026-10-05",
    training_day_name: "Upper A",
    status: "done",
    completion: 1,
    kcal: 300,
    exercises: [
      {
        exercise: SQUAT,
        is_extra: false,
        completion: 1,
        sets: [{ set_no: 1, status: "met", completion: 1, target_reps: 8, target_weight_kg: 60, target_seconds: null, reps: 8, weight_kg: 60, seconds: null }],
      },
    ],
  };

  function serveDay() {
    const requested: string[] = [];
    server.use(
      http.get(apiUrl("/athletes/:athleteId/days/:date"), ({ params }) => {
        const date = String(params.date);
        requested.push(date);
        if (date !== "2026-10-05") return HttpResponse.json(dayViewFixture(date, { is_today: false }));
        return HttpResponse.json(
          dayViewFixture(date, {
            is_today: false,
            training_status: "done",
            training_completion: 1,
            session: sessionFixture(date, { id: SESSION_ID, status: "done", completion: 1 }),
            meals: [
              { planned_meal: planned("pm-1", "breakfast", "Oat bowl"), log: log("l-1", "pm-1", "eaten", 320) },
              { planned_meal: planned("pm-2", "lunch", "Rice plate"), log: log("l-2", "pm-2", "skipped", 0) },
              { planned_meal: planned("pm-3", "dinner", "Fish and potatoes"), log: null },
            ],
            extra_meal_logs: [
              log("l-3", null, "eaten", 95, {
                slot: "snack",
                items: [{ food: { id: "f-1", name: "Apple" }, grams: 180, ...macros(95) }] as unknown as Schemas["MealLog"]["items"],
              }),
            ],
            energy: energyFixture(date, { eaten: macros(415) }),
          }),
        );
      }),
      http.get(apiUrl(`/athletes/${ATHLETE.id}/charts/session/${SESSION_ID}`), () => HttpResponse.json(chart)),
      http.get(apiUrl("/athletes/:athleteId/suggestions"), ({ request }) => {
        const status = new URL(request.url).searchParams.get("status");
        const all = [
          // 22:30 UTC on 4 Oct is already 5 Oct in Madrid.
          decided("sg-1", "accepted", "2026-10-04T22:30:00Z", "Back squat"),
          decided("sg-2", "rejected", "2026-10-05T10:00:00Z", "Bench press"),
          decided("sg-3", "accepted", "2026-10-06T10:00:00Z", "Deadlift"),
        ];
        return HttpResponse.json({ items: all.filter((s) => s.status === status), weigh_in_hint: null });
      }),
    );
    return requested;
  }

  it("shows nothing below the grid until a day is selected, and requests no day", async () => {
    const requested = serveDay();
    renderApp("/month");
    await screen.findByRole("list", { name: "Days of the month" });
    expect(screen.queryByTestId("month-day-detail")).not.toBeInTheDocument();
    expect(requested).toEqual([]);
  });

  it("selecting a day stays on Month and shows its workout, session chart, meals, energy and decisions", async () => {
    serveDay();
    const user = userEvent.setup();
    renderApp("/month");
    const list = await screen.findByRole("list", { name: "Days of the month" });
    await user.click(within(list).getByRole("link", { name: /Monday, October 5/ }));

    const detail = await screen.findByRole("region", { name: "Monday, October 5" });
    // Still the Month view, with the day marked as selected.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("October 2026");
    expect(within(list).getByRole("link", { name: /Monday, October 5 \(selected\)/ })).toBeInTheDocument();

    // Training: status with its reason, completion and the session chart.
    const training = await within(detail).findByRole("region", { name: "Training" });
    expect(within(training).getByText("Upper A")).toBeInTheDocument();
    expect(within(training).getByTestId("status-reason")).toHaveTextContent(/^Done:/);
    expect(within(training).getByTestId("session-completion")).toHaveTextContent("100%");
    expect(await within(training).findByRole("heading", { level: 3, name: /Back squat/ })).toBeInTheDocument();
    expect(within(training).getAllByTestId("set-row")).toHaveLength(1);

    // Meals: what was logged for each planned meal, then the extra one.
    const meals = within(within(detail).getByTestId("month-day-meals")).getAllByRole("listitem");
    expect(meals.map((m) => m.textContent)).toEqual([
      "Breakfast Oat bowlEaten as planned · 320 kcal",
      "Lunch Rice plateSkipped",
      "Dinner Fish and potatoesNot logged",
      "Snack AppleLogged outside the plan · 95 kcal",
    ]);
    expect(within(detail).getByRole("region", { name: "Estimated energy" })).toHaveTextContent("415");

    // Decisions: only those made on that day in the athlete's time zone.
    const decisions = within(detail).getByRole("region", { name: "Decisions made this day" });
    const rows = within(decisions).getAllByTestId("decided-suggestion");
    expect(rows.map((r) => r.querySelector("p")?.textContent).sort()).toEqual(["Back squat", "Bench press"]);

    expect(within(detail).getByRole("link", { name: "Open this day" })).toHaveAttribute("href", "/today?date=2026-10-05");
    expect(within(detail).getByRole("link", { name: "See its week" })).toHaveAttribute("href", "/week?week=2026-10-05");
  });

  it("says so when no decision was made on the selected day, and ignores a day outside the grid", async () => {
    serveDay();
    const view = renderApp("/month?month=2026-10&day=2026-10-12");
    const detail = await screen.findByRole("region", { name: "Monday, October 12" });
    expect(await within(detail).findByText("No suggestion was accepted or rejected on this day.")).toBeInTheDocument();
    expect(await within(detail).findByText(/^Rest: no workout was planned/)).toBeInTheDocument();
    expect(within(detail).getByText("No meals planned")).toBeInTheDocument();
    view.unmount();

    renderApp("/month?month=2026-10&day=2026-12-25");
    await screen.findByRole("list", { name: "Days of the month" });
    expect(screen.queryByTestId("month-day-detail")).not.toBeInTheDocument();
  });
});
