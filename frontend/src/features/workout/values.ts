import type { TFunction } from "i18next";

import type { ExerciseSummary } from "../../api/workout";
import { formatWeight, type UnitSystem } from "../../lib/units";

export interface SetValues {
  reps: number | null;
  weight_kg: number | null;
  seconds: number | null;
  distance_m: number | null;
}

/** "10 reps · 40 kg" for whichever values are present (weights shown in the user's units). */
export function describeValues(t: TFunction, values: Partial<SetValues>, units: UnitSystem): string {
  return [
    values.reps != null ? t("workout.reps", { count: values.reps }) : null,
    values.seconds != null ? t("workout.seconds", { count: values.seconds }) : null,
    values.weight_kg != null ? formatWeight(values.weight_kg, units) : null,
    values.distance_m != null ? t("workout.meters", { count: values.distance_m }) : null,
  ]
    .filter(Boolean)
    .join(" · ");
}

export type Field = "reps" | "weight" | "seconds" | "distance";

/** Which inputs the editor shows for an exercise type, and which of them are required. */
export function fieldsFor(type: ExerciseSummary["type"]): { field: Field; required: boolean }[] {
  switch (type) {
    case "strength":
      return [
        { field: "reps", required: true },
        { field: "weight", required: true },
      ];
    case "bodyweight":
      return [
        { field: "reps", required: true },
        { field: "weight", required: false },
      ];
    case "timed":
      return [
        { field: "seconds", required: true },
        { field: "distance", required: false },
      ];
  }
}

/** Compact one-line form for a set row: "8 × 60 kg", "12 + 10 kg", "45 s" (user's units). */
export function describeCompact(t: TFunction, values: Partial<SetValues>, units: UnitSystem): string {
  const weight = values.weight_kg != null ? formatWeight(values.weight_kg, units) : null;
  const distance = values.distance_m != null ? t("workout.meters", { count: values.distance_m }) : null;
  if (values.seconds != null) {
    return [t("workout.seconds", { count: values.seconds }), distance].filter(Boolean).join(" · ");
  }
  if (values.reps != null) {
    return weight ? t("workout.repsTimesWeight", { reps: values.reps, weight }) : String(values.reps);
  }
  return weight ?? "";
}

/**
 * The two lines of a set card: reps (or duration) and weight. A strength set without a weight
 * says "Weight not defined"; bodyweight and timed sets show a weight only when there is one (D96).
 */
export function cardLines(
  t: TFunction,
  values: Partial<SetValues>,
  units: UnitSystem,
  type: ExerciseSummary["type"],
): { main: string; weight: string | null } {
  const distance = values.distance_m != null ? t("workout.meters", { count: values.distance_m }) : null;
  const main =
    values.seconds != null
      ? [t("workout.seconds", { count: values.seconds }), distance].filter(Boolean).join(" · ")
      : values.reps != null
        ? t("workout.reps", { count: values.reps })
        : "";
  const weight =
    values.weight_kg != null
      ? formatWeight(values.weight_kg, units)
      : type === "strength"
        ? t("workout.weightNotDefined")
        : null;
  return { main, weight };
}

type Targets = { target_reps: number | null; target_weight_kg: number | null; target_seconds: number | null };

/**
 * Whether "done as planned" can copy this set's targets (mirrors the server, F10.7, D96): a timed
 * set needs a duration, other sets need reps, and a strength set also needs a planned weight.
 */
export function canLogAsPlanned(set: Targets, type: ExerciseSummary["type"]): boolean {
  if (type === "timed") return set.target_seconds != null;
  if (set.target_reps == null) return false;
  return type !== "strength" || set.target_weight_kg != null;
}
