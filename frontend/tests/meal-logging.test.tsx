import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { components } from "../src/api/schema";
import { dayViewFixture, energyFixture } from "./mocks/calendar";
import { meFixture, meOk } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

const DATE = "2026-10-26";
const OATS = "11111111-1111-4111-8111-111111111111";
const PLANNED = "22222222-2222-4222-8222-222222222222";
const PLANNED_2 = "33333333-3333-4333-8333-333333333333";

function planned(
  id: string,
  slot: Schemas["MealSlot"],
  name: string,
): Schemas["PlannedMeal"] {
  return {
    id,
    slot,
    order: 1,
    meal: { id: `m-${id}`, name, slots: [slot] },
    portion_factor: 1,
    items: [
      {
        food: { id: OATS, name: "Oats", source: "seed" },
        grams: 80,
        kcal: 300,
        protein_g: 10,
        carbs_g: 50,
        fat_g: 6,
      },
    ],
    totals: { kcal: 300, protein_g: 10, carbs_g: 50, fat_g: 6 },
  };
}

function logOf(
  status: Schemas["MealLogStatus"],
  plannedId: string | null,
  grams = 80,
): Schemas["MealLog"] {
  return {
    id: "44444444-4444-4444-8444-444444444444",
    date: DATE,
    planned_meal_id: plannedId,
    status,
    slot: plannedId ? null : "snack",
    items:
      status === "skipped"
        ? []
        : [
            {
              food: { id: OATS, name: "Oats", source: "seed" },
              grams,
              kcal: 300,
              protein_g: 10,
              carbs_g: 50,
              fat_g: 6,
            },
          ],
    totals: {
      kcal: status === "skipped" ? 0 : 300,
      protein_g: 10,
      carbs_g: 50,
      fat_g: 6,
    },
    logged_at: "2026-10-26T09:00:00Z",
  };
}

let day: Schemas["DayView"];
let posts: unknown[];

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-10-26T11:00:00Z") });
  server.use(meOk(meFixture({ role: "athlete", timezone: "Europe/Madrid" })));
  posts = [];
  day = dayViewFixture(DATE, {
    meals: [
      { planned_meal: planned(PLANNED, "breakfast", "Oat bowl"), log: null },
      { planned_meal: planned(PLANNED_2, "lunch", "Rice plate"), log: null },
    ],
    energy: energyFixture(DATE),
  });
  server.use(
    http.get(apiUrl("/athletes/:athleteId/days/:date"), () =>
      HttpResponse.json(day),
    ),
    http.post(apiUrl("/athletes/:athleteId/meal-logs"), async ({ request }) => {
      const body = (await request.json()) as Schemas["MealLogInput"];
      posts.push(body);
      const log = logOf(
        body.status,
        body.planned_meal_id,
        body.items?.[0]?.grams,
      );
      if (body.status === "extra") day = { ...day, extra_meal_logs: [log] };
      else
        day = {
          ...day,
          meals: day.meals.map((m) =>
            m.planned_meal.id === body.planned_meal_id ? { ...m, log } : m,
          ),
        };
      return HttpResponse.json(
        {
          meal_log: log,
          energy: energyFixture(DATE),
          nutrition_completion: 0.5,
        },
        { status: 201 },
      );
    }),
  );
});
afterEach(() => {
  vi.useRealTimers();
});

describe("Today meals (F12)", () => {
  it("checks a meal off as planned with one tap", async () => {
    const user = userEvent.setup();
    renderApp("/today");
    await user.click(
      await screen.findByRole("button", { name: "Eaten as planned: Oat bowl" }),
    );

    await waitFor(() =>
      expect(posts).toEqual([
        { date: DATE, planned_meal_id: PLANNED, status: "eaten" },
      ]),
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Eaten as planned",
    );
    // The other meal is untouched.
    expect(
      screen.getByRole("button", { name: "Eaten as planned: Rice plate" }),
    ).toBeInTheDocument();
  });

  it("skips a meal", async () => {
    const user = userEvent.setup();
    renderApp("/today");
    await user.click(
      await screen.findByRole("button", { name: "Skip: Rice plate" }),
    );

    await waitFor(() =>
      expect(posts).toEqual([
        { date: DATE, planned_meal_id: PLANNED_2, status: "skipped" },
      ]),
    );
    expect(await screen.findByText("Skipped")).toBeInTheDocument();
  });

  it("adjusts the grams per food", async () => {
    const user = userEvent.setup();
    renderApp("/today");
    await user.click(
      await screen.findByRole("button", { name: "Adjust: Oat bowl" }),
    );
    const grams = screen.getByRole("spinbutton", { name: "Grams of Oats" });
    expect(grams).toHaveValue(80);
    await user.clear(grams);
    await user.type(grams, "55");
    await user.click(screen.getByRole("button", { name: "Save grams" }));

    await waitFor(() =>
      expect(posts).toEqual([
        {
          date: DATE,
          planned_meal_id: PLANNED,
          status: "adjusted",
          items: [{ food_id: OATS, grams: 55 }],
        },
      ]),
    );
  });

  it("does not allow saving zero grams", async () => {
    const user = userEvent.setup();
    renderApp("/today");
    await user.click(
      await screen.findByRole("button", { name: "Adjust: Oat bowl" }),
    );
    const grams = screen.getByRole("spinbutton", { name: "Grams of Oats" });
    await user.clear(grams);
    await user.type(grams, "0");
    expect(screen.getByRole("button", { name: "Save grams" })).toBeDisabled();
  });

  it("undoes a check-off", async () => {
    day = {
      ...day,
      meals: [
        {
          planned_meal: planned(PLANNED, "breakfast", "Oat bowl"),
          log: logOf("eaten", PLANNED),
        },
      ],
    };
    let deleted = false;
    server.use(
      http.delete(apiUrl("/athletes/:athleteId/meal-logs/:id"), () => {
        deleted = true;
        day = {
          ...day,
          meals: [
            {
              planned_meal: planned(PLANNED, "breakfast", "Oat bowl"),
              log: null,
            },
          ],
        };
        return HttpResponse.json({
          energy: energyFixture(DATE),
          nutrition_completion: 0,
        });
      }),
    );
    const user = userEvent.setup();
    renderApp("/today");
    await user.click(
      await screen.findByRole("button", { name: "Undo: Oat bowl" }),
    );
    await waitFor(() => expect(deleted).toBe(true));
    expect(
      await screen.findByRole("button", { name: "Eaten as planned: Oat bowl" }),
    ).toBeInTheDocument();
  });

  it("adds a food from the library as extra food", async () => {
    server.use(
      http.get(apiUrl("/foods"), () =>
        HttpResponse.json({
          items: [
            {
              id: OATS,
              name: "Oats",
              brand: null,
              kcal_per_100g: 370,
              protein_g_per_100g: 13,
              carbs_g_per_100g: 60,
              fat_g_per_100g: 7,
              diet_tags: [],
              allergen_tags: [],
              source: "seed",
              external_code: null,
              owner: null,
            },
          ],
          next_cursor: null,
        } satisfies Schemas["FoodPage"]),
      ),
    );
    const user = userEvent.setup();
    renderApp("/today");
    await user.click(await screen.findByRole("button", { name: "Add food" }));
    await user.type(screen.getByLabelText("Search the food library"), "oat");
    await user.click(await screen.findByRole("button", { name: /Oats/ }));
    const grams = screen.getByLabelText("Grams");
    await user.clear(grams);
    await user.type(grams, "40");
    await user.click(screen.getByRole("button", { name: "Add to today" }));

    await waitFor(() =>
      expect(posts).toEqual([
        {
          date: DATE,
          planned_meal_id: null,
          status: "extra",
          slot: "snack",
          items: [{ food_id: OATS, grams: 40 }],
        },
      ]),
    );
    expect(await screen.findByText(/Oats 40 g/)).toBeInTheDocument();
  });

  it("imports an online product and adds it", async () => {
    const IMPORTED = "55555555-5555-4555-8555-555555555555";
    server.use(
      http.get(apiUrl("/foods"), () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.get(apiUrl("/foods/search"), () =>
        HttpResponse.json({
          available: true,
          unavailable_reason: null,
          message: null,
          items: [
            {
              code: "8410000810004",
              name: "Greek yogurt",
              brand: null,
              kcal_per_100g: 73,
              protein_g_per_100g: 9,
              carbs_g_per_100g: 3,
              fat_g_per_100g: 2,
              imported_food_id: null,
            },
          ],
        } satisfies Schemas["OffSearchResult"]),
      ),
      http.post(apiUrl("/foods/import"), () =>
        HttpResponse.json(
          {
            id: IMPORTED,
            name: "Greek yogurt",
            brand: null,
            kcal_per_100g: 73,
            protein_g_per_100g: 9,
            carbs_g_per_100g: 3,
            fat_g_per_100g: 2,
            diet_tags: [],
            allergen_tags: [],
            source: "openfoodfacts",
            external_code: "8410000810004",
            owner: null,
          },
          { status: 201 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp("/today");
    await user.click(await screen.findByRole("button", { name: "Add food" }));
    await user.type(screen.getByLabelText("Search the food library"), "yogurt");
    await user.click(screen.getByRole("button", { name: "Search online" }));
    const results = await screen.findByRole("list", { name: "Online results" });
    await user.click(
      within(results).getByRole("button", { name: /Greek yogurt/ }),
    );
    await user.click(
      await screen.findByRole("button", { name: "Add to today" }),
    );

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      planned_meal_id: null,
      status: "extra",
      items: [{ food_id: IMPORTED, grams: 100 }],
    });
  });

  it("explains when online search is unavailable", async () => {
    server.use(
      http.get(apiUrl("/foods"), () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.get(apiUrl("/foods/search"), () =>
        HttpResponse.json({
          available: false,
          unavailable_reason: "timeout",
          message:
            "Online food search is unavailable — use the library or create a custom food.",
          items: [],
        }),
      ),
    );
    const user = userEvent.setup();
    renderApp("/today");
    await user.click(await screen.findByRole("button", { name: "Add food" }));
    await user.type(screen.getByLabelText("Search the food library"), "yogurt");
    await user.click(screen.getByRole("button", { name: "Search online" }));
    expect(
      await screen.findByText(/Online food search is unavailable/),
    ).toBeInTheDocument();
  });

  it("creates a custom food and logs it", async () => {
    const CUSTOM = "66666666-6666-4666-8666-666666666666";
    server.use(
      http.post(apiUrl("/foods"), () =>
        HttpResponse.json(
          {
            id: CUSTOM,
            name: "My bar",
            brand: null,
            kcal_per_100g: 400,
            protein_g_per_100g: 20,
            carbs_g_per_100g: 40,
            fat_g_per_100g: 10,
            diet_tags: [],
            allergen_tags: [],
            source: "custom",
            external_code: null,
            owner: null,
          },
          { status: 201 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderApp("/today");
    await user.click(await screen.findByRole("button", { name: "Add food" }));
    await user.click(screen.getByRole("button", { name: "New custom food" }));
    await user.type(screen.getByLabelText("Food name"), "My bar");
    await user.type(screen.getByLabelText("kcal per 100 g"), "400");
    await user.type(screen.getByLabelText("Protein (g) per 100 g"), "20");
    await user.type(screen.getByLabelText("Carbs (g) per 100 g"), "40");
    await user.type(screen.getByLabelText("Fat (g) per 100 g"), "10");
    await user.click(screen.getByRole("button", { name: "Save food" }));
    await user.click(
      await screen.findByRole("button", { name: "Add to today" }),
    );

    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({
      status: "extra",
      items: [{ food_id: CUSTOM }],
    });
  });
});
