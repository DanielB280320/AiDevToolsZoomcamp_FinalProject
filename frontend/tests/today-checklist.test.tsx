import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { components } from "../src/api/schema";
import { dayViewFixture, sessionFixture } from "./mocks/calendar";
import { meFixture, meOk } from "./mocks/fixtures";
import { apiUrl, athleteProfileFixture } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

const DATE = "2026-10-26";

const planned = (id: string, slot: Schemas["MealSlot"], name: string): Schemas["PlannedMeal"] => ({
  id,
  meal_key: `key-${id}`,
  slot,
  order: 1,
  meal: { id: `m-${id}`, name, slots: [slot] },
  portion_factor: 1,
  items: [],
  totals: { kcal: 300, protein_g: 10, carbs_g: 50, fat_g: 6 },
});

const log = (plannedId: string, status: Schemas["MealLogStatus"]): Schemas["MealLog"] => ({
  id: `log-${plannedId}`,
  date: DATE,
  planned_meal_id: plannedId,
  status,
  slot: null,
  items: [],
  totals: { kcal: 0, protein_g: 0, carbs_g: 0, fat_g: 0 },
  logged_at: "2026-10-26T09:00:00Z",
});

const suggestion = {
  id: "sg-1",
  athlete_id: "a-1",
  kind: "calories",
  status: "pending",
  rule: "adaptive_calories",
  reason: "Weight is flat",
  inputs: {},
  created_at: "2026-10-24T08:00:00Z",
  decided_by: null,
  decided_at: null,
  payload: { current_kcal: 2400, proposed_kcal: 2250, delta_kcal: -150, floor_applied: false, applied_kcal: null },
} as unknown as Schemas["Suggestion"];

function serve(day: Partial<Schemas["DayView"]>, pending: Schemas["Suggestion"][] = []) {
  server.use(
    meOk(meFixture({ id: "a-1", role: "athlete" })),
    http.get(apiUrl("/athletes/:athleteId/days/:date"), () => HttpResponse.json(dayViewFixture(DATE, day))),
    http.get(apiUrl("/athletes/:athleteId/suggestions"), ({ request }) =>
      HttpResponse.json({ items: new URL(request.url).searchParams.get("status") === "pending" ? pending : [], weigh_in_hint: null }),
    ),
  );
}

const session = (status: Schemas["SessionStatus"]) => sessionFixture(DATE, { id: "s-1", athlete_id: "a-1", status });
const item = (key: string) => screen.findByTestId(`checklist-${key}`);

describe("Today: day checklist (F9.5, D100)", () => {
  it("lists what is still pending and links each open item to its section", async () => {
    serve(
      {
        training_status: "planned",
        session: session("planned"),
        meals: [
          { planned_meal: planned("pm-1", "breakfast", "Oat bowl"), log: log("pm-1", "eaten") },
          { planned_meal: planned("pm-2", "lunch", "Rice plate"), log: null },
        ],
      },
      [suggestion],
    );
    renderApp("/today");

    const meals = await item("meals");
    expect(meals).toHaveAttribute("data-done", "false");
    expect(meals).toHaveTextContent("Pending");
    expect(within(meals).getByRole("link", { name: "1 of 2 planned meals logged" })).toHaveAttribute("href", "#today-meals");
    expect(within(await item("training")).getByRole("link", { name: "Workout not started" })).toHaveAttribute("href", "#today-training");
    const suggestions = await item("suggestions");
    expect(within(suggestions).getByRole("link", { name: "1 suggestion to answer" })).toHaveAttribute("href", "#today-suggestions");

    expect(screen.getByTestId("day-summary")).toHaveTextContent("3 of 3 still pending");
    // The link targets exist on the page.
    for (const id of ["today-meals", "today-training", "today-suggestions"]) expect(document.getElementById(id)).not.toBeNull();
    // The checklist is the first section and says what it is for.
    const checklist = screen.getByTestId("day-checklist");
    expect(screen.getAllByRole("heading", { level: 2 })[0]).toHaveTextContent("Day checklist");
    expect(within(checklist).getByTestId("section-description")).toHaveTextContent(/when nothing is pending, the day is complete/);
  });

  it("says the day is complete when every meal is logged, the workout is finished and no suggestion waits", async () => {
    serve({
      training_status: "done",
      training_completion: 1,
      session: sessionFixture(DATE, { id: "s-1", athlete_id: "a-1", status: "done", completion: 1 }),
      meals: [
        { planned_meal: planned("pm-1", "breakfast", "Oat bowl"), log: log("pm-1", "eaten") },
        // A skipped meal is logged: nothing is left to do for it.
        { planned_meal: planned("pm-2", "lunch", "Rice plate"), log: log("pm-2", "skipped") },
      ],
    });
    renderApp("/today");

    expect(await item("suggestions")).toHaveTextContent("No suggestions waiting for an answer");
    const summary = screen.getByTestId("day-summary");
    expect(summary).toHaveTextContent("Day complete: nothing is pending.");
    expect(summary).toHaveAttribute("data-complete", "true");
    expect(await item("meals")).toHaveTextContent("2 of 2 planned meals logged");
    expect(await item("training")).toHaveTextContent("Workout finished");
    for (const key of ["meals", "training", "suggestions"]) {
      const row = screen.getByTestId(`checklist-${key}`);
      expect(row).toHaveAttribute("data-done", "true");
      expect(row).toHaveTextContent("Done");
      expect(within(row).queryByRole("link")).not.toBeInTheDocument();
    }
  });

  it("counts a rest day as done and leaves out meals when none are planned", async () => {
    serve({});
    renderApp("/today");
    expect(await item("training")).toHaveTextContent("Rest day: no workout planned");
    expect(await item("suggestions")).toHaveAttribute("data-done", "true");
    expect(screen.queryByTestId("checklist-meals")).not.toBeInTheDocument();
    expect(screen.getByTestId("day-summary")).toHaveTextContent("Day complete");
  });

  it("names the goal the athlete is working towards", async () => {
    serve({});
    server.use(http.get(apiUrl("/athletes/:athleteId/profile"), () => HttpResponse.json(athleteProfileFixture({ goal: "muscle_gain" }))));
    renderApp("/today");
    const goal = await screen.findByTestId("day-goal");
    expect(goal).toHaveTextContent("Your goal");
    expect(goal).toHaveTextContent("Muscle gain");
    expect(goal).toHaveTextContent("Build muscle with a small calorie surplus.");
    expect(within(screen.getByTestId("day-checklist")).getByTestId("day-goal")).toBe(goal);
  });

  it("shows the checklist without a goal when the profile cannot be read", async () => {
    serve({});
    server.use(http.get(apiUrl("/athletes/:athleteId/profile"), () => HttpResponse.json({ title: "Forbidden", status: 403 }, { status: 403 })));
    renderApp("/today");
    expect(await item("training")).toBeInTheDocument();
    expect(screen.queryByTestId("day-goal")).not.toBeInTheDocument();
  });

  it("keeps a workout in progress pending", async () => {
    serve({ training_status: "planned", session: session("in_progress") });
    renderApp("/today");
    const training = await item("training");
    expect(training).toHaveAttribute("data-done", "false");
    expect(training).toHaveTextContent("Workout in progress");
    await item("suggestions");
    expect(screen.getByTestId("day-summary")).toHaveTextContent("1 of 2 still pending");
  });
});

describe("Tab bar (D100)", () => {
  it("scrolls without a scrollbar and gives every tab the same share of the width", async () => {
    serve({});
    renderApp("/today");
    const nav = await screen.findByRole("navigation", { name: "Calendar views" });
    const strip = within(nav).getByRole("list");
    expect(strip).toHaveClass("no-scrollbar", "overflow-x-auto");
    const tabs = within(strip).getAllByRole("listitem");
    expect(tabs).toHaveLength(7);
    for (const tab of tabs) expect(tab).toHaveClass("flex-1");
    expect(within(nav).getByRole("link", { name: "Today" })).toHaveAttribute("aria-current", "page");
  });
});
