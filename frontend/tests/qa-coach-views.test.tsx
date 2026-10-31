import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../src/api/schema";
import { calendarDayFixture, dayViewFixture } from "./mocks/calendar";
import { meFixture, meOk } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

// QA (#48): the coach-context Week, Month, Progress, Session and Profile views (not covered by the
// PR's own tests) only request the client's id, never `athletes/me`, and Week offers no Move.

const COACH = meFixture({ id: "c-1", display_name: "Cleo", role: "coach" });
const ANA = "a-1";

const alice: Schemas["CoachAthleteSummary"] = {
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
};

/** Every day from `from` to `to`: every other future day planned, the others rest (so moves exist). */
function weekWithMovableSessions() {
  return http.get(apiUrl("/athletes/:athleteId/calendar"), ({ request }) => {
    const q = new URL(request.url).searchParams;
    const from = q.get("from") ?? "";
    const to = q.get("to") ?? "";
    const days: Schemas["CalendarDay"][] = [];
    const today = new Date().toISOString().slice(0, 10);
    for (let d = new Date(`${from}T00:00:00Z`), i = 0; d.toISOString().slice(0, 10) <= to; d.setUTCDate(d.getUTCDate() + 1), i++) {
      const date = d.toISOString().slice(0, 10);
      const planned = i % 2 === 0 && date > today;
      days.push(
        calendarDayFixture(date, {
          is_today: date === today,
          training_status: planned ? "planned" : "rest",
          training_day_name: planned ? "Upper A" : null,
        }),
      );
    }
    return HttpResponse.json({ from, to, timezone: "Europe/Madrid", days } satisfies Schemas["CalendarRange"]);
  });
}

function recordRequests() {
  const seen: string[] = [];
  server.events.on("request:start", ({ request }) => {
    seen.push(`${request.method} ${new URL(request.url).pathname}`);
  });
  return seen;
}

describe("QA #48: coach-context views", () => {
  beforeEach(() => {
    server.use(
      meOk(COACH),
      http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({ items: [alice] })),
      weekWithMovableSessions(),
      http.get(apiUrl("/athletes/:athleteId/days/:date"), ({ params }) => HttpResponse.json(dayViewFixture(String(params.date)))),
    );
  });

  it.each(["/week", "/month", "/progress", "/progress/session/s-1", "/profile", "/plan", "/body"])(
    "%s requests only athletes/{id}, never athletes/me",
    async (tail) => {
      const seen = recordRequests();
      renderApp(`/coach/clients/${ANA}${tail}`);
      await screen.findByRole("region", { name: "Athlete you are viewing" });
      await waitFor(() => expect(seen.some((r) => r.includes(`/athletes/${ANA}/`))).toBe(true));
      expect(seen.filter((r) => r.includes("/athletes/me"))).toEqual([]);
    },
  );

});

// Monday 26 October 2026 in Madrid; Wednesday has a planned session and free days follow it.
describe("QA #48: Week in coach context has no Move control", () => {
  const WEEK = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"];
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-26T11:00:00Z") });
    server.use(
      http.get(apiUrl("/coach/athletes"), () => HttpResponse.json({ items: [alice] })),
      http.get(apiUrl("/athletes/:athleteId/calendar"), () =>
        HttpResponse.json({
          from: WEEK[0]!,
          to: WEEK[6]!,
          timezone: "Europe/Madrid",
          days: WEEK.map((date, i) =>
            calendarDayFixture(date, {
              is_today: i === 0,
              training_status: date === "2026-10-28" ? "planned" : "rest",
              training_day_name: date === "2026-10-28" ? "Upper A" : null,
            }),
          ),
        } satisfies Schemas["CalendarRange"]),
      ),
    );
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("coach: no Move", async () => {
    server.use(meOk(COACH));
    renderApp(`/coach/clients/${ANA}/week`);
    await screen.findByText("Upper A");
    expect(screen.queryByRole("button", { name: /^Move/ })).not.toBeInTheDocument();
  });

  it("control: the athlete's own Week shows Move for the same calendar", async () => {
    server.use(meOk(meFixture()));
    renderApp("/week");
    await screen.findAllByText("Upper A");
    expect(screen.getByRole("button", { name: /^Move/ })).toBeInTheDocument();
  });
});
