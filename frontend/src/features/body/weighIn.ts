import type { BodyMetricInput } from "../../api/body";
import { inchesToCm, lbToKg, parseDecimal, type UnitSystem } from "../../lib/units";

export type WeighInField = "date" | "weight" | "bodyFat" | "neck" | "waist" | "hip";

export type WeighInValues = Record<WeighInField, string>;

/** Error keys under `body.errors`, or a literal message that came from the API (422). */
export type WeighInErrors = Partial<Record<WeighInField | "form", { key: string } | { message: string }>>;

/** API field name (`weight_kg`) -> form field. */
const API_FIELDS: Record<string, WeighInField> = {
  date: "date",
  weight_kg: "weight",
  body_fat_pct: "bodyFat",
  neck_cm: "neck",
  waist_cm: "waist",
  hip_cm: "hip",
};

export function formFieldOf(apiField: string): WeighInField | undefined {
  return API_FIELDS[apiField.split(/[./]/).pop() ?? apiField];
}

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Validates the form and converts it to the metric request (rule 5). `today` is the user's
 * calendar day; ISO dates compare correctly as strings.
 */
export function buildWeighIn(
  values: WeighInValues,
  units: UnitSystem,
  today: string,
): { input: BodyMetricInput } | { errors: WeighInErrors } {
  const errors: WeighInErrors = {};
  if (!ISO_DAY.test(values.date)) errors.date = { key: "invalidDate" };
  else if (values.date > today) errors.date = { key: "futureDate" };

  const parsed: Partial<Record<Exclude<WeighInField, "date">, number>> = {};
  for (const field of ["weight", "bodyFat", "neck", "waist", "hip"] as const) {
    const text = values[field].trim();
    if (text === "") continue;
    const number = parseDecimal(text);
    if (number === null) errors[field] = { key: "invalidNumber" };
    else parsed[field] = number;
  }
  if (Object.keys(errors).length === 0 && Object.keys(parsed).length === 0) errors.form = { key: "nothing" };
  if (Object.keys(errors).length > 0) return { errors };

  const length = (value: number) => (units === "imperial" ? inchesToCm(value) : value);
  const input: BodyMetricInput = { date: values.date };
  if (parsed.weight !== undefined) input.weight_kg = units === "imperial" ? lbToKg(parsed.weight) : parsed.weight;
  if (parsed.bodyFat !== undefined) input.body_fat_pct = parsed.bodyFat;
  if (parsed.neck !== undefined) input.neck_cm = length(parsed.neck);
  if (parsed.waist !== undefined) input.waist_cm = length(parsed.waist);
  if (parsed.hip !== undefined) input.hip_cm = length(parsed.hip);
  return { input };
}
