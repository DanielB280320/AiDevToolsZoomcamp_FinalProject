import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { calendarDayFixture, dayViewFixture, energyFixture } from "./mocks/calendar";
import { meFixture, meOk } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

const ATHLETE = meFixture({ role: "athlete", timezone: "Europe/Madrid" });

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-26T11:00:00Z") });
  server.use(meOk(ATHLETE));
});
afterEach(() => {
  vi.useRealTimers();
});

const energy = (date: string) =>
  energyFixture(date, {
    eaten: { kcal: 1800, protein_g: 120, carbs_g: 200, fat_g: 55 },
    target: { kcal: 2400, protein_g: 150, carbs_g: 280, fat_g: 70 },
    burned: { total_kcal: 2500, baseline_kcal: 2100, training_kcal: 300, activities_kcal: 100 },
    balance_kcal: -700,
    target_balance_kcal: -300,
  });

describe("Today energy balance", () => {
  it("shows eaten, burned, balance, target balance and macro bars with aria values", async () => {
    server.use(http.get(apiUrl("/athletes/:athleteId/days/:date"), () => HttpResponse.json(dayViewFixture("2026-10-26", { energy: energy("2026-10-26") }))));
    renderApp("/today");

    const section = (await screen.findByRole("heading", { name: "Estimated energy today" })).closest("section")!;
    const scope = within(section);
    expect(scope.getByText("1800")).toBeInTheDocument();
    expect(scope.getByText("2500")).toBeInTheDocument();
    expect(scope.getByText("-700")).toBeInTheDocument();
    expect(scope.getByText("Target balance (kcal)").nextElementSibling).toHaveTextContent("-300");
    expect(scope.getByText("All calorie numbers are estimates.")).toBeInTheDocument();

    const bars = scope.getAllByRole("progressbar");
    expect(bars.map((b) => b.getAttribute("aria-label"))).toEqual(["Protein", "Carbs", "Fat"]);
    expect(bars[0]).toHaveAttribute("aria-valuenow", "120");
    expect(bars[0]).toHaveAttribute("aria-valuemax", "150");
    expect(bars[1]).toHaveAttribute("aria-valuenow", "200");
    expect(bars[1]).toHaveAttribute("aria-valuemax", "280");
    expect(bars[2]).toHaveAttribute("aria-valuenow", "55");
    expect(bars[2]).toHaveAttribute("aria-valuemax", "70");
  });

  it("hides the macro bars when there are no targets yet", async () => {
    server.use(
      http.get(apiUrl("/athletes/:athleteId/days/:date"), () =>
        HttpResponse.json(dayViewFixture("2026-10-26", { energy: energyFixture("2026-10-26", { target: { kcal: 0, protein_g: 0, carbs_g: 0, fat_g: 0 } }) })),
      ),
    );
    renderApp("/today");
    await screen.findByRole("heading", { name: "Estimated energy today" });
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });
});

describe("Week energy balance", () => {
  it("shows each day's estimated energy and macro bars", async () => {
    const dates = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-10-31", "2026-11-01"];
    server.use(
      http.get(apiUrl("/athletes/:athleteId/calendar"), ({ request }) => {
        const q = new URL(request.url).searchParams;
        const days = dates.map((d, i) => calendarDayFixture(d, { is_today: i === 0, energy: i === 1 ? energy(d) : energyFixture(d) }));
        return HttpResponse.json({ from: q.get("from")!, to: q.get("to")!, timezone: ATHLETE.timezone, days });
      }),
    );
    renderApp("/week");

    const list = await screen.findByRole("list", { name: "Days of the week" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(7);
    const second = within(rows[1]!);
    expect(second.getByText("Estimated")).toBeInTheDocument();
    expect(second.getByText("1800")).toBeInTheDocument();
    expect(second.getByText("Target balance").nextElementSibling).toHaveTextContent("-300");
    const bars = second.getAllByRole("progressbar");
    expect(bars).toHaveLength(3);
    expect(bars[0]).toHaveAttribute("aria-valuenow", "120");
    expect(bars[0]).toHaveAttribute("aria-valuemax", "150");
  });
});
