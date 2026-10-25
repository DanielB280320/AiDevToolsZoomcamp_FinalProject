import type { TFunction } from "i18next";

import type { Choice } from "../components/form/fields";
import { DAYS_PER_WEEK, MEALS_PER_DAY, SESSION_MINUTES, WEEKDAYS, ALLERGENS, type WizardValues } from "./model";

type Value<K extends keyof WizardValues> = Exclude<WizardValues[K], "" | null | unknown[]>;

function pick<V extends string>(t: TFunction, prefix: string, ids: readonly V[], detail: boolean): Choice<V>[] {
  return ids.map((id) => ({
    value: id,
    label: t(`${prefix}.${id}` as never),
    detail: detail ? t(`${prefix}.${id}Detail` as never) : "",
  }));
}

const numbers = (list: readonly number[], label: (count: number) => string): Choice<string>[] =>
  list.map((count) => ({ value: String(count), label: label(count), detail: "" }));

/** Option lists for the wizard's radio and checkbox groups, labelled from en.json. */
export function wizardChoices(t: TFunction) {
  return {
    sex: pick<Value<"sex">>(t, "onboarding.body.sex", ["male", "female", "unspecified"], false),
    bodyFatMethod: (["entered", "navy", "skip"] as const).map(
      (id): Choice<Value<"bodyFatMethod">> => ({
        value: id,
        label: t(`onboarding.bodyFat.method.${id}`),
        detail: t(`onboarding.bodyFat.method.${id}Detail`),
      }),
    ),
    lifestyle: pick<Value<"lifestyle">>(t, "onboarding.lifestyle", ["sedentary", "lightly_active", "active", "very_active"], true),
    goal: pick<Value<"goal">>(t, "onboarding.goal", ["recomposition", "muscle_gain", "cutting", "maintenance", "wellness"], true),
    experience: pick<Value<"experience">>(t, "onboarding.training.experience", ["beginner", "intermediate", "advanced"], true),
    equipment: pick<Value<"equipment">>(t, "onboarding.training.equipment", ["full_gym", "home_dumbbells", "bodyweight_only"], true),
    diet: pick<Value<"diet">>(t, "onboarding.diet.diet", ["omnivore", "vegetarian", "vegan", "pescatarian"], true),
    daysPerWeek: numbers(DAYS_PER_WEEK, (count) => t("onboarding.training.daysPerWeek.option", { count })),
    sessionMinutes: numbers(SESSION_MINUTES, (count) => t("onboarding.training.sessionMinutes.option", { count })),
    mealsPerDay: numbers(MEALS_PER_DAY, (count) => t("onboarding.diet.mealsPerDay.option", { count })),
    weekdays: WEEKDAYS.map((day) => ({ value: day, label: t(`onboarding.training.weekday.${day}`) })),
    allergies: ALLERGENS.map((a) => ({ value: a, label: t(`onboarding.diet.allergies.${a}`) })),
  };
}

/** Unit symbols shown beside inputs. */
export const UNIT_SYMBOLS = { cm: "cm", ft: "ft", in: "in", percent: "%" } as const;
