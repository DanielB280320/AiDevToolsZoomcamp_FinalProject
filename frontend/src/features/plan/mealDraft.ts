import type { Meal, MealDay, MealPlanUpdate, PlannedMeal, Weekday } from "../../api/plan";
import { WEEKDAYS } from "../../api/plan";
import type { MealSlot } from "../../api/meals";
import { parseDecimal } from "../../lib/units";
import { type LocalError, newUid } from "./trainingDraft";

export interface DraftFood {
  foodId: string;
  name: string;
  grams: string;
}

export interface DraftMeal {
  uid: string;
  /** Present for a meal that already exists: sending it keeps the meal's logs (D73, D75(6)). */
  id?: string;
  slot: MealSlot;
  mealId: string;
  mealName: string;
  portion: string;
  foods: DraftFood[];
  /** Grams typed by hand are the final amounts and replace the portion factor. */
  gramsEdited: boolean;
}

export interface DraftMealDay {
  uid: string;
  weekday: Weekday;
  existed: boolean;
  editedBy: string | null;
  meals: DraftMeal[];
}

const gramsText = (grams: number): string => String(Math.round(grams * 10) / 10);

const fromPlanned = (m: PlannedMeal): DraftMeal => ({
  uid: newUid(),
  id: m.id,
  slot: m.slot,
  mealId: m.meal.id,
  mealName: m.meal.name,
  portion: String(m.portion_factor),
  foods: m.items.map((i) => ({ foodId: i.food.id, name: i.food.name, grams: gramsText(i.grams) })),
  gramsEdited: false,
});

export function mealDraftFromPlan(days: MealDay[]): DraftMealDay[] {
  return WEEKDAYS.map((weekday) => {
    const day = days.find((d) => d.weekday === weekday);
    return {
      uid: newUid(),
      weekday,
      existed: day !== undefined,
      editedBy: day?.edited_by?.display_name ?? null,
      meals: day ? day.meals.map(fromPlanned) : [],
    };
  });
}

/** The chosen library meal at the meal's current portion (used for add and replace). */
export function draftFromLibraryMeal(meal: Meal, slot: MealSlot, portion: string, id?: string): DraftMeal {
  const factor = parseDecimal(portion) ?? 1;
  return {
    uid: newUid(),
    ...(id ? { id } : {}),
    slot,
    mealId: meal.id,
    mealName: meal.name,
    portion,
    foods: meal.items.map((i) => ({ foodId: i.food.id, name: i.food.name, grams: gramsText(i.grams * factor) })),
    gramsEdited: false,
  };
}

/** Field path of a meal in the request: the API reports `meal_days[i].meals[j].…` by request position. */
export const mealPath = (dayIndex: number, mealIndex: number, field?: string): string =>
  `meal_days[${dayIndex}].meals[${mealIndex}]${field ? `.${field}` : ""}`;

export interface MealBuild {
  body: MealPlanUpdate | null;
  errors: Record<string, LocalError>;
  /** Request index of each weekday that is sent, to place server errors. */
  indexOf: Partial<Record<Weekday, number>>;
}

export function buildMealUpdate(days: DraftMealDay[], revision: number): MealBuild {
  const errors: Record<string, LocalError> = {};
  const indexOf: Partial<Record<Weekday, number>> = {};
  const sent = days.filter((d) => d.existed || d.meals.length > 0);
  const body: MealPlanUpdate = {
    revision,
    meal_days: sent.map((day, d) => {
      indexOf[day.weekday] = d;
      return {
        weekday: day.weekday,
        meals: day.meals.map((m, j) => {
          const base = { ...(m.id ? { id: m.id } : {}), slot: m.slot, meal_id: m.mealId };
          if (m.gramsEdited) {
            const foods = m.foods.map((f) => ({ food_id: f.foodId, grams: parseDecimal(f.grams) }));
            foods.forEach((f, k) => {
              if (f.grams === null || f.grams <= 0 || f.grams > 2000) errors[mealPath(d, j, `items[${k}].grams`)] = "grams";
            });
            return { ...base, portion_factor: 1, items: foods.map((f) => ({ food_id: f.food_id, grams: f.grams ?? 0 })) };
          }
          const factor = parseDecimal(m.portion);
          if (factor === null || factor < 0.25 || factor > 3) errors[mealPath(d, j, "portion_factor")] = "portion";
          return { ...base, portion_factor: factor ?? 1 };
        }),
      };
    }),
  };
  return Object.keys(errors).length > 0 ? { body: null, errors, indexOf } : { body, errors, indexOf };
}

/** Index of a weekday in the request, or -1 when it is not sent (no meals and none before). */
export function requestIndex(days: DraftMealDay[], weekday: Weekday): number {
  return days.filter((d) => d.existed || d.meals.length > 0).findIndex((d) => d.weekday === weekday);
}
