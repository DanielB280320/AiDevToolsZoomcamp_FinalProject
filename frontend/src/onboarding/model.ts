import type { TFunction } from "i18next";

import type { AthleteProfileInput, OnboardingBodyMetric, OnboardingRequest } from "../api/onboarding";
import type { Schemas } from "../api/client";
import {
  feetInchesToCm,
  formatHeight,
  formatLength,
  formatWeight,
  inchesToCm,
  lbToKg,
  parseDecimal,
  parseWhole,
  toStoredCm,
  toStoredKg,
  type UnitSystem,
} from "../lib/units";

type Weekday = Schemas["Weekday"];

/** Plausible ranges from spec F2.3 (metric; the same numbers openapi.yaml enforces). */
export const RANGES = {
  height_cm: { min: 120, max: 230 },
  weight_kg: { min: 35, max: 300 },
  body_fat_pct: { min: 3, max: 60 },
  measurement_cm: { min: 20, max: 200 },
} as const;

export const WEEKDAYS: readonly Weekday[] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
export const DAYS_PER_WEEK = [2, 3, 4, 5, 6] as const;
export const SESSION_MINUTES = [30, 45, 60, 75, 90] as const;
export const MEALS_PER_DAY = [3, 4, 5] as const;
export const ALLERGENS: readonly Schemas["Allergen"][] = ["gluten", "lactose", "nuts", "eggs", "soy", "shellfish", "fish"];

export type BodyFatChoice = OnboardingBodyMetric["body_fat_method"];

/** Everything the wizard collects, as typed. Numbers stay strings until validated. */
export interface WizardValues {
  sex: AthleteProfileInput["sex"] | "";
  /** Metric height, or the feet part when imperial. */
  height: string;
  /** Inches part of an imperial height. */
  heightInches: string;
  weight: string;
  bodyFatMethod: BodyFatChoice | "";
  bodyFat: string;
  neck: string;
  waist: string;
  hip: string;
  lifestyle: AthleteProfileInput["lifestyle"] | "";
  goal: AthleteProfileInput["goal"] | "";
  experience: AthleteProfileInput["experience"] | "";
  daysPerWeek: number | null;
  preferredDays: Weekday[];
  sessionMinutes: number | null;
  equipment: AthleteProfileInput["equipment"] | "";
  avoidedExercises: { id: string; name: string }[];
  diet: AthleteProfileInput["diet"] | "";
  allergies: Schemas["Allergen"][];
  mealsPerDay: number | null;
}

export const emptyValues = (): WizardValues => ({
  sex: "",
  height: "",
  heightInches: "",
  weight: "",
  bodyFatMethod: "",
  bodyFat: "",
  neck: "",
  waist: "",
  hip: "",
  lifestyle: "",
  goal: "",
  experience: "",
  daysPerWeek: null,
  preferredDays: [],
  sessionMinutes: null,
  equipment: "",
  avoidedExercises: [],
  diet: "",
  allergies: [],
  mealsPerDay: null,
});

export type StepId = "body" | "bodyFat" | "lifestyle" | "goal" | "training" | "diet";
export const STEPS: readonly StepId[] = ["body", "bodyFat", "lifestyle", "goal", "training", "diet"];

export type FieldErrors = Record<string, string>;

/** Hip is only asked for with the Navy method for female and "prefer not to say" (F2, F3.3). */
export const needsHip = (sex: WizardValues["sex"]): boolean => sex !== "male";

/** Height in cm from what was typed, or `null` when it is empty or malformed. */
export function heightToCm(values: WizardValues, units: UnitSystem): number | null {
  if (units === "metric") {
    const cm = parseDecimal(values.height);
    return cm === null ? null : toStoredCm(cm);
  }
  const feet = parseWhole(values.height);
  const inches = values.heightInches.trim() === "" ? 0 : parseDecimal(values.heightInches);
  return feet === null || inches === null ? null : feetInchesToCm(feet, inches);
}

export function weightToKg(text: string, units: UnitSystem): number | null {
  const value = parseDecimal(text);
  if (value === null) return null;
  return units === "metric" ? toStoredKg(value) : lbToKg(value);
}

/** A tape measurement in cm (typed in cm or inches). */
export function lengthToCm(text: string, units: UnitSystem): number | null {
  const value = parseDecimal(text);
  if (value === null) return null;
  return units === "metric" ? toStoredCm(value) : inchesToCm(value);
}

const between = (value: number, range: { min: number; max: number }) => value >= range.min && value <= range.max;

/** Range text in the user's units, e.g. "120 to 230 cm" or "3 ft 11.2 in to 7 ft 6.6 in". */
export function heightRange(units: UnitSystem): string {
  const { min, max } = RANGES.height_cm;
  return `${formatHeight(min, units)} – ${formatHeight(max, units)}`;
}
export function weightRange(units: UnitSystem): string {
  const { min, max } = RANGES.weight_kg;
  return `${formatWeight(min, units)} – ${formatWeight(max, units)}`;
}
export function measurementRange(units: UnitSystem): string {
  const { min, max } = RANGES.measurement_cm;
  return `${formatLength(min, units)} – ${formatLength(max, units)}`;
}

function measurementError(text: string, units: UnitSystem, t: TFunction): string | undefined {
  const cm = lengthToCm(text, units);
  if (cm === null) return t("onboarding.validation.number");
  return between(cm, RANGES.measurement_cm) ? undefined : t("onboarding.validation.measurementRange", { range: measurementRange(units) });
}

/** Validates one step against the same limits as openapi.yaml; returns messages keyed by field id. */
export function validateStep(step: StepId, values: WizardValues, units: UnitSystem, t: TFunction): FieldErrors {
  const errors: FieldErrors = {};
  const need = (field: string, ok: boolean, message: string) => {
    if (!ok) errors[field] = message;
  };
  const required = t("onboarding.validation.required");

  switch (step) {
    case "body": {
      need("sex", values.sex !== "", required);
      const cm = heightToCm(values, units);
      if (values.height.trim() === "") errors.height = required;
      else if (cm === null) errors.height = t("onboarding.validation.number");
      else need("height", between(cm, RANGES.height_cm), t("onboarding.validation.heightRange", { range: heightRange(units) }));
      const kg = weightToKg(values.weight, units);
      if (values.weight.trim() === "") errors.weight = required;
      else if (kg === null) errors.weight = t("onboarding.validation.number");
      else need("weight", between(kg, RANGES.weight_kg), t("onboarding.validation.weightRange", { range: weightRange(units) }));
      break;
    }
    case "bodyFat": {
      need("bodyFatMethod", values.bodyFatMethod !== "", required);
      if (values.bodyFatMethod === "entered") {
        const pct = parseDecimal(values.bodyFat);
        if (values.bodyFat.trim() === "") errors.bodyFat = required;
        else if (pct === null) errors.bodyFat = t("onboarding.validation.number");
        else need("bodyFat", between(pct, RANGES.body_fat_pct), t("onboarding.validation.bodyFatRange", RANGES.body_fat_pct));
      }
      if (values.bodyFatMethod === "navy") {
        const fields = [
          ["neck", values.neck],
          ["waist", values.waist],
          ...(needsHip(values.sex) ? [["hip", values.hip]] : []),
        ] as const;
        for (const [field, text] of fields) {
          if (text.trim() === "") errors[field] = required;
          else {
            const message = measurementError(text, units, t);
            if (message) errors[field] = message;
          }
        }
      }
      break;
    }
    case "lifestyle":
      need("lifestyle", values.lifestyle !== "", required);
      break;
    case "goal":
      need("goal", values.goal !== "", required);
      break;
    case "training":
      need("experience", values.experience !== "", required);
      need("daysPerWeek", values.daysPerWeek !== null, required);
      need("sessionMinutes", values.sessionMinutes !== null, required);
      need("equipment", values.equipment !== "", required);
      if (values.preferredDays.length === 0) errors.preferredDays = required;
      else if (values.daysPerWeek !== null && values.preferredDays.length !== values.daysPerWeek) {
        errors.preferredDays = t("onboarding.validation.daysMismatch", {
          count: values.daysPerWeek,
          picked: values.preferredDays.length,
        });
      }
      break;
    case "diet":
      need("diet", values.diet !== "", required);
      need("mealsPerDay", values.mealsPerDay !== null, required);
      break;
  }
  return errors;
}

/** Step that owns a field id, for sending the user back when the API rejects one. */
export function stepOfField(field: string): StepId | undefined {
  const map: Record<string, StepId> = {
    sex: "body",
    height: "body",
    height_cm: "body",
    weight: "body",
    weight_kg: "body",
    body_fat_method: "bodyFat",
    body_fat_pct: "bodyFat",
    neck_cm: "bodyFat",
    waist_cm: "bodyFat",
    hip_cm: "bodyFat",
    lifestyle: "lifestyle",
    goal: "goal",
    experience: "training",
    days_per_week: "training",
    preferred_days: "training",
    session_minutes: "training",
    equipment: "training",
    avoided_exercise_ids: "training",
    diet: "diet",
    allergies: "diet",
    meals_per_day: "diet",
  };
  return map[field];
}

/** Builds the metric `OnboardingRequest`. Call only after every step validated. */
export function buildRequest(values: WizardValues, units: UnitSystem): OnboardingRequest {
  const body_metric: OnboardingBodyMetric = {
    weight_kg: weightToKg(values.weight, units)!,
    body_fat_method: values.bodyFatMethod as BodyFatChoice,
  };
  if (values.bodyFatMethod === "entered") body_metric.body_fat_pct = parseDecimal(values.bodyFat)!;
  if (values.bodyFatMethod === "navy") {
    body_metric.neck_cm = lengthToCm(values.neck, units)!;
    body_metric.waist_cm = lengthToCm(values.waist, units)!;
    if (needsHip(values.sex)) body_metric.hip_cm = lengthToCm(values.hip, units)!;
  }
  return {
    profile: {
      sex: values.sex as AthleteProfileInput["sex"],
      height_cm: heightToCm(values, units)!,
      lifestyle: values.lifestyle as AthleteProfileInput["lifestyle"],
      goal: values.goal as AthleteProfileInput["goal"],
      experience: values.experience as AthleteProfileInput["experience"],
      days_per_week: values.daysPerWeek!,
      preferred_days: WEEKDAYS.filter((day) => values.preferredDays.includes(day)),
      session_minutes: values.sessionMinutes as AthleteProfileInput["session_minutes"],
      equipment: values.equipment as AthleteProfileInput["equipment"],
      avoided_exercise_ids: values.avoidedExercises.map((exercise) => exercise.id),
      diet: values.diet as AthleteProfileInput["diet"],
      allergies: values.allergies,
      meals_per_day: values.mealsPerDay as AthleteProfileInput["meals_per_day"],
    },
    body_metric,
  };
}
