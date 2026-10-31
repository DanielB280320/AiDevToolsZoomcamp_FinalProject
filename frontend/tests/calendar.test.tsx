import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../src/api/schema";
import {
  calendarDayFixture,
  dayViewFixture,
  energyFixture,
  sessionFixture,
} from "./mocks/calendar";
import { meFixture, meOk, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type CalendarDay = components["schemas"]["CalendarDay"];

const ATHLETE = meFixture({ role: "athlete", timezone: "Europe/Madrid" });
const SESSION_ID = "5a1c0a52-0d2e-4f43-8d3b-2f0e8d5a9a01";

// Monday 26 October 2026, midday in Madrid. Only Date is faked: MSW and React Query keep real timers.
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-26T11:00:00Z") });
  server.use(meOk(ATHLETE));
});
afterEach(() => {
  vi.useRealTimers();
});

const WEEK_DAYS = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"];

/** The week of 26 Oct: Monday has a planned session, the rest are rest days. */
function weekOf(overrides: Record<string, Partial<CalendarDay>> = {}): CalendarDay[] {
  return WEEK_DAYS.map((date, i) =>
    calendarDayFixture(date, {
      is_today: i === 0,
      ...(i === 0 ? { training_status: "planned", training_day_name: "Upper A" } : {}),
      ...overrides[date],
    }),
  );
}

function calendarOk(days: CalendarDay[], seen?: (from: string | null, to: string | null) => void) {
  return http.get(apiUrl("/athletes/:athleteId/calendar"), ({ request }) => {
    const q = new URL(request.url).searchParams;
    seen?.(q.get("from"), q.get("to"));
    return HttpResponse.json({ from: q.get("from")!, to: q.get("to")!, timezone: ATHLETE.timezone, days });
  });
}

describe("views are reachable", () => {
  it("switches between Today, Week and Month with the tab links", async () => {
    server.use(calendarOk(weekOf()));
    const user = userEvent.setup();
    renderApp("/today");

    const nav = await screen.findByRole("navigation", { name: "Calendar views" });
    expect(within(nav).getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page");

    await user.click(within(nav).getByRole("link", { name: "Week" }));
    expect(await screen.findByRole("list", { name: "Days of the week" })).toBeInTheDocument();

    await user.click(within(screen.getByRole("navigation", { name: "Calendar views" })).getByRole("link", { name: "Month" }));
    expect(await screen.findByRole("list", { name: "Days of the month" })).toBeInTheDocument();
  });

  it("sends a signed-out visitor to sign-in", async () => {
    server.use(http.get(apiUrl("/me"), () => problem(401, "not_authenticated")));
    const { router } = renderApp("/week");
    await waitFor(() => expect(router.state.location.pathname).toBe("/sign-in"));
  });
});

describe("Today", () => {
  it("shows today's session, meals and estimated energy", async () => {
    const date = "2026-10-26";
    server.use(
      http.get(apiUrl("/athletes/:athleteId/days/:date"), ({ params }) => {
        expect(params.date).toBe("today"); // the server resolves "today" in the athlete's zone (F9.1)
        return HttpResponse.json(
          dayViewFixture(date, {
            training_status: "planned",
            session: sessionFixture(date, {
              exercises: [
                {
                  planned_exercise_id: "e1",
                  exercise: { id: "x1", name: "Bench press", type: "strength", equipment: "barbell", muscle_group: "chest" },
                  order: 1,
                  is_extra: false,
                  rule: null,
                  sets: [
                    { set_no: 1, is_extra: false, target_reps: 8, target_weight_kg: 60, target_seconds: null, log: null },
                    { set_no: 2, is_extra: false, target_reps: 8, target_weight_kg: 60, target_seconds: null, log: null },
                  ],
                  reps_min: 8,
                  reps_max: 8,
                  rest_seconds: 90,
                  calibration_hint: null,
                  completion: null,
                  pending_suggestion_id: null,
                },
              ],
            }),
            energy: energyFixture(date, { eaten: { kcal: 650, protein_g: 40, carbs_g: 70, fat_g: 20 }, balance_kcal: -1550 }),
          }),
        );
      }),
    );

    renderApp("/today");

    expect(await screen.findByText("Upper A")).toBeInTheDocument();
    expect(screen.getByText("Bench press")).toBeInTheDocument();
    expect(screen.getByText(/2 sets · 8 reps · 60 kg/)).toBeInTheDocument();
    expect(screen.getByText("Planned")).toBeInTheDocument();
    expect(screen.getByText("650")).toBeInTheDocument();
    expect(screen.getByText("All calorie numbers are estimates.")).toBeInTheDocument();
  });

  it("shows weights in pounds for an imperial user", async () => {
    server.use(meOk(meFixture({ units: "imperial" })));
    const date = "2026-10-26";
    server.use(
      http.get(apiUrl("/athletes/:athleteId/days/:date"), () =>
        HttpResponse.json(
          dayViewFixture(date, {
            training_status: "planned",
            session: sessionFixture(date, {
              exercises: [
                {
                  planned_exercise_id: "e1",
                  exercise: { id: "x1", name: "Squat", type: "strength", equipment: "barbell", muscle_group: "quads" },
                  order: 1,
                  is_extra: false,
                  rule: null,
                  sets: [{ set_no: 1, is_extra: false, target_reps: 5, target_weight_kg: 100, target_seconds: null, log: null }],
                  reps_min: 5,
                  reps_max: 5,
                  rest_seconds: 90,
                  calibration_hint: null,
                  completion: null,
                  pending_suggestion_id: null,
                },
              ],
            }),
          }),
        ),
      ),
    );
    renderApp("/today");
    expect(await screen.findByText(/220\.5 lb/)).toBeInTheDocument();
  });

  it("labels a rest day and a partially completed session", async () => {
    renderApp("/today");
    expect(await screen.findByText("Rest")).toBeInTheDocument();
    expect(screen.getByText("Rest day")).toBeInTheDocument();
  });

  it("shows a retryable error when the day can't load", async () => {
    server.use(http.get(apiUrl("/athletes/:athleteId/days/:date"), () => problem(500, "internal_error")));
    renderApp("/today");
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't load your calendar");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("sends coaches to the client list (they have no day of their own)", async () => {
    server.use(meOk(meFixture({ role: "coach" })));
    renderApp("/today");
    expect(await screen.findByRole("heading", { level: 1, name: "Clients" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Calendar views" })).not.toBeInTheDocument();
  });
});

describe("Week", () => {
  it("asks for Monday to Sunday of the current week in the user's zone", async () => {
    let range: [string | null, string | null] = [null, null];
    server.use(calendarOk(weekOf(), (from, to) => (range = [from, to])));
    renderApp("/week");
    await screen.findByRole("list", { name: "Days of the week" });
    expect(range).toEqual(["2026-10-26", "2026-11-01"]);
  });

  it("shows a badge for done, partial, missed and rest days", async () => {
    server.use(
      calendarOk(
        weekOf({
          "2026-10-26": { training_status: "done", training_completion: 1, training_day_name: "Upper A" },
          "2026-10-27": { training_status: "done", training_completion: 0.5, training_day_name: "Lower A" },
          "2026-10-28": { training_status: "missed", training_day_name: "Upper B" },
        }),
      ),
    );
    renderApp("/week");

    const list = await screen.findByRole("list", { name: "Days of the week" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(7);
    const kinds = rows.map((row) => row.querySelector("[data-status]")?.getAttribute("data-status"));
    expect(kinds).toEqual(["done", "partial", "missed", "rest", "rest", "rest", "rest"]);
    expect(within(rows[2]!).getByText("Missed")).toBeInTheDocument();
    expect(within(rows[3]!).getByText("Rest")).toBeInTheDocument();
    expect(rows[0]).toHaveAttribute("aria-current", "date");
  });

  it("goes to the next week with the arrow", async () => {
    const seen: string[] = [];
    server.use(calendarOk(weekOf(), (from) => seen.push(from ?? "")));
    const user = userEvent.setup();
    renderApp("/week");
    await screen.findByRole("list", { name: "Days of the week" });
    await user.click(screen.getByRole("link", { name: "Next week" }));
    await waitFor(() => expect(seen).toContain("2026-11-02"));
  });
});

describe("Move session within the week", () => {
  it("moves a future planned session to a free day and shows it there", async () => {
    // Plan: Wednesday session, today Monday. After the move the API reports Thursday.
    let days = weekOf({
      "2026-10-26": { training_status: "rest", training_day_name: null },
      "2026-10-28": { training_status: "planned", training_day_name: "Upper A", session_id: null },
    });
    const moves: unknown[] = [];
    server.use(
      calendarOk(days),
      http.get(apiUrl("/athletes/:athleteId/days/:date"), ({ params }) =>
        HttpResponse.json(
          dayViewFixture(String(params.date), { session: sessionFixture(String(params.date), { id: SESSION_ID }) }),
        ),
      ),
      http.post(apiUrl("/sessions/:sessionId/move"), async ({ request, params }) => {
        const body = (await request.json()) as { date: string };
        moves.push({ id: params.sessionId, ...body });
        days = days.map((d) => {
          if (d.date === "2026-10-28") return { ...d, training_status: "rest", training_day_name: null };
          if (d.date === body.date) return { ...d, training_status: "planned", training_day_name: "Upper A", moved: true };
          return d;
        });
        server.use(calendarOk(days));
        return HttpResponse.json(sessionFixture(body.date, { id: SESSION_ID, original_date: "2026-10-28" }));
      }),
    );
    const user = userEvent.setup();
    renderApp("/week");

    const list = await screen.findByRole("list", { name: "Days of the week" });
    const wednesday = within(list).getAllByRole("listitem")[2]!;
    await user.click(within(wednesday).getByRole("button", { name: /Move/ }));
    const select = within(wednesday).getByRole("combobox", { name: /Move Upper A to/ });
    // Only free days from today on: not Wednesday itself.
    const options = within(select).getAllByRole("option").map((o) => o.getAttribute("value"));
    expect(options).toEqual(["2026-10-26", "2026-10-27", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"]);
    await user.selectOptions(select, "2026-10-29");
    await user.click(within(wednesday).getByRole("button", { name: "Move session" }));

    await waitFor(() => expect(moves).toEqual([{ id: SESSION_ID, date: "2026-10-29" }]));
    await waitFor(() => {
      const rows = within(screen.getByRole("list", { name: "Days of the week" })).getAllByRole("listitem");
      expect(rows[3]).toHaveTextContent("Upper A");
      expect(within(rows[3]!).getByText("Moved here")).toBeInTheDocument();
      expect(rows[2]).not.toHaveTextContent("Upper A");
      expect(rows[2]).toHaveTextContent("Rest day");
    });
  });

  it("uses the session id from the calendar when the session already exists", async () => {
    const posted: string[] = [];
    server.use(
      calendarOk(weekOf({ "2026-10-26": { session_id: SESSION_ID } })),
      http.post(apiUrl("/sessions/:sessionId/move"), ({ params }) => {
        posted.push(String(params.sessionId));
        return HttpResponse.json(sessionFixture("2026-10-27"));
      }),
    );
    const user = userEvent.setup();
    renderApp("/week");
    const monday = within(await screen.findByRole("list", { name: "Days of the week" })).getAllByRole("listitem")[0]!;
    await user.click(within(monday).getByRole("button", { name: /Move/ }));
    await user.click(within(monday).getByRole("button", { name: "Move session" }));
    await waitFor(() => expect(posted).toEqual([SESSION_ID]));
  });

  it("explains a refusal from the server and keeps the session where it was", async () => {
    server.use(
      calendarOk(weekOf({ "2026-10-26": { session_id: SESSION_ID } })),
      http.post(apiUrl("/sessions/:sessionId/move"), () => problem(409, "day_occupied")),
    );
    const user = userEvent.setup();
    renderApp("/week");
    const monday = within(await screen.findByRole("list", { name: "Days of the week" })).getAllByRole("listitem")[0]!;
    await user.click(within(monday).getByRole("button", { name: /Move/ }));
    await user.click(within(monday).getByRole("button", { name: "Move session" }));

    expect(await within(monday).findByRole("alert")).toHaveTextContent("That day already has a session");
    expect(monday).toHaveTextContent("Upper A");
  });

  it("offers no move for finished, in-progress, missed or past sessions, nor when no day is free", async () => {
    server.use(
      calendarOk(
        weekOf({
          "2026-10-26": { training_status: "in_progress", training_day_name: "Upper A" },
          "2026-10-27": { training_status: "done", training_day_name: "Lower A" },
          "2026-10-28": { training_status: "missed", training_day_name: "Upper B" },
        }),
      ),
    );
    renderApp("/week");
    await screen.findByRole("list", { name: "Days of the week" });
    expect(screen.queryByRole("button", { name: /Move/ })).not.toBeInTheDocument();
  });

  it("offers no move when every other day already has a session", async () => {
    const full = Object.fromEntries(
      WEEK_DAYS.map((d) => [d, { training_status: "planned", training_day_name: "X" } as Partial<CalendarDay>]),
    );
    server.use(calendarOk(weekOf(full)));
    renderApp("/week");
    await screen.findByRole("list", { name: "Days of the week" });
    expect(screen.queryByRole("button", { name: /Move/ })).not.toBeInTheDocument();
  });

  it("does not offer days before today", async () => {
    // Viewing last week: its rest days are all in the past, so nothing can be moved there.
    const lastWeek = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-24", "2026-10-25"].map(
      (d, i) => calendarDayFixture(d, i === 0 ? { training_status: "planned", training_day_name: "Upper A" } : {}),
    );
    server.use(calendarOk(lastWeek));
    renderApp("/week?week=2026-10-19");
    await screen.findByRole("list", { name: "Days of the week" });
    expect(screen.queryByRole("button", { name: /Move/ })).not.toBeInTheDocument();
  });
});

describe("Month", () => {
  it("requests the grid of weeks covering the month and shows a badge and nutrition % per day", async () => {
    let range: [string | null, string | null] = [null, null];
    const days = Array.from({ length: 35 }, (_, i) => {
      const date = new Date(Date.UTC(2026, 8, 28 + i)).toISOString().slice(0, 10);
      return calendarDayFixture(date, {
        ...(date === "2026-10-05" ? { training_status: "done", training_completion: 1, nutrition_completion: 0.75 } : {}),
        ...(date === "2026-10-07" ? { training_status: "missed" } : {}),
        ...(date === "2026-10-09" ? { training_status: "done", training_completion: 0.4 } : {}),
      });
    });
    server.use(calendarOk(days, (from, to) => (range = [from, to])));
    renderApp("/month");

    const list = await screen.findByRole("list", { name: "Days of the month" });
    expect(range).toEqual(["2026-09-28", "2026-11-01"]);
    const cells = within(list).getAllByRole("listitem");
    expect(cells).toHaveLength(35);
    const kind = (i: number) => cells[i]!.querySelector("[data-status]")?.getAttribute("data-status");
    expect(kind(7)).toBe("done"); // 5 Oct
    expect(within(cells[7]!).getByText("75%")).toBeInTheDocument();
    expect(kind(9)).toBe("missed"); // 7 Oct
    expect(kind(11)).toBe("partial"); // 9 Oct
    expect(kind(8)).toBe("rest");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("October 2026");
    // Each day links to its week.
    expect(within(cells[7]!).getByRole("link")).toHaveAttribute("href", "/week?week=2026-10-05");
  });

  it("falls back to the current month for an invalid month param", async () => {
    renderApp("/month?month=nonsense");
    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("October 2026");
  });
});
