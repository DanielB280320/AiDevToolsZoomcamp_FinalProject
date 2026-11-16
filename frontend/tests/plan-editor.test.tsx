import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";

import type { components } from "../src/api/schema";
import { buildTrainingUpdate, draftFromPlan } from "../src/features/plan/trainingDraft";
import { meFixture, meOk, problem } from "./mocks/fixtures";
import { apiUrl } from "./mocks/handlers";
import { server } from "./mocks/server";
import { PLAN_GOAL } from "./mocks/planGoal";
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
    plan_no: 1,
    source: "generated",
    active: true,
    revision: 4,
    name: null,
    start_date: null,
    ...PLAN_GOAL,
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
function fakePlan(
  options: {
    plan?: Schemas["Plan"];
    put?: () => Response | undefined;
    post?: () => Response | undefined;
    versions?: Schemas["PlanVersionSummary"][];
    plans?: Schemas["PlanSummary"][];
  } = {},
) {
  let current = options.plan ?? planFixture();
  const calls = {
    gets: 0,
    training: [] as Schemas["TrainingPlanUpdate"][],
    meals: [] as Schemas["MealPlanUpdate"][],
    create: [] as Schemas["CreatePlanRequest"][],
  };
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
      current = {
        ...current,
        revision: current.revision + 1,
        version: current.version + 1,
        source: "custom",
        ...(body.training_goal ? { training_goal: body.training_goal } : {}),
      };
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
    http.post(apiUrl("/athletes/:athleteId/plan"), async ({ request }) => {
      const body = (await request.json()) as Schemas["CreatePlanRequest"];
      calls.create.push(body);
      const failure = options.post?.();
      if (failure) return failure;
      current = {
        ...current,
        revision: current.revision + 1,
        version: current.version + 1,
        source: body.start_from === "generated" ? "generated" : "custom",
        name: body.name,
        start_date: body.start_date ?? null,
        training_goal: body.training_goal ?? "hypertrophy",
        ...(body.start_from === "generated"
          ? {}
          : { training_days: [], meal_days: [] }),
      };
      return HttpResponse.json(current, { status: 201 });
    }),
    http.get(apiUrl("/athletes/:athleteId/plan/versions"), ({ request }) => {
      const planNo = Number(new URL(request.url).searchParams.get("plan_no"));
      return HttpResponse.json({
        items: (options.versions ?? []).filter((v) => !planNo || v.plan_no === planNo),
      });
    }),
    http.get(apiUrl("/athletes/:athleteId/plans"), () =>
      HttpResponse.json({ items: options.plans ?? [] }),
    ),
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

/** Days are collapsed by default (D105): open the one whose heading matches. */
async function openDay(user: ReturnType<typeof userEvent.setup>, name: RegExp) {
  const heading = await screen.findByRole("heading", { name });
  const toggle = within(heading).getByRole("button");
  if (toggle.getAttribute("aria-expanded") === "false")
    await user.click(toggle);
}

async function openPlan(user = userEvent.setup()) {
  renderApp("/plan");
  await screen.findByRole("heading", { name: "Plan", level: 1 });
  await openDay(user, /^Mon: Push/);
  return user;
}

/** Opens the "N foods, X kcal" disclosure of a meal (closed by default) and returns its button. */
async function openFoods(user: ReturnType<typeof userEvent.setup>, meal: string) {
  const toggle = screen.getByRole("button", { name: new RegExp(`^Foods of ${meal}:`) });
  if (toggle.getAttribute("aria-expanded") === "false") await user.click(toggle);
  return toggle;
}

const field = (label: string | RegExp) => screen.getByLabelText(label) as HTMLInputElement;

describe("Plan editor: training", () => {
  it("saves edited targets with the current revision and keeps the ids of existing items", async () => {
    const { calls } = fakePlan();
    const user = await openPlan();
    const sets = screen.getAllByLabelText("Sets")[0]!;
    await user.clear(sets);
    await user.type(sets, "4");
    await user.clear(screen.getAllByLabelText("Max reps")[0]!);
    await user.type(screen.getAllByLabelText("Max reps")[0]!, "12");
    await user.clear(screen.getAllByLabelText("Weight (kg)")[0]!);
    await user.type(screen.getAllByLabelText("Weight (kg)")[0]!, "62.5");
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
      rule: "double", // no longer edited in the app: sent back as it was (D107)
      increment_kg: 2.5,
      deload_enabled: true,
    });
    expect(day).not.toHaveProperty("training_goal"); // unchanged goal is not sent
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
    expect(
      screen.getByRole("heading", { name: /^Tue: New day(?: .*)?$/ }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Remove Bench press" }),
    );
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
    expect(field("Reps (min)")).toHaveAttribute("aria-describedby", expect.stringContaining(reps.id));
    expect(field("Reps (min)")).toBeInvalid();
    const seconds = screen.getByText("A timed exercise needs seconds.");
    expect(field("Seconds")).toHaveAttribute("aria-describedby", expect.stringContaining(seconds.id));
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

describe("Plan editor: compact exercise rows", () => {
  it("shows each exercise as one row of labelled fields and the three hints once per day", async () => {
    fakePlan();
    await openPlan();
    const rows = screen.getAllByTestId("exercise-fields");
    expect(rows).toHaveLength(2);
    for (const label of ["Sets", "Reps (min)", "Max reps", "Weight (kg)", "Rest (seconds)"]) {
      expect(within(rows[0]!).getByLabelText(label)).toBeInTheDocument();
    }
    // A timed exercise has sets, seconds and rest.
    for (const label of ["Sets", "Seconds", "Rest (seconds)"]) {
      expect(within(rows[1]!).getByLabelText(label)).toBeInTheDocument();
    }
    const hint = screen.getByTestId("day-hint");
    expect(screen.getAllByTestId("day-hint")).toHaveLength(1);
    expect(hint).toHaveTextContent(/Leave max reps empty for a fixed number of reps/);
    expect(hint).toHaveTextContent(/Leave weight empty to choose it at the first session/);
    expect(field("Reps (min)")).toHaveAccessibleDescription(/Recommended for this goal/);
    expect(screen.queryByText("Top of the range. Leave empty for a fixed number of reps.")).not.toBeInTheDocument();
  });
});

describe("Plan editor: meals", () => {
  async function openMeals() {
    const user = await openPlan();
    await user.click(screen.getByRole("tab", { name: "Meals" }));
    await openDay(user, /^Monday/);
    return user;
  }
  const saveMeals = (user: ReturnType<typeof userEvent.setup>) =>
    user.click(within(screen.getByRole("region", { name: "Meals" })).getByRole("button", { name: "Save changes" }));

  it("folds foods behind an \"N foods, X kcal\" disclosure: closed by default, opens to foods, grams, Replace and Swap", async () => {
    fakePlan();
    const user = await openMeals();
    const toggle = screen.getByRole("button", { name: "Foods of Chicken rice: 1 food, 600 kcal" });
    expect(toggle).toHaveTextContent("1 food, 600 kcal");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // One row per meal: name, slot, portion and remove are visible; foods and actions are not.
    expect(screen.getByRole("button", { name: "Remove Chicken rice" })).toBeVisible();
    expect(screen.getAllByLabelText("Meal")[1]).toHaveValue("lunch");
    expect(screen.queryByRole("button", { name: "Replace Chicken rice" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Swap Chicken rice" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Grams of Rice")).not.toBeVisible();

    // The keyboard opens it too.
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAttribute("aria-controls", expect.stringMatching(/-content$/));
    expect(screen.getByLabelText("Grams of Rice")).toBeVisible();
    expect(screen.getByLabelText("Grams of Rice")).toHaveValue("150");
    expect(screen.getByRole("button", { name: "Replace Chicken rice" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Swap Chicken rice" })).toBeVisible();
    // The Oat bowl stays closed.
    expect(screen.getByRole("button", { name: /^Foods of Oat bowl:/ })).toHaveAttribute("aria-expanded", "false");

    await user.keyboard(" ");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("opens the foods of a meal whose grams have an error", async () => {
    fakePlan();
    const user = await openMeals();
    await openFoods(user, "Chicken rice");
    await user.clear(screen.getByLabelText("Grams of Rice"));
    await user.type(screen.getByLabelText("Grams of Rice"), "0");
    await user.click(screen.getByRole("button", { name: /^Foods of Chicken rice:/ })); // fold it
    await saveMeals(user);
    expect(await screen.findByRole("button", { name: /^Foods of Chicken rice:/ })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Grams of Rice")).toBeInvalid();
  });

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
    await openFoods(user, "Chicken rice");
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
    await openFoods(user, "Oat bowl");
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
    await user.click(
      screen.getByRole("button", {
        name: "Reload the latest plan and drop my draft",
      }),
    );
    expect(
      await screen.findByRole("heading", { name: /^Mon: Pull(?: .*)?$/ }),
    ).toBeInTheDocument();
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
    const training = screen
      .getByRole("heading", { name: /^Mon: Push(?: .*)?$/ })
      .closest("li")!;
    expect(
      within(training).getByText("Edited by Coach Carla"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Meals" }));
    const meals = (
      await screen.findByRole("heading", { name: /^Monday(?: .*)?$/, level: 3 })
    ).closest("li")!;
    expect(
      within(meals).getByText("Edited by Coach Carla"),
    ).toBeInTheDocument();
  });

  it("shows no label when nobody edited the day", async () => {
    fakePlan();
    await openPlan();
    expect(screen.queryByText(/Edited by/)).not.toBeInTheDocument();
  });
});

const TODAY = new Intl.DateTimeFormat("en-CA", {
  timeZone: ATHLETE.timezone,
}).format(new Date());
const shiftDay = (iso: string, days: number) =>
  new Date(Date.parse(`${iso}T00:00:00Z`) + days * 86_400_000)
    .toISOString()
    .slice(0, 10);

describe("Plan editor: new plan (D105)", () => {
  const open = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole("button", { name: "New plan" }));
    return screen.getByRole("form", { name: "New plan" });
  };

  it("replaces Regenerate: an empty plan by default, today as the start date, with the consequences", async () => {
    const { calls } = fakePlan();
    const user = await openPlan();
    expect(
      screen.queryByRole("button", { name: "Regenerate plan" }),
    ).not.toBeInTheDocument();
    const form = await open(user);
    expect(within(form).getByLabelText("Start date")).toHaveValue(TODAY);
    expect(within(form).getByLabelText("Start date")).toHaveAttribute(
      "max",
      TODAY,
    );
    expect(
      within(form).getByRole("radio", { name: /Empty plan/ }),
    ).toBeChecked();
    expect(
      within(form).queryByLabelText("What to generate"),
    ).not.toBeInTheDocument();
    expect(form).toHaveTextContent("replaces the current plan from today");
    expect(form).toHaveTextContent("stays in History");
    expect(
      within(form).queryByText(/unsaved changes will be lost/),
    ).not.toBeInTheDocument();

    await user.type(within(form).getByLabelText("Plan name"), "  Summer cut ");
    await user.click(within(form).getByRole("button", { name: "Create plan" }));
    expect(
      await screen.findByText("New plan created: Summer cut."),
    ).toBeInTheDocument();
    expect(calls.create).toEqual([
      {
        name: "Summer cut",
        start_date: TODAY,
        start_from: "empty",
        scope: "all",
        training_goal: "cutting", // the default derived from the profile goal
      },
    ]);
    // The editor reloads with the new plan: the summary shows its name, and the days are gone.
    expect(
      within(screen.getByTestId("plan-summary")).getByText("Summer cut"),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("No training days yet."),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("form", { name: "New plan" }),
    ).not.toBeInTheDocument();
  });

  it("generates from the profile with the chosen scope and a past start date", async () => {
    const { calls } = fakePlan();
    const user = await openPlan();
    const form = await open(user);
    await user.type(within(form).getByLabelText("Plan name"), "Base");
    fireEvent.change(within(form).getByLabelText("Start date"), {
      target: { value: "2026-09-01" },
    });
    await user.click(
      within(form).getByRole("radio", { name: /Generated from my profile/ }),
    );
    await user.selectOptions(
      within(form).getByLabelText("What to generate"),
      "Training only",
    );
    await user.click(within(form).getByRole("button", { name: "Create plan" }));
    expect(
      await screen.findByText("New plan created: Base."),
    ).toBeInTheDocument();
    expect(calls.create).toEqual([
      {
        name: "Base",
        start_date: "2026-09-01",
        start_from: "generated",
        scope: "training",
        training_goal: "cutting",
      },
    ]);
  });

  it("validates the name and the start date before calling the API, and warns about unsaved edits", async () => {
    const { calls } = fakePlan();
    const user = await openPlan();
    await user.clear(screen.getAllByLabelText("Sets")[0]!);
    await user.type(screen.getAllByLabelText("Sets")[0]!, "5");
    const form = await open(user);
    expect(form).toHaveTextContent("Your unsaved changes will be lost.");
    await user.click(within(form).getByRole("button", { name: "Create plan" }));
    const name = within(form).getByLabelText("Plan name");
    expect(name).toBeInvalid();
    expect(
      within(form).getByText("Enter a name for the plan."),
    ).toHaveAttribute("id", `${name.id}-error`);
    await user.type(name, "x".repeat(61));
    fireEvent.change(within(form).getByLabelText("Start date"), {
      target: { value: shiftDay(TODAY, 1) },
    });
    await user.click(within(form).getByRole("button", { name: "Create plan" }));
    expect(
      within(form).getByText("Use at most 60 characters."),
    ).toBeInTheDocument();
    expect(
      within(form).getByText("The start date can't be in the future."),
    ).toBeInTheDocument();
    expect(calls.create).toHaveLength(0);
  });

  it("shows a field error from the API on its field and keeps the form", async () => {
    fakePlan({
      post: () =>
        problem(422, "invalid_plan", {
          detail: "Some plan fields are invalid.",
          errors: [
            {
              field: "start_date",
              code: "in_the_future",
              message: "The start date cannot be in the future.",
            },
          ],
        }),
    });
    const user = await openPlan();
    const form = await open(user);
    await user.type(within(form).getByLabelText("Plan name"), "Later");
    await user.click(within(form).getByRole("button", { name: "Create plan" }));
    const message = await within(form).findByText(
      "The start date cannot be in the future.",
    );
    expect(within(form).getByLabelText("Start date")).toHaveAttribute(
      "aria-describedby",
      expect.stringContaining(message.id),
    );
    expect(within(form).getByLabelText("Plan name")).toHaveValue("Later");
  });
});

describe("Plan editor: collapsible days (D105)", () => {
  it("starts collapsed, opens and closes with aria-expanded, and keeps the draft while collapsed", async () => {
    fakePlan();
    const user = userEvent.setup();
    renderApp("/plan");
    const heading = await screen.findByRole("heading", { name: /^Mon: Push/ });
    expect(heading).toHaveTextContent("2 exercises");
    const toggle = within(heading).getByRole("button");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(
      document.getElementById(toggle.getAttribute("aria-controls")!),
    ).toHaveAttribute("hidden");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await user.clear(screen.getAllByLabelText("Sets")[0]!);
    await user.type(screen.getAllByLabelText("Sets")[0]!, "6");
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    expect(screen.getAllByLabelText("Sets")[0]).toHaveValue("6");
  });

  it("opens a new day, and a day with an error when saving", async () => {
    fakePlan();
    const user = await openPlan();
    await user.click(screen.getByRole("button", { name: "Add training day" }));
    const added = screen.getByRole("heading", { name: /^Tue: New day/ });
    expect(added).toHaveTextContent("no exercises");
    expect(within(added).getByRole("button")).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    // An unreadable value in a collapsed day opens it on save.
    await user.clear(screen.getAllByLabelText("Sets")[0]!);
    await user.type(screen.getAllByLabelText("Sets")[0]!, "x");
    const monday = within(
      screen.getByRole("heading", { name: /^Mon: Push/ }),
    ).getByRole("button");
    await user.click(monday);
    expect(monday).toHaveAttribute("aria-expanded", "false");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(monday).toHaveAttribute("aria-expanded", "true");
    expect(
      screen.getAllByText("Sets must be a whole number from 1 to 10.").length,
    ).toBeGreaterThan(0);
  });

  it("opens a meal day that the server reports an error for", async () => {
    fakePlan({
      put: () =>
        problem(422, "invalid_plan", {
          detail: "x",
          errors: [
            {
              field: "meal_days[0].meals[0].portion_factor",
              code: "out_of_range",
              message: "Portion is out of range.",
            },
          ],
        }),
    });
    const user = userEvent.setup();
    renderApp("/plan");
    await screen.findByRole("heading", { name: /^Mon: Push/ });
    await user.click(screen.getByRole("tab", { name: "Meals" }));
    const monday = within(
      await screen.findByRole("heading", { name: /^Monday/ }),
    ).getByRole("button");
    expect(monday).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("heading", { name: /^Monday/ })).toHaveTextContent(
      "2 meals",
    );
    await user.click(monday);
    await user.clear(screen.getAllByLabelText("Portion")[0]!);
    await user.type(screen.getAllByLabelText("Portion")[0]!, "2");
    await user.click(monday);
    await user.click(
      within(screen.getByRole("region", { name: "Meals" })).getByRole(
        "button",
        { name: "Save changes" },
      ),
    );
    expect(
      await screen.findByText("Portion is out of range."),
    ).toBeInTheDocument();
    expect(monday).toHaveAttribute("aria-expanded", "true");
  });
});

describe("Plan editor: summary and descriptions (D105)", () => {
  it("describes the tab, summarises the current plan and describes each sub-tab", async () => {
    fakePlan({
      plan: planFixture({
        name: "Summer cut",
        start_date: shiftDay(TODAY, -8),
      }),
    });
    const user = await openPlan();
    expect(screen.getByTestId("plan-description")).toHaveTextContent(
      "Your training and meal plan",
    );
    const summary = within(screen.getByTestId("plan-summary"));
    expect(
      summary.getByRole("heading", { name: "Current plan" }),
    ).toBeInTheDocument();
    expect(summary.getByText("Summer cut")).toBeInTheDocument();
    expect(summary.getByText(/\(week 2\)$/)).toBeInTheDocument();
    expect(summary.getByText("Generated")).toBeInTheDocument();
    expect(summary.getByText("2 meals in 1 days")).toBeInTheDocument();
    expect(
      summary.getByText(/Review that the training days fit your week/),
    ).toBeInTheDocument();
    expect(screen.getByText(/Add the days you train/)).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Meals" }));
    expect(
      screen.getByText(/For each day add meals or replace them/),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "History" }));
    expect(screen.getByText(/Every plan you create is listed here/)).toBeInTheDocument();
  });

  it("falls back to the plan number, shows its changes and omits the start date", async () => {
    fakePlan({ plans: [{ ...PLAN_ONE, changes: 5, plan_no: 1 }] });
    await openPlan();
    const summary = within(screen.getByTestId("plan-summary"));
    expect(summary.getByText("Plan 1")).toBeInTheDocument();
    expect(await summary.findByText("5 changes since it was created")).toBeInTheDocument();
    expect(summary.queryByText(/version/i)).not.toBeInTheDocument();
    expect(summary.queryByText("Started")).not.toBeInTheDocument();
  });
});

describe("Plan editor: goal-driven progression (D107)", () => {
  it("explains progression, effort and the disclaimer; the removed fields are gone", async () => {
    fakePlan();
    const user = await openPlan();
    const toggle = screen.getByRole("button", { name: /How progression works/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // The disclaimer and the effort explanation are visible without opening the help.
    expect(screen.getByTestId("progression-disclaimer")).toHaveTextContent(
      /not a professional recommendation.*proper technique and professional supervision.*health conditions/,
    );
    expect(screen.getByTestId("effort-note")).toHaveTextContent(/heavy enough.*real effort/);
    await user.click(toggle);
    const content = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(content).not.toHaveAttribute("hidden");
    expect(within(content).getByText(/^Rep range:/)).toBeInTheDocument();
    expect(within(content).getByText(/^Heavier:/)).toBeInTheDocument();
    expect(within(content).getByText(/^Deload:/)).toBeInTheDocument();
    expect(within(content).getByText(/^Effort: the weight must be heavy enough/)).toBeInTheDocument();
    for (const gone of ["Progression", /^Increment/, "Allow deload weeks"]) {
      expect(screen.queryByLabelText(gone)).not.toBeInTheDocument();
    }
  });

  it("shows the plan's goal and the recommended range under the reps, warning when outside it", async () => {
    fakePlan({ plan: planFixture({ training_goal: "strength" }) });
    const user = await openPlan();
    expect(screen.getByLabelText("Training goal")).toHaveValue("strength");
    expect(screen.getByTestId("goal-detail")).toHaveTextContent("Heavy loads, few reps.");
    // The recommended range is one line at the top of the day, not repeated per exercise.
    expect(screen.getAllByTestId("day-hint")).toHaveLength(1);
    expect(screen.getByTestId("day-hint")).toHaveTextContent("Recommended for this goal: 3 to 6 reps.");
    // Bench is 8 to 10 reps: outside 3 to 6, but saving stays possible. The warning stays on the exercise.
    const note = screen.getAllByTestId("range-warning")[0]!;
    expect(note).toHaveTextContent("8 to 10 reps is outside the recommended 3 to 6");
    await user.click(within(note).getByRole("button", { name: "Use 3 to 6 reps" }));
    expect(screen.getAllByLabelText("Reps (min)")[0]).toHaveValue("3");
    expect(screen.getAllByLabelText("Max reps")[0]).toHaveValue("6");
    expect(screen.queryByTestId("range-warning")).not.toBeInTheDocument();
  });

  it("does not block saving a plan that is outside the range", async () => {
    const { calls } = fakePlan({ plan: planFixture({ training_goal: "strength" }) });
    const user = await openPlan();
    expect(screen.getAllByTestId("range-warning")[0]!).toBeInTheDocument();
    await user.clear(screen.getAllByLabelText("Sets")[0]!);
    await user.type(screen.getAllByLabelText("Sets")[0]!, "4");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.training).toHaveLength(1));
    expect(calls.training[0]!.training_days[0]!.exercises[0]).toMatchObject({ reps_min: 8, reps_max: 10 });
  });

  it("changing the goal offers the new range for all exercises, and saves the goal", async () => {
    const { calls } = fakePlan(); // hypertrophy: 8 to 12
    const user = await openPlan();
    expect(screen.queryByTestId("goal-range-offer")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Training goal"), "Endurance");
    const offer = screen.getByTestId("goal-range-offer");
    expect(offer).toHaveTextContent("The recommended range for Endurance is 13 to 20 reps.");
    await user.click(within(offer).getByRole("button", { name: "Apply 13 to 20 reps to all exercises" }));
    expect(screen.queryByTestId("goal-range-offer")).not.toBeInTheDocument();
    expect(screen.getAllByLabelText("Reps (min)")[0]).toHaveValue("13");
    expect(screen.getAllByLabelText("Max reps")[0]).toHaveValue("20");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.training).toHaveLength(1));
    const body = calls.training[0]!;
    expect(body.training_goal).toBe("endurance");
    const [bench, plank] = body.training_days[0]!.exercises;
    expect(bench).toMatchObject({ reps_min: 13, reps_max: 20 });
    expect(plank).toMatchObject({ reps_min: null, reps_max: null, target_seconds: 45 }); // timed: untouched
  });

  it("lets the athlete keep the current reps when the goal changes", async () => {
    const { calls } = fakePlan();
    const user = await openPlan();
    await user.selectOptions(screen.getByLabelText("Training goal"), "Strength");
    await user.click(within(screen.getByTestId("goal-range-offer")).getByRole("button", { name: "Keep the current reps" }));
    expect(screen.queryByTestId("goal-range-offer")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.training).toHaveLength(1));
    expect(calls.training[0]!.training_goal).toBe("strength");
    expect(calls.training[0]!.training_days[0]!.exercises[0]).toMatchObject({ reps_min: 8, reps_max: 10 });
  });

  it("starts a new exercise at the recommended range of the goal", async () => {
    const { calls } = fakePlan({ plan: planFixture({ training_goal: "endurance" }) });
    const user = await openPlan();
    await user.type(screen.getAllByLabelText("Add exercise")[0]!, "squ");
    await user.click(await screen.findByRole("button", { name: "Add Squat" }));
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(calls.training).toHaveLength(1));
    expect(calls.training[0]!.training_days[0]!.exercises[2]).toMatchObject({
      exercise_id: "ex-squat",
      reps_min: 13,
      reps_max: 20,
      rule: "double",
    });
  });

  it("offers the training goal in the new plan form, defaulting to the profile goal", async () => {
    const { calls } = fakePlan();
    const user = await openPlan();
    await user.click(screen.getByRole("button", { name: "New plan" }));
    const form = screen.getByRole("form", { name: "New plan" });
    const goal = within(form).getByLabelText("Training goal");
    await waitFor(() => expect(goal).toHaveValue("cutting")); // the profile goal is cutting
    await user.selectOptions(goal, "Strength");
    await user.type(within(form).getByLabelText("Plan name"), "Heavy");
    await user.click(within(form).getByRole("button", { name: "Create plan" }));
    await screen.findByText("New plan created: Heavy.");
    expect(calls.create[0]).toMatchObject({ name: "Heavy", training_goal: "strength" });
  });
});

const PLAN_ONE: Schemas["PlanSummary"] = {
  plan_no: 1,
  name: null,
  start_date: null,
  created_at: "2026-10-01T08:00:00Z",
  last_changed_at: "2026-10-01T08:00:00Z",
  changes: 0,
  active: true,
  source: "generated",
  first_version: 1,
  latest_version: 1,
};

describe("Plan editor: history of plans (D106)", () => {
  const change = (
    kind: Schemas["PlanChangeSummary"]["kind"],
    role: "athlete" | "coach",
    at: string,
  ): Schemas["PlanChangeSummary"] => ({
    kind,
    author_role: role,
    author: role === "coach" ? COACH_REF : ATHLETE_REF,
    at,
  });
  const version = (
    n: number,
    planNo: number,
    summary: Schemas["PlanChangeSummary"],
    over: Partial<Schemas["PlanVersionSummary"]> = {},
  ): Schemas["PlanVersionSummary"] => ({
    id: `plan-${n}`,
    version: n,
    plan_no: planNo,
    change: summary,
    source: "custom",
    active: false,
    name: null,
    start_date: null,
    created_by: summary.author,
    created_at: summary.at,
    ...over,
  });
  const versions = [
    version(5, 2, change("training_edited", "coach", "2026-10-25T10:30:00Z"), { active: true, name: "Summer cut" }),
    version(4, 2, change("created_new", "athlete", "2026-10-20T08:00:00Z"), { name: "Summer cut" }),
    version(3, 1, change("suggestion_accepted", "athlete", "2026-10-15T08:00:00Z")),
    version(2, 1, change("meals_edited", "athlete", "2026-10-10T08:00:00Z")),
    version(1, 1, change("created", "athlete", "2026-10-01T08:00:00Z")),
  ];
  const plans: Schemas["PlanSummary"][] = [
    {
      ...PLAN_ONE,
      plan_no: 2,
      name: "Summer cut",
      start_date: "2026-10-20",
      created_at: "2026-10-20T08:00:00Z",
      last_changed_at: "2026-10-25T10:30:00Z",
      changes: 1,
      source: "custom",
      first_version: 4,
      latest_version: 5,
    },
    { ...PLAN_ONE, active: false, changes: 2, last_changed_at: "2026-10-15T08:00:00Z", latest_version: 3 },
  ];

  it("lists one row per plan, newest first, with its changes and the current one marked", async () => {
    fakePlan({ plans, versions });
    const user = await openPlan();
    await user.click(screen.getByRole("tab", { name: "History" }));
    const rows = await within(await screen.findByRole("region", { name: "History" })).findAllByRole("listitem");
    expect(rows).toHaveLength(2); // five versions, two plans
    expect(rows[0]).toHaveTextContent("Summer cut");
    expect(rows[0]).toHaveTextContent("Current");
    expect(rows[0]).toHaveTextContent("1 change");
    expect(rows[0]).toHaveTextContent("Oct 25, 2026, 11:30 AM");
    expect(rows[1]).toHaveTextContent("Plan 1");
    expect(rows[1]).toHaveTextContent("2 changes");
    expect(rows[1]).not.toHaveTextContent("Current");
  });

  it("shows an athlete with one plan and five edits as one row with five changes", async () => {
    fakePlan({ plans: [{ ...PLAN_ONE, changes: 5, latest_version: 6 }] });
    const user = await openPlan();
    await user.click(screen.getByRole("tab", { name: "History" }));
    const rows = await within(await screen.findByRole("region", { name: "History" })).findAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("5 changes");
  });

  it("opens a plan to its changes over time with author, time and kind", async () => {
    fakePlan({ plans, versions });
    const user = await openPlan();
    await user.click(screen.getByRole("tab", { name: "History" }));
    await user.click(await screen.findByRole("button", { name: "Open Plan 1" }));
    const timeline = within(await screen.findByTestId("plan-timeline"));
    const entries = await timeline.findAllByRole("listitem");
    expect(entries.map((li) => li.querySelector("p")?.textContent)).toEqual([
      "Suggestion accepted",
      "Meals edited",
      "Plan created (onboarding)",
    ]);
    expect(entries[0]).toHaveTextContent("Oct 15, 2026, 10:00 AM, You");
    await user.click(screen.getByRole("button", { name: "Back to plans" }));
    await user.click(await screen.findByRole("button", { name: "Open Summer cut" }));
    const coachEntries = await within(await screen.findByTestId("plan-timeline")).findAllByRole("listitem");
    expect(coachEntries[0]).toHaveTextContent("Training edited");
    expect(coachEntries[0]).toHaveTextContent("Oct 25, 2026, 11:30 AM, Coach Coach Carla");
    expect(coachEntries[1]).toHaveTextContent("Plan created");
  });

  it("says so when a plan has no changes yet", async () => {
    fakePlan({
      plans: [PLAN_ONE],
      versions: [version(1, 1, change("created", "athlete", "2026-10-01T08:00:00Z"), { active: true })],
    });
    const user = await openPlan();
    await user.click(screen.getByRole("tab", { name: "History" }));
    await user.click(await screen.findByRole("button", { name: "Open Plan 1" }));
    expect(await screen.findByText("No changes since it was created.")).toBeInTheDocument();
    expect(within(screen.getByTestId("plan-timeline")).getAllByRole("listitem")).toHaveLength(1);
  });

  it("opens the plan as it was after a change, read-only", async () => {
    fakePlan({ plans, versions });
    const old = planFixture({ id: "plan-2", version: 2, active: false, source: "custom" });
    let requested = "";
    server.use(
      http.get(apiUrl("/athletes/:athleteId/plan/versions/:version"), ({ params }) => {
        requested = String(params.version);
        return HttpResponse.json(old);
      }),
    );
    const user = await openPlan();
    await user.click(screen.getByRole("tab", { name: "History" }));
    await user.click(await screen.findByRole("button", { name: "Open Plan 1" }));
    await user.click(
      await screen.findByRole("button", { name: "Open the plan as it was after: Meals edited, Oct 10, 2026, 10:00 AM" }),
    );
    expect(await screen.findByText(/Read-only/)).toBeInTheDocument();
    expect(requested).toBe("2");
    const view = screen.getByRole("region", { name: "Plan 1 on Oct 10, 2026, 10:00 AM" });
    expect(within(view).getByText(/Bench press/)).toBeInTheDocument();
    expect(within(view).queryAllByRole("textbox")).toHaveLength(0);
    expect(within(view).queryByRole("button", { name: /save|remove|add/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Back to changes" }));
    expect(await screen.findByTestId("plan-timeline")).toBeInTheDocument();
  });
});

describe("Plan editor: make current and delete a plan (D108)", () => {
  const listed: Schemas["PlanSummary"][] = [
    {
      ...PLAN_ONE,
      plan_no: 2,
      name: "Summer cut",
      changes: 1,
      source: "custom",
      first_version: 4,
      latest_version: 5,
    },
    { ...PLAN_ONE, active: false, changes: 2, latest_version: 3 },
  ];

  async function openHistory() {
    fakePlan({ plans: listed });
    const user = await openPlan();
    await user.click(screen.getByRole("tab", { name: "History" }));
    const region = await screen.findByRole("region", { name: "History" });
    const [current, previous] = await within(region).findAllByRole("listitem");
    const rows = [current!, previous!] as const;
    return { user, region, rows };
  }

  it("offers Make current and Delete on every plan except the current one", async () => {
    const { rows } = await openHistory();
    expect(within(rows[0]).queryByRole("button", { name: /Make current|Delete/ })).not.toBeInTheDocument();
    expect(within(rows[1]).getByRole("button", { name: "Make Plan 1 the current plan" })).toBeInTheDocument();
    expect(within(rows[1]).getByRole("button", { name: "Delete Plan 1" })).toBeInTheDocument();
  });

  it("asks first, then makes the plan current and says the other one stays in History", async () => {
    let called = "";
    server.use(
      http.post(apiUrl("/athletes/:athleteId/plans/:planNo/activate"), ({ params }) => {
        called = String(params.planNo);
        return HttpResponse.json(planFixture({ plan_no: 1, name: null, revision: 9 }));
      }),
    );
    const { user, rows } = await openHistory();
    await user.click(within(rows[1]).getByRole("button", { name: "Make Plan 1 the current plan" }));
    const dialog = within(rows[1]).getByRole("alertdialog");
    expect(dialog).toHaveTextContent("The plan that is current now stays in History");
    expect(called).toBe("");
    await user.click(within(dialog).getByRole("button", { name: "Make current" }));
    expect(await screen.findByText("Plan 1 is now the current plan.")).toBeInTheDocument();
    expect(called).toBe("1");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("refetches the suggestions list after making a plan current", async () => {
    server.use(
      http.post(apiUrl("/athletes/:athleteId/plans/:planNo/activate"), () =>
        HttpResponse.json(planFixture({ plan_no: 1, name: null, revision: 9 })),
      ),
    );
    const { user, rows } = await openHistory();
    const spy = vi.spyOn(QueryClient.prototype, "invalidateQueries");
    await user.click(within(rows[1]).getByRole("button", { name: "Make Plan 1 the current plan" }));
    await user.click(within(within(rows[1]).getByRole("alertdialog")).getByRole("button", { name: "Make current" }));
    await screen.findByText("Plan 1 is now the current plan.");
    expect(spy.mock.calls.map(([filters]) => filters?.queryKey)).toContainEqual(["suggestions"]);
    spy.mockRestore();
  });

  it("deletes only after a confirmation that says it cannot be undone", async () => {
    let called = "";
    server.use(
      http.delete(apiUrl("/athletes/:athleteId/plans/:planNo"), ({ params }) => {
        called = String(params.planNo);
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { user, rows } = await openHistory();
    await user.click(within(rows[1]).getByRole("button", { name: "Delete Plan 1" }));
    const dialog = within(rows[1]).getByRole("alertdialog");
    expect(dialog).toHaveTextContent("This cannot be undone");
    expect(dialog).toHaveTextContent("Logged workouts and meals are not affected");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(called).toBe("");
    await user.click(within(rows[1]).getByRole("button", { name: "Delete Plan 1" }));
    await user.click(within(within(rows[1]).getByRole("alertdialog")).getByRole("button", { name: "Delete plan" }));
    expect(await screen.findByText("Plan 1 was deleted.")).toBeInTheDocument();
    expect(called).toBe("1");
  });

  it("shows an error and keeps the confirmation when the server refuses", async () => {
    server.use(
      http.delete(apiUrl("/athletes/:athleteId/plans/:planNo"), () =>
        problem(409, "plan_is_current"),
      ),
    );
    const { user, rows } = await openHistory();
    await user.click(within(rows[1]).getByRole("button", { name: "Delete Plan 1" }));
    await user.click(within(within(rows[1]).getByRole("alertdialog")).getByRole("button", { name: "Delete plan" }));
    expect(await screen.findByText("FitWise couldn't delete the plan. Try again.")).toBeInTheDocument();
    expect(within(rows[1]).getByRole("alertdialog")).toBeInTheDocument();
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
    await openDay(user, /^Monday/);
    return user;
  }

  it("copies a training day to an empty weekday, with the same targets and no ids, leaving Monday as it is", async () => {
    const { calls } = fakePlan();
    const user = await openPlan();
    await user.click(training().getByRole("button", { name: "Duplicate Monday" }));
    await user.selectOptions(training().getByLabelText("Copy to"), "thu");
    await user.click(training().getByRole("button", { name: "Copy" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(
      await screen.findByRole("heading", { name: /^Thu: Push(?: .*)?$/ }),
    ).toBeInTheDocument();
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
    expect(
      screen.getByRole("heading", { name: /^Thu: Legs(?: .*)?$/ }),
    ).toBeInTheDocument();
    expect(
      training().getByRole("button", { name: "Save changes" }),
    ).toBeDisabled();
    expect(calls.training).toHaveLength(0);

    await user.click(training().getByRole("button", { name: "Duplicate Monday" }));
    await user.selectOptions(training().getByLabelText("Copy to"), "thu");
    await user.click(training().getByRole("button", { name: "Copy" }));
    await user.click(
      screen.getByRole("button", { name: "Yes, replace Thursday" }),
    );
    expect(
      await screen.findByRole("heading", { name: /^Thu: Push(?: .*)?$/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: /^Thu: Legs(?: .*)?$/ }),
    ).not.toBeInTheDocument();
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
    await openDay(user, /^Monday/);
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
    await openFoods(user, "Chicken rice");
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
    await openFoods(user, "Oat bowl");
    await user.click(mealsRegion().getByRole("button", { name: "Swap Oat bowl" }));
    expect(await screen.findByText(/No similar meals fit/)).toBeInTheDocument();
    expect(calls.meals).toHaveLength(0);
  });

  it("waits for a clean draft: unsaved changes disable Swap", async () => {
    fakePlan();
    swaps(swapList([toast]));
    const user = await openMeals();
    await openFoods(user, "Chicken rice");
    await user.click(mealsRegion().getByRole("button", { name: "Remove Oat bowl" }));
    expect(mealsRegion().getByRole("button", { name: "Swap Chicken rice" })).toBeDisabled();
    expect(mealsRegion().getAllByText("Save your changes to see swaps.").length).toBeGreaterThan(0);
  });

  it("shows an error when the alternatives cannot be loaded", async () => {
    fakePlan();
    server.use(http.get(apiUrl("/athletes/:athleteId/plan/meals/:mealKey/swaps"), () => problem(422, "past_day")));
    const user = await openMeals();
    await openFoods(user, "Oat bowl");
    await user.click(mealsRegion().getByRole("button", { name: "Swap Oat bowl" }));
    expect(await screen.findByText("Couldn't load alternatives. Try again.")).toBeInTheDocument();
  });
});
