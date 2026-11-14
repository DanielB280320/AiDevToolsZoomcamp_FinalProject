import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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
    name: null,
    start_date: null,
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
        ...(body.start_from === "generated"
          ? {}
          : { training_days: [], meal_days: [] }),
      };
      return HttpResponse.json(current, { status: 201 });
    }),
    http.get(apiUrl("/athletes/:athleteId/plan/versions"), () =>
      HttpResponse.json({ items: options.versions ?? [] }),
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
    await openDay(user, /^Monday/);
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
    expect(summary.getByText("3, Generated")).toBeInTheDocument();
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
    expect(screen.getByText(/versions are read-only/)).toBeInTheDocument();
  });

  it("falls back to the version when the plan has no name and omits the start date", async () => {
    fakePlan();
    await openPlan();
    const summary = within(screen.getByTestId("plan-summary"));
    expect(summary.getByText("Plan, version 3")).toBeInTheDocument();
    expect(summary.queryByText("Started")).not.toBeInTheDocument();
  });
});

describe("Plan editor: progression methods (D105)", () => {
  it("lists the three methods, increment and deload, collapsed under the tab description", async () => {
    fakePlan();
    const user = await openPlan();
    const toggle = screen.getByRole("button", { name: /Progression methods/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    await user.click(toggle);
    const content = document.getElementById(
      toggle.getAttribute("aria-controls")!,
    )!;
    expect(content).not.toHaveAttribute("hidden");
    expect(
      within(content).getByText(
        /^Linear progression: one fixed number of reps/,
      ),
    ).toBeInTheDocument();
    expect(
      within(content).getByText(/^Double progression: a range of reps/),
    ).toBeInTheDocument();
    expect(
      within(content).getByText(/^Manual: FitWise makes no suggestions/),
    ).toBeInTheDocument();
    expect(within(content).getByText(/^Increment:/)).toBeInTheDocument();
    expect(
      within(content).getByText(
        /^Allow deload weeks: after 3 finished sessions in a row/,
      ),
    ).toBeInTheDocument();
  });

  it("shows the meaning of the selected method under the select and follows the selection", async () => {
    fakePlan();
    const user = await openPlan();
    const rule = screen.getAllByLabelText("Progression")[0]!; // bench: double
    const hint = () =>
      document.getElementById(
        rule.getAttribute("aria-describedby")!.split(" ")[0]!,
      )!;
    expect(hint()).toHaveTextContent(
      /^Double: add reps until every set reaches the top/,
    );
    await user.selectOptions(rule, "Manual");
    expect(hint()).toHaveTextContent(
      "Manual: no suggestions; you change the targets yourself.",
    );
    await user.selectOptions(rule, "Linear");
    expect(hint()).toHaveTextContent(
      /^Linear: hit the fixed reps on every set/,
    );
  });
});

describe("Plan editor: version history", () => {
  const versions: Schemas["PlanVersionSummary"][] = [
    {
      id: "plan-3",
      version: 3,
      source: "custom",
      active: true,
      name: null,
      start_date: null,
      created_by: COACH_REF,
      created_at: "2026-10-25T10:30:00Z",
    },
    {
      id: "plan-2",
      version: 2,
      source: "generated",
      active: false,
      name: null,
      start_date: null,
      created_by: ATHLETE_REF,
      created_at: "2026-10-20T08:00:00Z",
    },
  ];

  it("lists the name of a version that has one", async () => {
    fakePlan({ versions: [{ ...versions[0]!, name: "Summer cut" }, versions[1]!] });
    const user = await openPlan();
    await user.click(screen.getByRole("tab", { name: "History" }));
    const items = await screen.findAllByRole("listitem");
    expect(items.find((li) => li.textContent?.includes("Version 3"))).toHaveTextContent("Summer cut");
    expect(items.find((li) => li.textContent?.includes("Version 2"))).not.toHaveTextContent("Name");
  });

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
