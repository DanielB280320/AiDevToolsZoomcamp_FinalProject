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
