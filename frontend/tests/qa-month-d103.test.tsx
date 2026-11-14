import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../src/api/schema";
import { monthKpis } from "../src/features/calendar/monthKpis";
import { calendarDayFixture, dayViewFixture } from "./mocks/calendar";
import { meFixture, meOk } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

// QA for F9.7 / D103: edge cases beyond the author's tests.

const ATHLETE = meFixture({ id: "a-1", role: "athlete", timezone: "Europe/Madrid" });
const SQUAT = { id: "ex-squat", name: "Back squat", type: "strength", equipment: "barbell", muscle_group: "quads" } as const;

const decided = (id: string, decidedAt: string, name = id) =>
  ({
    id,
    athlete_id: ATHLETE.id,
    kind: "progression",
    status: "accepted",
    rule: "double",
    reason: "r",
    inputs: {},
    created_at: "2026-10-01T08:00:00Z",
    decided_by: null,
    decided_at: decidedAt,
    payload: {
      exercise: { ...SQUAT, id: `ex-${id}`, name },
      planned_exercise_id: "pe-1",
      source_session_id: "s-1",
      current: { target_weight_kg: 40, reps_min: 8, reps_max: 12, target_seconds: null },
      proposed: { target_weight_kg: 42.5, reps_min: 8, reps_max: 12, target_seconds: null },
      hint: null,
      applied: null,
    },
  }) as unknown as Schemas["Suggestion"];

function serveSuggestions(all: Schemas["Suggestion"][]) {
  server.use(
    http.get(apiUrl("/athletes/:athleteId/suggestions"), ({ request }) => {
      const status = new URL(request.url).searchParams.get("status");
      return HttpResponse.json({ items: all.filter((s) => s.status === status), weigh_in_hint: null });
    }),
  );
}

function serveMonth() {
  const days = Array.from({ length: 35 }, (_, i) => {
    const date = new Date(Date.UTC(2026, 8, 28 + i)).toISOString().slice(0, 10);
    return calendarDayFixture(date);
  });
  server.use(
    http.get(apiUrl("/athletes/:athleteId/calendar"), ({ request }) => {
      const q = new URL(request.url).searchParams;
      return HttpResponse.json({ from: q.get("from")!, to: q.get("to")!, timezone: ATHLETE.timezone, days });
    }),
    http.get(apiUrl("/athletes/:athleteId/days/:date"), ({ params }) => HttpResponse.json(dayViewFixture(String(params.date), { is_today: false }))),
  );
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-26T11:00:00Z") });
  server.use(meOk(ATHLETE));
});
afterEach(() => {
  vi.useRealTimers();
});

describe("monthKpis edge cases", () => {
  const day = (date: string, o: Partial<Schemas["CalendarDay"]> = {}) => calendarDayFixture(date, o);

  it("a month fully in the past counts every day", () => {
    const days = [
      day("2026-09-01", { training_status: "done", training_completion: 0.8 }),
      day("2026-09-30", { training_status: "missed" }),
    ];
    expect(monthKpis(days, "2026-11-14")).toMatchObject({ sessionsDone: 1, sessionsPlanned: 2, sessionsMissed: 1, sessionsUpcoming: 0, avgCompletion: 0.8 });
  });

  it("an in-progress session is planned but neither done nor missed, and has no completion", () => {
    const days = [day("2026-10-20", { training_status: "in_progress", training_completion: 0.4 })];
    expect(monthKpis(days, "2026-10-26")).toMatchObject({ sessionsDone: 0, sessionsPlanned: 1, sessionsMissed: 0, avgCompletion: null });
  });

  it("a done session without completion does not break the average", () => {
    const days = [day("2026-10-02", { training_status: "done", training_completion: null }), day("2026-10-03", { training_status: "done", training_completion: 0.5 })];
    expect(monthKpis(days, "2026-10-26")).toMatchObject({ sessionsDone: 2, avgCompletion: 0.5 });
  });

  it("an empty month yields dashes, not NaN", () => {
    expect(monthKpis([], "2026-10-26")).toMatchObject({ avgCompletion: null, mealsRatio: null, avgEatenKcal: null, sessionsPlanned: 0 });
  });
});

describe("Month day selection edge cases (D103)", () => {
  it.each(["garbage", "2026-13-45", "2026-10-5", "", "2026-02-30"])("ignores a malformed ?day=%j", async (bad) => {
    serveMonth();
    serveSuggestions([]);
    renderApp(`/month?month=2026-10&day=${bad}`);
    await screen.findByRole("list", { name: "Days of the month" });
    expect(screen.queryByTestId("month-day-detail")).not.toBeInTheDocument();
  });

  it("a day in the grid but outside the month (leading day) is selectable", async () => {
    serveMonth();
    serveSuggestions([]);
    renderApp("/month?month=2026-10&day=2026-09-30");
    expect(await screen.findByRole("region", { name: "Wednesday, September 30" })).toBeInTheDocument();
  });

  it("filters decisions by the athlete's calendar day around local midnight (Madrid is UTC+2 in October)", async () => {
    serveMonth();
    // 21:59:59Z = 23:59:59 on 5 Oct; 22:00:00Z = 00:00:00 on 6 Oct.
    serveSuggestions([decided("before", "2026-10-05T21:59:59Z"), decided("after", "2026-10-05T22:00:00Z"), decided("start", "2026-10-04T22:00:00Z")]);
    const view = renderApp("/month?month=2026-10&day=2026-10-05");
    const fifth = await screen.findByRole("region", { name: "Decisions made this day" });
    expect(within(fifth).getAllByTestId("decided-suggestion").map((r) => r.querySelector("p")?.textContent).sort()).toEqual(["before", "start"]);
    view.unmount();

    renderApp("/month?month=2026-10&day=2026-10-06");
    const sixth = await screen.findByRole("region", { name: "Decisions made this day" });
    expect(within(sixth).getAllByTestId("decided-suggestion").map((r) => r.querySelector("p")?.textContent)).toEqual(["after"]);
  });

  it("a day cell has an accessible name with the date, and the selected one says so in text", async () => {
    serveMonth();
    serveSuggestions([]);
    renderApp("/month?month=2026-10&day=2026-10-12");
    const list = await screen.findByRole("list", { name: "Days of the month" });
    expect(within(list).getByRole("link", { name: /^Monday, October 12 \(selected\)/ })).toBeInTheDocument();
    expect(within(list).getByRole("link", { name: /^Tuesday, October 13$|^Tuesday, October 13[^(]*$/ })).toBeInTheDocument();
    expect(within(list).getAllByRole("listitem").filter((li) => li.hasAttribute("data-selected"))).toHaveLength(1);
    for (const link of within(list).getAllByRole("link")) {
      const tip = document.getElementById(link.getAttribute("aria-describedby")!);
      expect(tip).toHaveAttribute("role", "tooltip");
    }
  });
});

describe("Month in the coach context (D103)", () => {
  it("with a day selected requests only the client's id, never athletes/me, and offers no 'Open this day'", async () => {
    const COACH = meFixture({ id: "c-1", display_name: "Cleo", role: "coach" });
    const ANA = "a-1";
    const seen: string[] = [];
    server.events.on("request:start", ({ request }) => {
      seen.push(`${request.method} ${new URL(request.url).pathname}`);
    });
    serveMonth();
    serveSuggestions([]);
    server.use(
      meOk(COACH),
      http.get(apiUrl("/coach/athletes"), () =>
        HttpResponse.json({
          items: [
            {
              athlete: { id: ANA, display_name: "Alice", role: "athlete" },
              units: "imperial",
              timezone: "Europe/Madrid",
              link_id: "l-a-1",
              linked_since: "2026-10-01T10:00:00Z",
              needs_attention: false,
              attention_reasons: [],
              training_adherence_7d: 0.85,
              last_log_date: "2026-10-24",
              pending_suggestion_count: 0,
            },
          ],
        }),
      ),
    );
    renderApp(`/coach/clients/${ANA}/month?month=2026-10&day=2026-10-05`);
    const detail = await screen.findByTestId("month-day-detail");
    await within(detail).findByRole("region", { name: "Decisions made this day" });
    expect(within(detail).queryByRole("link", { name: "Open this day" })).not.toBeInTheDocument();
    const athleteCalls = seen.filter((r) => r.includes("/athletes/"));
    expect(athleteCalls.length).toBeGreaterThan(0);
    expect(athleteCalls.filter((r) => r.includes("/athletes/me"))).toEqual([]);
    expect(athleteCalls.filter((r) => !r.includes(`/athletes/${ANA}/`))).toEqual([]);
  });
});

describe("Today still caps recent decisions at five", () => {
  it("shows five of seven decisions", async () => {
    serveSuggestions(Array.from({ length: 7 }, (_, i) => decided(`d${i}`, `2026-10-2${i}T09:00:00Z`)));
    server.use(http.get(apiUrl("/athletes/:athleteId/days/:date"), ({ params }) => HttpResponse.json(dayViewFixture(String(params.date)))));
    renderApp("/today");
    const rows = await screen.findAllByTestId("decided-suggestion");
    expect(rows).toHaveLength(5);
  });
});
