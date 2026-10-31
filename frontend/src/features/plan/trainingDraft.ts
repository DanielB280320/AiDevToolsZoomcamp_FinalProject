import type { Exercise } from "../../api/onboarding";
import type { PlannedExercise, ProgressionRule, TrainingDay, TrainingPlanUpdate, Weekday } from "../../api/plan";
import { kgToLb, lbToKg, parseDecimal, parseWhole, type UnitSystem } from "../../lib/units";

type ExerciseType = Exercise["type"];

/** What the athlete is typing: numbers stay strings until saved; weights are in the user's units. */
export interface DraftExercise {
  uid: string;
  id?: string;
  exerciseId: string;
  name: string;
  type: ExerciseType;
  sets: string;
  repsMin: string;
  repsMax: string;
  weight: string;
  seconds: string;
  rest: string;
  rule: ProgressionRule;
  increment: string;
  deload: boolean;
}

export interface DraftDay {
  uid: string;
  id?: string;
  weekday: Weekday;
  name: string;
  editedBy: string | null;
  exercises: DraftExercise[];
}

let counter = 0;
export const newUid = (): string => `draft-${++counter}`;

const show = (value: number | null, units: UnitSystem): string =>
  value === null ? "" : String(units === "metric" ? value : kgToLb(value));
const text = (value: number | null): string => (value === null ? "" : String(value));

export function draftFromPlan(days: TrainingDay[], units: UnitSystem): DraftDay[] {
  return days.map((day) => ({
    uid: newUid(),
    id: day.id,
    weekday: day.weekday,
    name: day.name,
    editedBy: day.edited_by?.role === "coach" ? day.edited_by.display_name : null,
    exercises: day.exercises.map((e: PlannedExercise) => ({
      uid: newUid(),
      id: e.id,
      exerciseId: e.exercise.id,
      name: e.exercise.name,
      type: e.exercise.type,
      sets: String(e.sets),
      repsMin: text(e.reps_min),
      repsMax: e.reps_max !== null && e.reps_max !== e.reps_min ? String(e.reps_max) : "",
      weight: show(e.target_weight_kg, units),
      seconds: text(e.target_seconds),
      rest: String(e.rest_seconds),
      rule: e.rule,
      increment: show(e.increment_kg, units),
      deload: e.deload_enabled,
    })),
  }));
}

/** A new exercise with sensible defaults for its type; the server rejects what does not fit. */
export function newDraftExercise(exercise: Exercise, units: UnitSystem): DraftExercise {
  const timed = exercise.type === "timed";
  return {
    uid: newUid(),
    exerciseId: exercise.id,
    name: exercise.name,
    type: exercise.type,
    sets: "3",
    repsMin: timed ? "" : "8",
    repsMax: "",
    weight: "",
    seconds: timed ? "30" : "",
    rest: "90",
    rule: "linear",
    increment: show(exercise.increment_kg, units),
    deload: true,
  };
}

export function newDraftDay(weekday: Weekday, name: string): DraftDay {
  return { uid: newUid(), weekday, name, editedBy: null, exercises: [] };
}

/** Field path used by the API in `errors[].field`, so server and local messages land in the same place. */
export const exercisePath = (day: number, exercise: number, field?: string): string =>
  `training_days[${day}].exercises[${exercise}]${field ? `.${field}` : ""}`;
export const dayPath = (day: number, field?: string): string => `training_days[${day}]${field ? `.${field}` : ""}`;

export type LocalError = "nameRequired" | "sets" | "rest" | "seconds" | "reps" | "weight" | "increment" | "grams" | "portion";

export interface BuildResult {
  body: TrainingPlanUpdate | null;
  /** i18n keys (under `plan.errors`) by field path for values that cannot be parsed. */
  errors: Record<string, LocalError>;
}

function whole(value: string, min: number, max: number): number | null {
  const n = parseWhole(value);
  return n !== null && n >= min && n <= max ? n : null;
}

export function buildTrainingUpdate(days: DraftDay[], revision: number, units: UnitSystem): BuildResult {
  const errors: Record<string, LocalError> = {};
  const toKg = (value: string) => {
    const n = parseDecimal(value);
    return n === null ? null : units === "metric" ? n : lbToKg(n);
  };
  const body: TrainingPlanUpdate = {
    revision,
    training_days: days.map((day, d) => {
      if (day.name.trim() === "") errors[dayPath(d, "name")] = "nameRequired";
      return {
        ...(day.id ? { id: day.id } : {}),
        weekday: day.weekday,
        name: day.name.trim(),
        exercises: day.exercises.map((e, x) => {
          const at = (field: string) => exercisePath(d, x, field);
          const sets = whole(e.sets, 1, 10);
          if (sets === null) errors[at("sets")] = "sets";
          const rest = whole(e.rest, 0, 600);
          if (rest === null) errors[at("rest_seconds")] = "rest";
          const timed = e.type === "timed";
          let repsMin: number | null = null;
          let repsMax: number | null = null;
          let seconds: number | null = null;
          let weight: number | null = null;
          if (timed) {
            if (e.seconds.trim() !== "") {
              seconds = whole(e.seconds, 5, 14400);
              if (seconds === null) errors[at("target_seconds")] = "seconds";
            }
          } else {
            if (e.repsMin.trim() !== "") {
              repsMin = whole(e.repsMin, 1, 100);
              if (repsMin === null) errors[at("reps_min")] = "reps";
            }
            if (e.repsMax.trim() !== "") {
              repsMax = whole(e.repsMax, 1, 100);
              if (repsMax === null) errors[at("reps_max")] = "reps";
            } else {
              repsMax = repsMin; // fixed reps
            }
            if (e.weight.trim() !== "") {
              weight = toKg(e.weight);
              if (weight === null || weight > 500) errors[at("target_weight_kg")] = "weight";
            }
          }
          const increment = toKg(e.increment);
          if (increment === null || increment > 20) errors[at("increment_kg")] = "increment";
          return {
            ...(e.id ? { id: e.id } : {}),
            exercise_id: e.exerciseId,
            sets: sets ?? 0,
            reps_min: repsMin,
            reps_max: repsMax,
            target_weight_kg: weight,
            target_seconds: seconds,
            rest_seconds: rest ?? 0,
            rule: e.rule,
            increment_kg: increment ?? 0,
            deload_enabled: e.deload,
          };
        }),
      };
    }),
  };
  return Object.keys(errors).length > 0 ? { body: null, errors } : { body, errors };
}

export function move<T>(items: T[], index: number, delta: -1 | 1): T[] {
  const to = index + delta;
  if (to < 0 || to >= items.length) return items;
  const copy = [...items];
  [copy[index], copy[to]] = [copy[to]!, copy[index]!];
  return copy;
}

/** API field names, as constants so JSX never carries string literals. */
export const FIELD = {
  sets: "sets",
  seconds: "target_seconds",
  repsMin: "reps_min",
  repsMax: "reps_max",
  weight: "target_weight_kg",
  rest: "rest_seconds",
  rule: "rule",
  increment: "increment_kg",
  weekday: "weekday",
  name: "name",
  slot: "slot",
  portion: "portion_factor",
} as const;
