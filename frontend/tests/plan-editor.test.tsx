import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import type { components } from "../src/api/schema";
import { buildTrainingUpdate, draftFromPlan } from "../src/features/plan/trainingDraft";
import { meFixture, meOk, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { renderApp } from "./renderApp";

type Schemas = components["schemas"];

const ATHLETE = meFixture();
const COACH_REF: Schemas["UserRef"] = { id: "c0ac4000-0000-4000-8000-000000000001", display_name: "Coach Carla", role: "coach" };
const ATHLETE_REF: Schemas["UserRef"] = { id: ATHLETE.id, display_name: "Ana", role: "athlete" };

const BENCH: Schemas["ExerciseSummary"] = { id: "ex-bench", name: "Bench press", type: "strength", equipment: "barbell", muscle_group: "chest" };
const PLANK: Schemas["ExerciseSummary"] = { id: "ex-plank", name: "Plank", type: "timed", equipment: "bodyweight", muscle_group: "core" };

const macros = { kcal: 600, protein_g: 40, carbs_g: 60, fat_g: 20 };
const OATS = { id: "food-oats", name: "Oats", source: "seed" as const };

function planFixture(over: Partial<Schemas["Plan"]> = {}): Schemas["Plan"] {
  return {
    id: "plan-3",
    athlete_id: ATHLETE.id,
    version: 3,
    source: "generated",
    active: true,
    revision: 4,
    created_by: ATHLETE_REF,
    created_at: "2026-10-20T08:00:00Z",
    updated_at: "2026-10-20T08:00:00Z",
    warnings: [],
    training_days: [
      {
        id: "td-mon",
        weekday: "mon",
        name: "Push",
        order: 0,
        estimated_minutes: 50,
        planned_kcal: 300,
        edited_by: null,
        exercises: [
          { id: "pe-bench", exercise: BENCH, order: 0, sets: 3, reps_min: 8, reps_max: 10, target_weight_kg: 60, target_seconds: null, rest_seconds: 90, rule: "double", increment_kg: 2.5, deload_enabled: true, calibration_hint: null },
          { id: "pe-plank", exercise: PLANK, order: 1, sets: 3, reps_min: null, reps_max: null, target_weight_kg: null, target_seconds: 45, rest_seconds: 60, rule: "linear", increment_kg: 0, deload_enabled: false, calibration_hint: null },
        ],
      },
    ],
    meal_days: [
      {
        id: "md-mon",
        weekday: "mon",
        warning: null,
        edited_by: null,
        totals: macros,
        meals: [
          { id: "pm-oat", meal_key: "key-oat", slot: "breakfast", order: 0, meal: { id: "meal-oat", name: "Oat bowl", slots: ["breakfast"] }, portion_factor: 1, totals: macros, items: [{ ...macros, food: OATS, grams: 80 }] },
          { id: "pm-rice", meal_key: "key-rice", slot: "lunch", order: 1, meal: { id: "meal-rice", name: "Chicken rice", slots: ["lunch"] }, portion_factor: 1.5, totals: macros, items: [{ ...macros, food: { id: "food-rice", name: "Rice", source: "seed" }, grams: 150 }] },
        ],
      },
    ],
    ...over,
  };
}

const meal = (id: string, name: string, slot: Schemas["MealSlot"] = "lunch"): Schemas["Meal"] => ({
  id,
  name,
  slots: [slot],
  totals: macros,
  items: [{ ...macros, food: { id: "food-x", name: "Lentils", source: "seed" }, grams: 200 }],
  diet_tags: [],
  allergen_tags: [],
  is_custom: false,
  owner: null,
});

/** A fake plan API that records requests; `put` can return a problem instead of a plan. */
function fakePlan(options: { plan?: Schemas["Plan"]; put?: () => Response | undefined; versions?: Schemas["PlanVersionSummary"][] } = {}) {
  let current = options.plan ?? planFixture();
  const calls = { gets: 0, training: [] as Schemas["TrainingPlanUpdate"][], meals: [] as Schemas["MealPlanUpdate"][], regenerate: [] as unknown[] };
  server.use(
    meOk(),
    http.get(apiUrl("/athletes/:athleteId/plan"), () => {
      calls.gets += 1;
      return HttpResponse.json(current);
    }),
    http.put(apiUrl("/athletes/:athleteId/plan/training"), async ({ request }) => {
      const body = (await request.json()) as Schemas["TrainingPlanUpdate"];
      calls.training.push(body);
      const failure = options.put?.();
      if (failure) return failure;
      current = { ...current, revision: current.revision + 1, version: current.version + 1, source: "custom" };
      return HttpResponse.json(current);
    }),
    http.put(apiUrl("/athletes/:athleteId/plan/meals"), async ({ request }) => {
      const body = (await request.json()) as Schemas["MealPlanUpdate"];
      calls.meals.push(body);
      const failure = options.put?.();
      if (failure) return failure;
      current = { ...current, revision: current.revision + 1, version: current.version + 1, source: "custom" };
      return HttpResponse.json(current);
    }),
    http.post(apiUrl("/athletes/:athleteId/plan/regenerate"), async ({ request }) => {
      calls.regenerate.push(await request.json());
      current = { ...current, revision: current.revision + 1, version: current.version + 1, source: "generated" };
      return HttpResponse.json(current, { status: 201 });
    }),
    http.get(apiUrl("/athletes/:athleteId/plan/versions"), () => HttpResponse.json({ items: options.versions ?? [] })),
    http.get(apiUrl("/exercises"), ({ request }) => {
      const q = new URL(request.url).searchParams.get("q")?.toLowerCase() ?? "";
      const all = [BENCH, PLANK, { id: "ex-squat", name: "Squat", type: "strength" as const, equipment: "barbell" as const, muscle_group: "legs" as const }];
      const items = all.filter((e) => e.name.toLowerCase().includes(q)).map((e) => ({ ...e, met: 5, region: "upper", increment_kg: 2.5, allows_added_weight: true, is_custom: false, owner: null }));
      return HttpResponse.json({ items, next_cursor: null });
    }),
    http.get(apiUrl("/meals"), () =>
      HttpResponse.json({ items: [meal("meal-lentil", "Lentil stew")], next_cursor: null } satisfies Schemas["MealPage"]),
    ),
  );
  return {
    calls,
    setCurrent: (plan: Schemas["Plan"]) => {
      current = plan;
    },
  };
}

async function openPlan(user = userEvent.setup()) {
  renderApp("/plan");
  await screen.findByRole("heading", { name: "Plan", level: 1 });
  await screen.findByRole("heading", { name: "Mon: Push" });
  return user;
}

const field = (label: string | RegExp) => screen.getByLabelText(label) as HTMLInputElement;

describe("Plan editor: training", () => {
  it("saves edited targets with the current revision and keeps the ids of existing items", async () => {
    const { calls } = fakePlan();
    const user = await openPlan();
    const sets = screen.getAllByLabelText("Sets")[0]!;
    await user.clear(sets);
    await user.type(sets, "4");
    await user.clear(screen.getAllByLabelText("Max reps (optional)")[0]!);
    await user.type(screen.getAllByLabelText("Max reps (optional)")[0]!, "12");
    await user.clear(screen.getAllByLabelText("Weight (kg)")[0]!);
    await user.type(screen.getAllByLabelText("Weight (kg)")[0]!, "62.5");
    await user.selectOptions(screen.getAllByLabelText("Progression")[0]!, "manual");
    await user.click(screen.getAllByLabelText("Allow deload weeks")[0]!);
    await user.clear(screen.getAllByLabelText("Rest (seconds)")[0]!);
    await user.type(screen.getAllByLabelText("Rest (seconds)")[0]!, "120");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText(/Plan saved/)).toBeInTheDocument();
    expect(calls.training).toHaveLength(1);
    const day = calls.training[0]!;
    expect(day.revision).toBe(4);
    expect(day.training_days[0]).toMatchObject({ id: "td-mon", weekday: "mon", name: "Push" });
    expect(day.training_days[0]!.exercises[0]).toEqual({
      id: "pe-bench",
      exercise_id: "ex-bench",
      sets: 4,
      reps_min: 8,
      reps_max: 12,
      target_weight_kg: 62.5,
      target_seconds: null,
      rest_seconds: 120,
      rule: "manual",
      increment_kg: 2.5,
      deload_enabled: false,
    });
    // The timed exercise keeps seconds only.
    expect(day.training_days[0]!.exercises[1]).toMatchObject({ id: "pe-plank", reps_min: null, target_weight_kg: null, target_seconds: 45 });
  });

  it("adds a day and an exercise (without ids), reorders and removes", async () => {
    const { calls } = fakePlan();
    const user = await openPlan();
    // Reorder: move the plank above the bench press.
    await user.click(screen.getByRole("button", { name: "Move Plank up" }));
    // Remove nothing yet; add a squat to Monday.
    await user.type(screen.getAllByLabelText("Add exercise")[0]!, "squ");
    await user.click(await screen.findByRole("button", { name: "Add Squat" }));
    // Add a second day.
    await user.click(screen.getByRole("button", { name: "Add training day" }));
    expect(screen.getByRole("heading", { name: "Tue: New day" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove Bench press" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(calls.training).toHaveLength(1));
    const [mon, tue] = calls.training[0]!.training_days;
    expect(mon!.exercises.map((e) => e.exercise_id)).toEqual(["ex-plank", "ex-squat"]);
    expect(mon!.exercises[0]!.id).toBe("pe-plank");
    expect(mon!.exercises[1]).not.toHaveProperty("id");
    expect(tue).toMatchObject({ weekday: "tue", name: "New day", exercises: [] });
    expect(tue).not.toHaveProperty("id");
  });

  it("reorders and removes days", async () => {
    const { calls } = fakePlan();
    const user = await openPlan();
    await user.click(screen.getByRole("button", { name: "Add training day" }));
    await user.click(screen.getByRole("button", { name: "Move New day up" }));
    await user.click(screen.getByRole("button", { name: "Remove day Push" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.training).toHaveLength(1));
    expect(calls.training[0]!.training_days.map((d) => d.name)).toEqual(["New day"]);
  });

  it("shows imperial weights and sends kilograms", async () => {
    const { calls } = fakePlan();
    server.use(meOk(meFixture({ units: "imperial" })));
    const user = await openPlan();
    expect(screen.getAllByLabelText("Weight (lb)")[0]).toHaveValue("132.3");
    await user.clear(screen.getAllByLabelText("Weight (lb)")[0]!);
    await user.type(screen.getAllByLabelText("Weight (lb)")[0]!, "110.2");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.training).toHaveLength(1));
    expect(calls.training[0]!.training_days[0]!.exercises[0]!.target_weight_kg).toBe(50);
  });

  it("shows each 422 invalid_plan message next to its field", async () => {
    fakePlan({
      put: () =>
        problem(422, "invalid_plan", {
          detail: "Some plan fields are invalid.",
          errors: [
            { field: "training_days[0].exercises[0].reps_min", code: "required", message: "Set the target reps." },
            { field: "training_days[0].exercises[1].target_seconds", code: "required", message: "A timed exercise needs seconds." },
            { field: "training_days[0].exercises[1]", code: "invalid_targets", message: "A timed exercise has seconds only." },
          ],
        }),
    });
    const user = await openPlan();
    await user.clear(screen.getAllByLabelText("Sets")[0]!);
    await user.type(screen.getAllByLabelText("Sets")[0]!, "4");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    const reps = await screen.findByText("Set the target reps.");
    expect(field("Reps")).toHaveAttribute("aria-describedby", reps.id);
    expect(field("Reps")).toBeInvalid();
    const seconds = screen.getByText("A timed exercise needs seconds.");
    expect(field("Seconds")).toHaveAttribute("aria-describedby", seconds.id);
    expect(screen.getByText("A timed exercise has seconds only.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Some plan fields need fixing");
    // The draft is still there.
    expect(screen.getAllByLabelText("Sets")[0]).toHaveValue("4");
  });

  it("rejects unreadable numbers before calling the API", async () => {
    const { calls } = fakePlan();
    const user = await openPlan();
    await user.clear(screen.getAllByLabelText("Sets")[0]!);
    await user.type(screen.getAllByLabelText("Sets")[0]!, "x");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Sets must be a whole number from 1 to 10.")).toBeInTheDocument();
    expect(calls.training).toHaveLength(0);
  });

  it("builds a timed exercise with seconds only and fixed reps for strength", () => {
    const days = draftFromPlan(planFixture().training_days, "metric");
    days[0]!.exercises[0]!.repsMax = "";
    const { body } = buildTrainingUpdate(days, 4, "metric");
    expect(body!.training_days[0]!.exercises[0]).toMatchObject({ reps_min: 8, reps_max: 8 });
    expect(body!.training_days[0]!.exercises[1]).toMatchObject({ reps_min: null, reps_max: null, target_seconds: 45 });
  });
});

describe("Plan editor: meals", () => {
  async function openMeals() {
    const user = await openPlan();
    await user.click(screen.getByRole("tab", { name: "Meals" }));
    await screen.findByRole("heading", { name: "Monday", level: 3 });
    return user;
  }
  const saveMeals = (user: ReturnType<typeof userEvent.setup>) =>
    user.click(within(screen.getByRole("region", { name: "Meals" })).getByRole("button", { name: "Save changes" }));

  it("keeps the id of an edited meal and sends the portion", async () => {
    const { calls } = fakePlan();
    const user = await openMeals();
    const portions = screen.getAllByLabelText("Portion");
    await user.clear(portions[1]!);
    await user.type(portions[1]!, "2");
    await saveMeals(user);
    await waitFor(() => expect(calls.meals).toHaveLength(1));
    expect(calls.meals[0]).toEqual({
      revision: 4,
      meal_days: [
        {
          weekday: "mon",
          meals: [
            { id: "pm-oat", slot: "breakfast", meal_id: "meal-oat", portion_factor: 1 },
            { id: "pm-rice", slot: "lunch", meal_id: "meal-rice", portion_factor: 2 },
          ],
        },
      ],
    });
    expect(await screen.findByText(/Plan saved/)).toBeInTheDocument();
  });

  it("sends edited grams as final amounts with portion 1", async () => {
    const { calls } = fakePlan();
    const user = await openMeals();
    const grams = screen.getByLabelText("Grams of Rice");
    expect(grams).toHaveValue("150");
    await user.clear(grams);
    await user.type(grams, "120");
    await saveMeals(user);
    await waitFor(() => expect(calls.meals).toHaveLength(1));
    expect(calls.meals[0]!.meal_days[0]!.meals[1]).toEqual({
      id: "pm-rice",
      slot: "lunch",
      meal_id: "meal-rice",
      portion_factor: 1,
      items: [{ food_id: "food-rice", grams: 120 }],
    });
  });

  it("replaces a meal but keeps its id, adds a new one without id and removes one", async () => {
    const { calls } = fakePlan();
    const user = await openMeals();
    await user.click(screen.getByRole("button", { name: "Replace Oat bowl" }));
    await user.click(await screen.findByRole("button", { name: "Choose Lentil stew" }));
    expect(screen.queryByText("Oat bowl")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove Chicken rice" }));
    await user.click(screen.getByRole("button", { name: "Add meal on Monday" }));
    await user.click(await screen.findByRole("button", { name: "Choose Lentil stew" }));
    await saveMeals(user);
    await waitFor(() => expect(calls.meals).toHaveLength(1));
    const meals = calls.meals[0]!.meal_days[0]!.meals;
    expect(meals).toHaveLength(2);
    expect(meals[0]).toMatchObject({ id: "pm-oat", meal_id: "meal-lentil", slot: "breakfast" });
    expect(meals[1]).toMatchObject({ meal_id: "meal-lentil" });
    expect(meals[1]).not.toHaveProperty("id");
  });

  it("creates a custom meal from a food and uses it", async () => {
    const { calls } = fakePlan();
    let created: Schemas["MealInput"] | null = null;
    server.use(
      http.get(apiUrl("/foods"), () =>
        HttpResponse.json({
          items: [{ id: "food-oats", name: "Oats", brand: null, kcal_per_100g: 370, protein_g_per_100g: 13, carbs_g_per_100g: 60, fat_g_per_100g: 7, diet_tags: [], allergen_tags: [], source: "seed", external_code: null, owner: null }],
          next_cursor: null,
        } satisfies Schemas["FoodPage"]),
      ),
      http.post(apiUrl("/meals"), async ({ request }) => {
        created = (await request.json()) as Schemas["MealInput"];
        return HttpResponse.json({ ...meal("meal-mine", created.name), is_custom: true }, { status: 201 });
      }),
    );
    const user = await openMeals();
    await user.click(screen.getByRole("button", { name: "Add meal on Monday" }));
    await user.click(screen.getByRole("button", { name: "Create custom meal" }));
    await user.type(screen.getByLabelText("Meal name"), "My bowl");
    await user.type(screen.getByLabelText("Search foods to add"), "oa");
    await user.click(await screen.findByRole("button", { name: "Add Oats" }));
    await user.click(screen.getByRole("button", { name: "Create meal" }));
    await waitFor(() => expect(created).toEqual({ name: "My bowl", slots: ["lunch"], items: [{ food_id: "food-oats", grams: 100 }] }));
    expect(await screen.findByRole("heading", { name: "My bowl" })).toBeInTheDocument();
    await saveMeals(user);
    await waitFor(() => expect(calls.meals).toHaveLength(1));
    expect(calls.meals[0]!.meal_days[0]!.meals[2]).toMatchObject({ meal_id: "meal-mine", slot: "lunch" });
  });

  it("shows invalid_plan messages next to the meal field", async () => {
    fakePlan({
      put: () =>
        problem(422, "invalid_plan", {
          errors: [{ field: "meal_days[0].meals[1].portion_factor", code: "out_of_range", message: "Portion is too large." }],
        }),
    });
    const user = await openMeals();
    await user.clear(screen.getAllByLabelText("Portion")[1]!);
    await user.type(screen.getAllByLabelText("Portion")[1]!, "2");
    await saveMeals(user);
    const message = await screen.findByText("Portion is too large.");
    expect(screen.getAllByLabelText("Portion")[1]).toHaveAttribute("aria-describedby", expect.stringContaining(message.id));
  });
});

describe("Plan editor: concurrent edits", () => {
  it("shows a reload message on 409, refetches and keeps the draft", async () => {
    let conflict = true;
    const { calls, setCurrent } = fakePlan({ put: () => (conflict ? problem(409, "plan_revision_conflict", { detail: "The plan changed." }) : undefined) });
    const user = await openPlan();
    const getsBefore = calls.gets;
    await user.clear(screen.getAllByLabelText("Sets")[0]!);
    await user.type(screen.getAllByLabelText("Sets")[0]!, "5");
    setCurrent(planFixture({ revision: 7, version: 5 }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("The plan changed");
    expect(alert).toHaveTextContent("kept your draft");
    await waitFor(() => expect(calls.gets).toBeGreaterThan(getsBefore));
    expect(screen.getAllByLabelText("Sets")[0]).toHaveValue("5");

    // Saving again goes against the latest revision.
    conflict = false;
    await user.click(screen.getByRole("button", { name: "Save over the latest plan" }));
    await waitFor(() => expect(calls.training).toHaveLength(2));
    expect(calls.training[1]!.revision).toBe(7);
    await waitFor(() => expect(screen.queryByText("The plan changed")).not.toBeInTheDocument());
  });

  it("drops the draft only when the user asks to reload", async () => {
    const { setCurrent } = fakePlan({ put: () => problem(409, "plan_revision_conflict") });
    const user = await openPlan();
    await user.clear(screen.getAllByLabelText("Sets")[0]!);
    await user.type(screen.getAllByLabelText("Sets")[0]!, "5");
    setCurrent(planFixture({ revision: 7, training_days: [{ ...planFixture().training_days[0]!, name: "Pull" }] }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await screen.findByText("The plan changed");
    await user.click(screen.getByRole("button", { name: "Reload the latest plan and drop my draft" }));
    expect(await screen.findByRole("heading", { name: "Mon: Pull" })).toBeInTheDocument();
    expect(screen.getAllByLabelText("Sets")[0]).toHaveValue("3");
  });
});

describe("Plan editor: edited-by label", () => {
  it("labels training days and meal days that a coach edited", async () => {
    const base = planFixture();
    fakePlan({
      plan: {
        ...base,
        training_days: [{ ...base.training_days[0]!, edited_by: COACH_REF }],
        meal_days: [{ ...base.meal_days[0]!, edited_by: COACH_REF }],
      },
    });
    const user = await openPlan();
    const training = screen.getByRole("heading", { name: "Mon: Push" }).closest("li")!;
    expect(within(training).getByText("Edited by Coach Carla")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Meals" }));
    const meals = (await screen.findByRole("heading", { name: "Monday", level: 3 })).closest("li")!;
    expect(within(meals).getByText("Edited by Coach Carla")).toBeInTheDocument();
  });

  it("shows no label when nobody edited the day", async () => {
    fakePlan();
    await openPlan();
    expect(screen.queryByText(/Edited by/)).not.toBeInTheDocument();
  });
});

describe("Plan editor: regenerate", () => {
  it("asks first, explains the consequences and calls the API only on confirm", async () => {
    const { calls } = fakePlan();
    const user = await openPlan();
    await user.click(screen.getByRole("button", { name: "Regenerate plan" }));
    const dialog = screen.getByRole("alertdialog", { name: "Regenerate your plan?" });
    expect(dialog).toHaveTextContent("Previous versions stay readable");
    expect(dialog).toHaveTextContent("extra meals");
    expect(calls.regenerate).toHaveLength(0);

    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(calls.regenerate).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "Regenerate plan" }));
    await user.click(screen.getByRole("button", { name: "Yes, regenerate" }));
    expect(await screen.findByText("Plan regenerated.")).toBeInTheDocument();
    expect(calls.regenerate).toEqual([{ scope: "all" }]);
  });
});

describe("Plan editor: version history", () => {
  const versions: Schemas["PlanVersionSummary"][] = [
    { id: "plan-3", version: 3, source: "custom", active: true, created_by: COACH_REF, created_at: "2026-10-25T10:30:00Z" },
    { id: "plan-2", version: 2, source: "generated", active: false, created_by: ATHLETE_REF, created_at: "2026-10-20T08:00:00Z" },
  ];

  it("lists versions with date, source and author role and opens one read-only", async () => {
    fakePlan({ versions });
    const old = planFixture({ id: "plan-2", version: 2, active: false, source: "generated" });
    server.use(http.get(apiUrl("/athletes/:athleteId/plan/versions/:version"), () => HttpResponse.json(old)));
    const user = await openPlan();
    await user.click(screen.getByRole("tab", { name: "History" }));

    const items = await screen.findAllByRole("listitem");
    const v3 = items.find((li) => li.textContent?.includes("Version 3"))!;
    expect(v3).toHaveTextContent("Custom");
    expect(v3).toHaveTextContent("Coach");
    expect(v3).toHaveTextContent("Active");
    expect(v3).toHaveTextContent("Oct 25, 2026, 11:30 AM");
    const v2 = items.find((li) => li.textContent?.includes("Version 2"))!;
    expect(v2).toHaveTextContent("Generated");
    expect(v2).toHaveTextContent("Athlete");

    await user.click(screen.getByRole("button", { name: "Open version 2" }));
    expect(await screen.findByText(/Read-only/)).toBeInTheDocument();
    const view = screen.getByRole("region", { name: "Version 2" });
    expect(within(view).getByText(/Bench press/)).toBeInTheDocument();
    expect(within(view).queryAllByRole("textbox")).toHaveLength(0);
    expect(within(view).queryByRole("button", { name: /save|remove|add/i })).not.toBeInTheDocument();
  });
});

describe("Plan editor: viewer", () => {
  it("hides the editor for a viewer who is not the athlete", async () => {
    let planRequests = 0;
    server.use(
      meOk(meFixture({ role: "coach" })),
      http.get(apiUrl("/athletes/:athleteId/plan"), () => {
        planRequests += 1;
        return HttpResponse.json(planFixture());
      }),
    );
    renderApp("/plan");
    expect(await screen.findByText(/Plans are edited from a client's page/)).toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save changes" })).not.toBeInTheDocument();
    expect(planRequests).toBe(0);
  });

  it("is reachable from the calendar navigation", async () => {
    fakePlan();
    const user = userEvent.setup();
    renderApp("/week");
    await user.click(await screen.findByRole("link", { name: "Plan" }));
    expect(await screen.findByRole("heading", { name: "Plan", level: 1 })).toBeInTheDocument();
  });
});

describe("Plan editor: duplicate a day (D87)", () => {
  const thursday = (): Schemas["TrainingDay"] => ({
    ...planFixture().training_days[0]!,
    id: "td-thu",
    weekday: "thu",
    name: "Legs",
    exercises: [{ ...planFixture().training_days[0]!.exercises[0]!, id: "pe-thu", exercise: { ...BENCH, id: "ex-squat", name: "Squat" } }],
  });
  const training = () => within(screen.getByRole("region", { name: "Training" }));
  const mealsRegion = () => within(screen.getByRole("region", { name: "Meals" }));
  async function openMeals() {
    const user = await openPlan();
    await user.click(screen.getByRole("tab", { name: "Meals" }));
    await screen.findByRole("heading", { name: "Monday", level: 3 });
    return user;
  }

  it("copies a training day to an empty weekday, with the same targets and no ids, leaving Monday as it is", async () => {
    const { calls } = fakePlan();
    const user = await openPlan();
    await user.click(training().getByRole("button", { name: "Duplicate Monday" }));
    await user.selectOptions(training().getByLabelText("Copy to"), "thu");
    await user.click(training().getByRole("button", { name: "Copy" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Thu: Push" })).toBeInTheDocument();
    await user.click(training().getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.training).toHaveLength(1));
    const [mon, thu] = calls.training[0]!.training_days;
    expect(calls.training[0]!.training_days).toHaveLength(2);
    expect(mon).toMatchObject({ id: "td-mon", weekday: "mon", name: "Push" });
    expect(mon!.exercises.map((e) => e.id)).toEqual(["pe-bench", "pe-plank"]);
    expect(thu).toMatchObject({ weekday: "thu", name: "Push" });
    expect(thu).not.toHaveProperty("id");
    expect(thu!.exercises.map((e) => e.id)).toEqual([undefined, undefined]);
    const targets = (e: Schemas["PlannedExerciseInput"]) => ({ ...e, id: undefined });
    expect(thu!.exercises.map(targets)).toEqual(mon!.exercises.map(targets));
    expect(thu!.exercises[0]).toMatchObject({ sets: 3, reps_min: 8, reps_max: 10, target_weight_kg: 60, rest_seconds: 90, rule: "double", increment_kg: 2.5 });
  });

  it("asks before replacing a day with content, and cancelling changes nothing", async () => {
    const base = planFixture();
    const { calls } = fakePlan({ plan: { ...base, training_days: [...base.training_days, thursday()] } });
    const user = await openPlan();
    await user.click(training().getByRole("button", { name: "Duplicate Monday" }));
    await user.selectOptions(training().getByLabelText("Copy to"), "thu");
    await user.click(training().getByRole("button", { name: "Copy" }));
    const dialog = screen.getByRole("alertdialog", { name: "Replace Thursday?" });
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Thu: Legs" })).toBeInTheDocument();
    expect(training().getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(calls.training).toHaveLength(0);

    await user.click(training().getByRole("button", { name: "Duplicate Monday" }));
    await user.selectOptions(training().getByLabelText("Copy to"), "thu");
    await user.click(training().getByRole("button", { name: "Copy" }));
    await user.click(screen.getByRole("button", { name: "Yes, replace Thursday" }));
    expect(await screen.findByRole("heading", { name: "Thu: Push" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Thu: Legs" })).not.toBeInTheDocument();
    await user.click(training().getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.training).toHaveLength(1));
    const days = calls.training[0]!.training_days;
    expect(days).toHaveLength(2);
    expect(days[1]).toMatchObject({ id: "td-thu", weekday: "thu", name: "Push" });
    expect(days[1]!.exercises.every((e) => e.id === undefined)).toBe(true);
  });

  it("copies the meals of a day without ids, so the copies get new meal keys", async () => {
    const { calls } = fakePlan();
    const user = await openMeals();
    await user.click(mealsRegion().getByRole("button", { name: "Duplicate Monday" }));
    await user.selectOptions(mealsRegion().getByLabelText("Copy to"), "wed");
    await user.click(mealsRegion().getByRole("button", { name: "Copy" }));
    await user.click(mealsRegion().getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.meals).toHaveLength(1));
    const [mon, wed] = calls.meals[0]!.meal_days;
    expect(mon).toMatchObject({ weekday: "mon" });
    expect(mon!.meals.map((m) => m.id)).toEqual(["pm-oat", "pm-rice"]);
    expect(wed).toMatchObject({ weekday: "wed" });
    expect(wed!.meals).toEqual([
      { slot: "breakfast", meal_id: "meal-oat", portion_factor: 1 },
      { slot: "lunch", meal_id: "meal-rice", portion_factor: 1.5 },
    ]);
  });

  it("confirms before replacing a meal day with meals, and cancelling keeps it", async () => {
    const base = planFixture();
    const tue = { ...base.meal_days[0]!, id: "md-tue", weekday: "tue" as const, meals: [{ ...base.meal_days[0]!.meals[0]!, id: "pm-tue" }] };
    const { calls } = fakePlan({ plan: { ...base, meal_days: [...base.meal_days, tue] } });
    const user = await openMeals();
    await user.click(mealsRegion().getByRole("button", { name: "Duplicate Monday" }));
    await user.click(mealsRegion().getByRole("button", { name: "Copy" })); // default target is Tuesday
    await user.click(within(screen.getByRole("alertdialog", { name: "Replace Tuesday?" })).getByRole("button", { name: "Cancel" }));
    expect(mealsRegion().getByRole("button", { name: "Save changes" })).toBeDisabled();
    expect(calls.meals).toHaveLength(0);

    await user.click(mealsRegion().getByRole("button", { name: "Duplicate Monday" }));
    await user.click(mealsRegion().getByRole("button", { name: "Copy" }));
    await user.click(screen.getByRole("button", { name: "Yes, replace Tuesday" }));
    await user.click(mealsRegion().getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.meals).toHaveLength(1));
    const tueSent = calls.meals[0]!.meal_days.find((d) => d.weekday === "tue")!;
    expect(tueSent.meals).toHaveLength(2);
    expect(tueSent.meals.every((m) => m.id === undefined)).toBe(true);
  });
});

describe("Plan editor: swap a meal (D86)", () => {
  const mealsRegion = () => within(screen.getByRole("region", { name: "Meals" }));
  const swapList = (alternatives: Schemas["MealSwap"][]): Schemas["MealSwapList"] => ({ meal_key: "key-rice", alternatives, reason: "ok" });
  const toast: Schemas["MealSwap"] = {
    meal_id: "meal-toast",
    name: "Eggs on toast",
    portion_factor: 1.2,
    items: [{ ...macros, food: { id: "food-egg", name: "Egg", source: "seed" }, grams: 120 }],
    totals: { ...macros, kcal: 590 },
  };
  async function openMeals() {
    const user = await openPlan();
    await user.click(screen.getByRole("tab", { name: "Meals" }));
    await screen.findByRole("heading", { name: "Monday", level: 3 });
    return user;
  }
  function swaps(list: Schemas["MealSwapList"]) {
    const asked: string[] = [];
    server.use(
      http.get(apiUrl("/athletes/:athleteId/plan/meals/:mealKey/swaps"), ({ params }) => {
        asked.push(String(params.mealKey));
        return HttpResponse.json(list);
      }),
    );
    return asked;
  }

  it("lists the alternatives of a saved meal and saves the chosen one as a new meal", async () => {
    const { calls } = fakePlan();
    const asked = swaps(swapList([toast]));
    const user = await openMeals();
    await user.click(mealsRegion().getByRole("button", { name: "Swap Chicken rice" }));
    expect(await screen.findByText("Eggs on toast")).toBeInTheDocument();
    expect(screen.getByText("590 kcal at 1.2x")).toBeInTheDocument();
    expect(asked).toEqual(["key-rice"]);

    await user.click(screen.getByRole("button", { name: "Use Eggs on toast" }));
    await waitFor(() => expect(calls.meals).toHaveLength(1));
    const [mon] = calls.meals[0]!.meal_days;
    expect(mon!.meals).toEqual([
      { id: "pm-oat", slot: "breakfast", meal_id: "meal-oat", portion_factor: 1 },
      { slot: "lunch", meal_id: "meal-toast", portion_factor: 1.2 }, // no id: new meal_key, no logs (D73)
    ]);
  });

  it("says so when there is no alternative and saves nothing", async () => {
    const { calls } = fakePlan();
    swaps(swapList([]));
    const user = await openMeals();
    await user.click(mealsRegion().getByRole("button", { name: "Swap Oat bowl" }));
    expect(await screen.findByText(/No similar meals fit/)).toBeInTheDocument();
    expect(calls.meals).toHaveLength(0);
  });

  it("waits for a clean draft: unsaved changes disable Swap", async () => {
    fakePlan();
    swaps(swapList([toast]));
    const user = await openMeals();
    await user.click(mealsRegion().getByRole("button", { name: "Remove Oat bowl" }));
    expect(mealsRegion().getByRole("button", { name: "Swap Chicken rice" })).toBeDisabled();
    expect(mealsRegion().getAllByText("Save your changes to see swaps.").length).toBeGreaterThan(0);
  });

  it("shows an error when the alternatives cannot be loaded", async () => {
    fakePlan();
    server.use(http.get(apiUrl("/athletes/:athleteId/plan/meals/:mealKey/swaps"), () => problem(422, "past_day")));
    const user = await openMeals();
    await user.click(mealsRegion().getByRole("button", { name: "Swap Oat bowl" }));
    expect(await screen.findByText("Couldn't load alternatives. Try again.")).toBeInTheDocument();
  });
});
